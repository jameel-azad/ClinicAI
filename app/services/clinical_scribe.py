import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.graph.scribe.pipeline import scribe_pipeline
from app.graph.scribe.state import ScribeState
from app.services.store import all_appointments
from app.services.whatsapp import send_whatsapp_media_sync, send_whatsapp_message_sync

load_dotenv()

SUPPORTED_AUDIO_CONTENT_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "application/ogg": ".ogg",
}

GENERATED_DIR = Path(os.getenv("SCRIBE_PDF_DIR", "generated/scribe_pdfs"))
_pdf_store: dict[str, str] = {}


async def handle_doctor_voice_note(
    media_url: str,
    media_content_type: str | None,
    doctor_number: str,
    doctor_name: str | None = None,
    caption: str = "",
) -> str:
    if not _is_supported_audio(media_content_type):
        return "I received media from the doctor, but it was not a supported audio voice note."

    audio_path = None
    try:
        audio_path = await _download_audio(media_url, media_content_type)
        result = _run_scribe_pipeline(
            audio_path=audio_path,
            doctor_name=doctor_name,
            patient_hint=_patient_hint_from_caption(caption),
        )

        pdf_path = result.get("pdf_path", "")
        if not pdf_path or not os.path.exists(pdf_path):
            warnings = "; ".join(result.get("errors", []))
            return f"I transcribed the voice note, but could not generate the PDF. {warnings}".strip()

        document_id, stored_pdf = store_scribe_pdf(pdf_path)
        patient_number = _resolve_patient_number(result, doctor_name, caption)
        patient_name = _patient_name(result)

        # Store pending SOAP — doctor must approve before it reaches the patient
        soap_id = "SOAP" + str(uuid.uuid4())[:6].upper()
        from app.services.store import save_pending_soap
        save_pending_soap(soap_id, {
            "document_id": document_id,
            "patient_number": patient_number,
            "patient_name": patient_name,
            "doctor_number": doctor_number,
        })

        public_url = _public_pdf_url(document_id)

        if patient_number:
            approval_msg = (
                f"📋 Prescription note ready for *{patient_name or 'patient'}*.\n\n"
                "Review the PDF and reply:\n"
                f"✅ *APPROVE {soap_id}* — sends to {patient_number}\n"
                f"❌ *REJECT {soap_id}* — discards the note"
            )
        else:
            approval_msg = (
                "📋 Prescription note generated — patient could not be identified automatically.\n\n"
                "Review the PDF and reply:\n"
                f"✅ *APPROVE {soap_id} +PATIENT_NUMBER* — sends to the specified number\n"
                f"❌ *REJECT {soap_id}* — discards the note\n\n"
                "💡 Include the patient's WhatsApp number after APPROVE."
            )

        if public_url:
            send_whatsapp_media_sync(doctor_number, approval_msg, public_url)
        else:
            send_whatsapp_message_sync(
                doctor_number,
                approval_msg + f"\n\n(PDF saved at: {stored_pdf})",
            )

        return "Voice note transcribed. Prescription note sent to you for review — approve it to deliver to the patient."
    except Exception as exc:
        return f"Sorry, I could not process the doctor's voice note: {exc}"
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


def store_scribe_pdf(pdf_path: str) -> tuple[str, str]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid.uuid4())
    target = GENERATED_DIR / f"{document_id}.pdf"
    shutil.copyfile(pdf_path, target)
    _pdf_store[document_id] = str(target)
    return document_id, str(target)


def get_scribe_pdf_path(document_id: str) -> str | None:
    stored = _pdf_store.get(document_id)
    if stored and os.path.exists(stored):
        return stored

    target = GENERATED_DIR / f"{document_id}.pdf"
    if target.exists():
        return str(target)
    return None


async def _download_audio(media_url: str, media_content_type: str | None) -> str:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    auth = (account_sid, auth_token) if account_sid and auth_token else None
    suffix = SUPPORTED_AUDIO_CONTENT_TYPES.get((media_content_type or "").lower(), ".ogg")

    async with httpx.AsyncClient() as client:
        response = await client.get(media_url, auth=auth, follow_redirects=True)
        response.raise_for_status()

    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)
    return temp_path


def _run_scribe_pipeline(
    audio_path: str,
    doctor_name: str | None,
    patient_hint: str | None,
) -> ScribeState:
    initial_state: ScribeState = {
        "audio_path": audio_path,
        "doctor_name": doctor_name,
        "patient_name": patient_hint,
        "clinic_name": os.getenv("CLINIC_NAME", "ClinicAI"),
        "errors": [],
    }
    return scribe_pipeline.invoke(initial_state)


def _resolve_patient_number(result: ScribeState, doctor_name: str | None, caption: str) -> str | None:
    number_from_caption = _patient_number_from_caption(caption)
    if number_from_caption:
        return number_from_caption

    patient_name = _patient_name(result)
    appointments = list(all_appointments().values())
    if doctor_name:
        normalized_doctor = _normalise(doctor_name)
        doctor_matches = [
            appt for appt in appointments
            if _normalise(appt.get("doctor_name")) == normalized_doctor
        ]
        if doctor_matches:
            appointments = doctor_matches

    if patient_name:
        wanted = _normalise(patient_name)
        name_matches = [
            appt for appt in appointments
            if wanted and wanted in _normalise(appt.get("patient_name"))
        ]
        if len(name_matches) == 1:
            return name_matches[0].get("from_number")
        if name_matches:
            appointments = name_matches

    appointments.sort(key=lambda item: item.get("confirmed_at", ""), reverse=True)
    if len(appointments) == 1:
        return appointments[0].get("from_number")
    return None


def _patient_name(result: ScribeState) -> str:
    soap_note = result.get("soap_note", {})
    return (
        result.get("patient_name")
        or soap_note.get("patient_name")
        or ""
    ).strip()


def _patient_hint_from_caption(caption: str) -> str | None:
    match = re.search(r"(?:patient|for)\s*[:\-]?\s*([A-Za-z][A-Za-z .]{1,60})", caption, re.I)
    if match:
        return match.group(1).strip()
    return None


def _patient_number_from_caption(caption: str) -> str | None:
    match = re.search(r"(?:\+?\d[\d\s\-()]{8,}\d)", caption)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    if not digits:
        return None
    return f"+{digits}" if match.group(0).strip().startswith("+") else digits


def _public_pdf_url(document_id: str) -> str | None:
    base_url = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("WEBHOOK_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/scribe/pdf/{document_id}"


def _is_supported_audio(media_content_type: str | None) -> bool:
    return (media_content_type or "").lower() in SUPPORTED_AUDIO_CONTENT_TYPES


def _normalise(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
