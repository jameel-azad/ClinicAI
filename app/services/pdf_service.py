import asyncio
import logging
import os
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

try:
    from app.graph.parser.pipeline import lab_report_pipeline
except ImportError:
    lab_report_pipeline = None
    print("Warning: Could not import app.graph.parser.pipeline")

from app.services.whatsapp import download_media_bytes

load_dotenv()
logger = logging.getLogger(__name__)

LAB_PDF_DIR = Path(os.getenv("LAB_PDF_DIR", "generated/lab_pdfs"))
_lab_pdf_store: dict[str, str] = {}


def store_lab_pdf(pdf_path: str) -> tuple[str, str]:
    """Copy the lab report PDF to permanent storage and return (document_id, stored_path)."""
    LAB_PDF_DIR.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid.uuid4())
    target = LAB_PDF_DIR / f"{document_id}.pdf"
    shutil.copyfile(pdf_path, target)
    stored_path = str(target)
    _lab_pdf_store[document_id] = stored_path
    # Register in Redis so other workers can serve this PDF
    try:
        from app.services.store import register_pdf
        register_pdf("lab", document_id, stored_path)
    except Exception:
        pass
    return document_id, stored_path


def get_lab_pdf_path(document_id: str) -> str | None:
    # 1. In-process cache (fastest, same worker)
    stored = _lab_pdf_store.get(document_id)
    if stored and os.path.exists(stored):
        return stored
    # 2. Cross-worker Redis registry
    try:
        from app.services.store import lookup_pdf
        redis_path = lookup_pdf("lab", document_id)
        if redis_path and os.path.exists(redis_path):
            return redis_path
    except Exception:
        pass
    # 3. Filesystem fallback (shared volume)
    target = LAB_PDF_DIR / f"{document_id}.pdf"
    return str(target) if target.exists() else None


def _lab_pdf_public_url(document_id: str) -> str | None:
    base_url = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("WEBHOOK_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/lab-report/pdf/{document_id}"


async def download_media(media_id: str) -> str:
    """Download media from Meta via media_id to a temporary PDF file and return the path."""
    pdf_bytes = await download_media_bytes(media_id)
    if pdf_bytes is None:
        raise RuntimeError(f"Failed to download media for media_id={media_id}")
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(pdf_bytes)
    return temp_path


def check_safety(pdf_path: str) -> bool:
    """
    Check whether the PDF appears to be a legitimate medical or lab report.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return False
            first_page = pdf.pages[0].extract_text()
            if not first_page:
                return False
    except Exception as e:
        logger.error(f"Error reading PDF for safety check: {e}")
        return False

    prompt = """
    You are a safety filter for a medical AI system.
    Review the following text extracted from the first page of a document.
    Determine if this document appears to be a legitimate medical or laboratory report.
    If it contains any explicit, malicious, harmful, or clearly non-medical spam content, respond with "UNSAFE".
    If it looks like a standard medical/lab document (even if partial), respond with "SAFE".
    Reply with ONLY the word "SAFE" or "UNSAFE".
    """

    try:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        llm = ChatGroq(
            model=model,
            temperature=0,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"--- DOCUMENT TEXT ---\n{first_page[:2000]}\n--- END TEXT ---"),
        ]
        response = llm.invoke(messages)
        content = response.content.strip().upper()
        return "SAFE" in content
    except Exception as e:
        logger.error(f"Safety check LLM error: {e}")
        return False


def format_report_reply(state: dict) -> str:
    """Format parser output into a WhatsApp-friendly message."""
    errors = state.get("errors", [])
    if errors:
        return "Sorry, I encountered an error while processing the report: " + "; ".join(errors)

    patient_info = state.get("patient_info", {})
    name = patient_info.get("name", "Unknown")
    summary = state.get("doctor_summary", "No summary available.")

    reply_lines = [
        "Lab Report Analysis",
        f"Patient: {name}",
        "",
        "Summary:",
        summary,
        "",
    ]

    abnormals = state.get("abnormals", [])
    if abnormals:
        reply_lines.append(f"Abnormal Findings ({len(abnormals)}):")
        for ab in abnormals:
            marker = "CRITICAL" if ab.get("status") == "CRITICAL" else "ABNORMAL"
            reply_lines.append(
                f"{marker}: {ab.get('parameter')}: {ab.get('value')} "
                f"{ab.get('unit', '')} (Ref: {ab.get('reference_range')}) "
                f"[{ab.get('status')}]"
            )
    else:
        reply_lines.append("No abnormal values detected.")

    return "\n".join(reply_lines)


async def handle_incoming_pdf(media_id: str, from_number: str = "") -> str:
    """
    Handle a WhatsApp PDF from a patient:
    1. Download + safety check + parse (pipeline runs in a thread to avoid blocking the event loop)
    2. Forward the full report summary to the doctor(s)
    3. Return a brief acknowledgment to the patient
    """
    if not lab_report_pipeline:
        return "Sorry, the report parser is currently offline."

    temp_path = None
    try:
        temp_path = await download_media(media_id)

        if not await asyncio.to_thread(check_safety, temp_path):
            return "This document does not appear to be a valid lab report or could not be verified for safety."

        print(f"[Parser] Invoking pipeline for {temp_path}")
        # Run the synchronous LangGraph pipeline in a thread so it doesn't block the event loop
        final_state = await asyncio.to_thread(
            lab_report_pipeline.invoke, {"pdf_path": temp_path}
        )

        errors = final_state.get("errors", [])
        if errors and not final_state.get("doctor_summary"):
            return "Sorry, I had trouble reading that report. Please ask the clinic to check it manually."

        # Store PDF permanently before cleanup so we can share the original with the doctor
        document_id, _ = store_lab_pdf(temp_path)
        pdf_url = _lab_pdf_public_url(document_id)

        lab_id = "LAB" + str(uuid.uuid4())[:6].upper()
        doctor_numbers = _find_doctor_for_patient(from_number)
        _forward_report_to_doctor(final_state, from_number, pdf_url, lab_id=lab_id, doctor_numbers=doctor_numbers)

        if doctor_numbers:
            from app.services.store import save_pending_lab_review
            patient_info = final_state.get("patient_info", {})
            save_pending_lab_review(lab_id, {
                "patient_number": from_number,
                "patient_name": patient_info.get("name") or "",
                "doctor_number": doctor_numbers[0],   # primary for ACK lookup
                "doctor_numbers": doctor_numbers,      # full list for multi-doctor awareness
            })

        # Save lab record to DB so it appears in dashboard medical history
        try:
            from app.services.store import get_session
            from app.services.patient_service import save_lab_record
            booking = get_session(from_number)
            clinic_id = booking.clinic_id if booking else None
            if clinic_id:
                patient_info = final_state.get("patient_info") or {}
                await save_lab_record(
                    clinic_id=clinic_id,
                    patient_phone=from_number,
                    patient_name=patient_info.get("name"),
                    lab_result=final_state,
                    pdf_url=pdf_url,
                )
        except Exception as _le:
            print(f"[PDF] Could not save lab record: {_le}")

        criticals = final_state.get("criticals", [])
        if criticals:
            return (
                "Your lab report has been received and forwarded to the doctor. "
                "⚠️ Some critical values were detected — the doctor will reach out to you shortly."
            )
        return "Your lab report has been received and forwarded to the doctor for review."

    except Exception as e:
        logger.error(f"Error handling PDF: {e!r}\n{traceback.format_exc()}")
        return "Sorry, an error occurred while processing the PDF."
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _find_doctor_for_patient(from_number: str) -> list[str]:
    """Return doctor WhatsApp numbers to notify for this patient.
    Checks the patient's most recent confirmed appointment first,
    then falls back to all configured doctor numbers.
    """
    from app.services.store import get_appointments_by_number
    from app.services.identity import find_doctor_number, all_doctor_numbers, normalize_whatsapp_number

    try:
        if from_number:
            appointments = get_appointments_by_number(normalize_whatsapp_number(from_number))
            if appointments:
                most_recent = max(appointments, key=lambda a: a.confirmed_at)
                doctor_number = find_doctor_number(most_recent.doctor_name)
                if doctor_number:
                    return [doctor_number]
    except Exception as exc:
        logger.warning(f"[pdf_service] Appointment lookup failed: {exc}")

    # Fall back to all configured doctor numbers
    return all_doctor_numbers()


def _forward_report_to_doctor(
    final_state: dict,
    from_number: str,
    pdf_url: str | None = None,
    lab_id: str | None = None,
    doctor_numbers: list[str] | None = None,
) -> None:
    """Send the text summary and (if available) the original PDF to the relevant doctor(s)."""
    from app.services.whatsapp import send_whatsapp_message_sync, send_whatsapp_document_sync

    if doctor_numbers is None:
        doctor_numbers = _find_doctor_for_patient(from_number)
    if not doctor_numbers:
        logger.warning("[Parser] No doctor numbers configured — report not forwarded")
        return

    patient_info = final_state.get("patient_info", {})
    patient_name = patient_info.get("name") or "Unknown patient"
    summary = final_state.get("doctor_summary", "No summary available.")

    lines = [
        f"📋 *Lab Report — {patient_name}*",
        f"Submitted by: {from_number}" if from_number else "",
        "",
        summary,
        "",
    ]

    criticals = [ab for ab in final_state.get("abnormals", []) if ab.get("status") == "CRITICAL"]
    other_abnormals = [ab for ab in final_state.get("abnormals", []) if ab.get("status") != "CRITICAL"]

    if criticals:
        lines.append(f"🚨 *Critical ({len(criticals)}):*")
        for c in criticals:
            lines.append(
                f"• {c['parameter']}: {c['value']} {c.get('unit', '')} "
                f"(ref: {c.get('reference_range')}) — {c.get('critical_reason', 'Critical')}"
            )
        lines.append("")

    if other_abnormals:
        lines.append(f"⚠️ *Other Abnormals ({len(other_abnormals)}):*")
        for ab in other_abnormals:
            lines.append(
                f"• {ab['parameter']}: {ab['value']} {ab.get('unit', '')} "
                f"(ref: {ab.get('reference_range')}) [{ab['status']}]"
            )

    if lab_id:
        lines.append("")
        lines.append(f"Reply *OK {lab_id}* to acknowledge — patient will be notified.")

    message = "\n".join(line for line in lines if line is not None)

    for number in doctor_numbers:
        send_whatsapp_message_sync(number, message)
        if pdf_url:
            send_whatsapp_document_sync(
                number,
                pdf_url,
                "lab_report.pdf",
                f"Original lab report — {patient_name}",
            )
        print(f"[Parser] Report forwarded to doctor {number}")
