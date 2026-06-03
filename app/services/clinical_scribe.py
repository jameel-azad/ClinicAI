import asyncio
import os
import re
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.graph.scribe.nodes import overall_soap_confidence, low_confidence_section_names
from app.graph.scribe.pipeline import scribe_pipeline
from app.graph.scribe.state import ScribeState
from app.services.store import all_appointments
from app.services.whatsapp import download_media_bytes, send_whatsapp_media_sync, send_whatsapp_message_sync

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
    media_id: str,
    media_content_type: str | None,
    doctor_number: str,
    doctor_name: str | None = None,
    caption: str = "",
) -> str:
    if not _is_supported_audio(media_content_type):
        return "I received media from the doctor, but it was not a supported audio voice note."

    # ── Consultation buffer pre-check ──────────────────────────────────────────
    # If an active consultation exists for any patient linked to this doctor,
    # buffer the audio media_id in the consultation session instead of running the
    # local scribe pipeline immediately. Jameel's API receives it on finalize.
    buffered_reply = _try_buffer_doctor_audio(media_id, doctor_number)
    if buffered_reply:
        return buffered_reply
    # ── End consultation buffer pre-check ──────────────────────────────────────

    audio_path = None
    try:
        print(f"[Scribe] Downloading audio via Meta API...")
        audio_path = await _download_audio(media_id, media_content_type)
        print(f"[Scribe] Audio saved to {audio_path}, running scribe pipeline...")
        result = await asyncio.to_thread(
            _run_scribe_pipeline,
            audio_path=audio_path,
            doctor_name=doctor_name,
            patient_hint=_patient_hint_from_caption(caption),
        )
        print(f"[Scribe] Pipeline done. errors={result.get('errors', [])}")

        pipeline_errors = result.get("errors", [])
        for err in pipeline_errors:
            print(f"[scribe_pipeline_error] {err}")

        pdf_path = result.get("pdf_path", "")
        if not pdf_path or not os.path.exists(pdf_path):
            warnings = "; ".join(pipeline_errors)
            return f"I transcribed the voice note, but could not generate the PDF. {warnings}".strip()

        document_id, stored_pdf = store_scribe_pdf(pdf_path)
        patient_number = _resolve_patient_number(result, doctor_name, caption)
        patient_name = _patient_name(result)

        # Store pending prescription — doctor must approve before it reaches the patient
        soap_id = "RX" + str(uuid.uuid4())[:6].upper()
        follow_up_questions = result.get("follow_up_questions") or []
        follow_up_days = result.get("follow_up_days")  # None if doctor didn't mention
        from app.services.store import save_pending_soap
        save_pending_soap(soap_id, {
            "document_id": document_id,
            "patient_number": patient_number,
            "patient_name": patient_name,
            "doctor_number": doctor_number,
            "follow_up_questions": follow_up_questions,
            "follow_up_days": follow_up_days,
            # Stored for REGEN support — allows re-running pipeline without re-transcribing audio
            "transcript": result.get("transcript", ""),
            "soap_note": result.get("soap_note") or {},
            "clinical_entities": result.get("clinical_entities") or {},
            "fhir_bundle": result.get("fhir_bundle") or {},
            "snomed_mappings": result.get("snomed_mappings") or [],
        })

        # ── Confidence check ──────────────────────────────────────────────────
        soap_note = result.get("soap_note", {})
        overall_conf = overall_soap_confidence(soap_note)
        low_conf = low_confidence_section_names(soap_note)

        if overall_conf < 0.6 and low_conf:
            sections_str = ", ".join(f"[{s}]" for s in low_conf)
            confidence_notice = (
                f"\n\n⚠️ *Low confidence warning:* I am not confident about the "
                f"{sections_str} section(s). Please review carefully before sending."
            )
        else:
            confidence_notice = ""
        # ─────────────────────────────────────────────────────────────────────

        public_url = _public_pdf_url(document_id)
        soap_content_sid = os.getenv("SOAP_APPROVAL_CONTENT_SID", "").strip()

        if soap_content_sid:
            # ── Button flow ──────────────────────────────────────────────────────
            # 1. Send the PDF so the doctor can read it
            if public_url:
                pdf_caption = (
                    f"📋 Prescription note for {patient_name or 'patient'} — review before approving."
                    f"{confidence_notice}"
                )
                send_whatsapp_media_sync(doctor_number, pdf_caption, public_url)

            # 2. Send the approval buttons via Content Template
            from app.services.whatsapp import send_whatsapp_template_sync
            send_whatsapp_template_sync(
                doctor_number,
                soap_content_sid,
                {
                    "1": patient_name or "unknown patient",
                    "2": patient_number or "not identified — include number when approving",
                },
            )
        else:
            # ── Text fallback (no template configured) ───────────────────────────
            fhir_summary = _format_fhir_whatsapp_summary(
                result.get("snomed_mappings") or [],
                result.get("fhir_bundle") or {},
            )
            if patient_number:
                approval_msg = (
                    f"📋 Prescription note ready for *{patient_name or 'patient'}*.\n\n"
                    + fhir_summary
                    + "Review the PDF and reply:\n"
                    f"✅ *APPROVE {soap_id}* — sends to {patient_number}\n"
                    f"❌ *REJECT {soap_id}* — discards the note\n"
                    f"🔄 *REGEN {soap_id} <correction>* — regenerates with your feedback"
                    f"{confidence_notice}"
                )
            else:
                approval_msg = (
                    "📋 Prescription note generated — patient could not be identified automatically.\n\n"
                    + fhir_summary
                    + "Review the PDF and reply:\n"
                    f"✅ *APPROVE {soap_id} +PATIENT_NUMBER* — sends to the specified number\n"
                    f"❌ *REJECT {soap_id}* — discards the note\n"
                    f"🔄 *REGEN {soap_id} <correction>* — regenerates with your feedback\n\n"
                    "💡 Include the patient's WhatsApp number after APPROVE."
                    f"{confidence_notice}"
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
        print(f"[Scribe] UNHANDLED ERROR:\n{traceback.format_exc()}")
        return f"Sorry, I could not process the doctor's voice note: {exc}"
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


def store_scribe_pdf(pdf_path: str) -> tuple[str, str]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid.uuid4())
    target = GENERATED_DIR / f"{document_id}.pdf"
    shutil.copyfile(pdf_path, target)
    stored_path = str(target)
    _pdf_store[document_id] = stored_path
    # Register in Redis so other workers can serve this PDF
    try:
        from app.services.store import register_pdf
        register_pdf("scribe", document_id, stored_path)
    except Exception:
        pass
    return document_id, stored_path


def get_scribe_pdf_path(document_id: str) -> str | None:
    # 1. In-process cache (fastest, same worker)
    stored = _pdf_store.get(document_id)
    if stored and os.path.exists(stored):
        return stored
    # 2. Cross-worker Redis registry
    try:
        from app.services.store import lookup_pdf
        redis_path = lookup_pdf("scribe", document_id)
        if redis_path and os.path.exists(redis_path):
            return redis_path
    except Exception:
        pass
    # 3. Filesystem fallback (shared volume)
    target = GENERATED_DIR / f"{document_id}.pdf"
    if target.exists():
        return str(target)
    return None


async def _download_audio(media_id: str, media_content_type: str | None) -> str:
    suffix = SUPPORTED_AUDIO_CONTENT_TYPES.get((media_content_type or "").lower(), ".ogg")
    audio_bytes = await download_media_bytes(media_id)
    if audio_bytes is None:
        raise RuntimeError(f"Failed to download audio for media_id={media_id}")
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(audio_bytes)
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


def _try_buffer_doctor_audio(media_id: str, doctor_number: str) -> str | None:
    """
    If any patient has an active ConsultationSession linked to this doctor,
    buffer the audio media_id there and return an ack string.
    Returns None if no active consultation — caller should run local scribe.
    """
    try:
        from app.services.store import get_consultation, save_consultation
        from app.services.identity import all_doctor_numbers, find_doctor_name
        from app.schemas import ConsultationMessage
        import redis as _redis_lib
        import os as _os
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        r_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
        r = _redis_lib.Redis.from_url(r_url, decode_responses=True, socket_connect_timeout=2)
        r.ping()

        import re as _re
        _UUID_RE = _re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:",
            _re.I,
        )
        prefix = "clinicai:consult:"
        for key in r.scan_iter(f"{prefix}*"):
            patient_number = key.removeprefix(prefix)
            # Skip clinic-scoped keys (format: "clinic_id:phone"); the same
            # session is always accessible via the legacy "phone-only" key.
            if _UUID_RE.match(patient_number):
                continue
            session = get_consultation(patient_number)
            if not session or not session.is_active:
                continue
            if session.doctor_number != doctor_number:
                continue

            now = _dt.now(_ZI(_os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")))
            msg = ConsultationMessage(
                sender_role="doctor",
                audio_url=media_id,
                timestamp=now,
            )
            session.messages.append(msg)
            session.audio_files.append({"url": media_id, "duration_secs": None})
            save_consultation(patient_number, session)

            print(f"[Scribe] Buffered doctor audio in consultation {session.consultation_id}")
            return (
                "🎙️ Voice note received and added to the active consultation buffer.\n"
                "Send *ok done* or *take care* when the consultation is complete."
            )
    except Exception as exc:
        print(f"[Scribe] _try_buffer_doctor_audio: {exc}")
    return None


def _format_fhir_whatsapp_summary(snomed_mappings: list, fhir_bundle: dict) -> str:
    """Build a compact SNOMED+RxNorm summary for the doctor's WhatsApp approval message."""
    lines = []
    if snomed_mappings:
        lines.append("*Coded Diagnoses (SNOMED CT):*")
        for m in snomed_mappings[:4]:
            term = m.get("clinical_term", "")
            code = m.get("snomed_concept_id", "")
            if term:
                lines.append(f"  • {term}" + (f" [{code}]" if code and code != "UNKNOWN" else ""))
    med_resources = [
        e["resource"] for e in fhir_bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == "MedicationRequest"
    ]
    if med_resources:
        lines.append("*Medications (RxNorm):*")
        for res in med_resources[:4]:
            med = res.get("medicationCodeableConcept", {})
            codings = med.get("coding", [{}])
            code = codings[0].get("code", "") if codings else ""
            text = med.get("text") or (codings[0].get("display", "") if codings else "")
            if text:
                lines.append(f"  • {text}" + (f" [{code}]" if code and code != "UNKNOWN" else ""))
    return "\n".join(lines) + "\n\n" if lines else ""


def _is_supported_audio(media_content_type: str | None) -> bool:
    return (media_content_type or "").lower() in SUPPORTED_AUDIO_CONTENT_TYPES


def _normalise(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
