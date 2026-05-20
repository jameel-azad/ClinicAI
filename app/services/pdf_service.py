import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx
import pdfplumber
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

try:
    from app.graph.parser.pipeline import lab_report_pipeline
except ImportError:
    lab_report_pipeline = None
    print("Warning: Could not import app.graph.parser.pipeline")

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
    _lab_pdf_store[document_id] = str(target)
    return document_id, str(target)


def get_lab_pdf_path(document_id: str) -> str | None:
    stored = _lab_pdf_store.get(document_id)
    if stored and os.path.exists(stored):
        return stored
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


async def download_media(media_url: str) -> str:
    """Download media from Twilio to a temporary PDF file and return the path."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    auth = (account_sid, auth_token) if account_sid and auth_token else None

    async with httpx.AsyncClient() as client:
        response = await client.get(media_url, auth=auth, follow_redirects=True)
        response.raise_for_status()

        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(response.content)

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


async def handle_incoming_pdf(media_url: str, from_number: str = "") -> str:
    """
    Handle a WhatsApp PDF from a patient:
    1. Download + safety check + parse
    2. Forward the full report summary to the doctor
    3. Return a brief acknowledgment to the patient
    """
    if not lab_report_pipeline:
        return "Sorry, the report parser is currently offline."

    temp_path = None
    try:
        temp_path = await download_media(media_url)

        if not check_safety(temp_path):
            return "This document does not appear to be a valid lab report or could not be verified for safety."

        print(f"[Parser] Invoking pipeline for {temp_path}")
        final_state = lab_report_pipeline.invoke({"pdf_path": temp_path})

        errors = final_state.get("errors", [])
        if errors and not final_state.get("doctor_summary"):
            return "Sorry, I had trouble reading that report. Please ask the clinic to check it manually."

        # Only forward if the patient has an existing booking
        if not _find_doctor_for_patient(from_number):
            return (
                "We couldn't find an active booking for your number. "
                "Please book an appointment first, then share your lab report."
            )

        # Store PDF permanently before cleanup so we can share the original with the doctor
        document_id, _ = store_lab_pdf(temp_path)
        pdf_url = _lab_pdf_public_url(document_id)

        lab_id = "LAB" + str(uuid.uuid4())[:6].upper()
        doctor_numbers = _find_doctor_for_patient(from_number)
        _forward_report_to_doctor(final_state, from_number, pdf_url, lab_id=lab_id)

        if doctor_numbers:
            from app.services.store import save_pending_lab_review
            patient_info = final_state.get("patient_info", {})
            save_pending_lab_review(lab_id, {
                "patient_number": from_number,
                "patient_name": patient_info.get("name") or "",
                "doctor_number": doctor_numbers[0],
            })

        criticals = final_state.get("criticals", [])
        if criticals:
            return (
                "Your lab report has been received and forwarded to the doctor. "
                "⚠️ Some critical values were detected — the doctor will reach out to you shortly."
            )
        return "Your lab report has been received and forwarded to the doctor for review."

    except Exception as e:
        logger.error(f"Error handling PDF: {e}")
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

    if from_number:
        appointments = get_appointments_by_number(normalize_whatsapp_number(from_number))
        if appointments:
            most_recent = max(appointments, key=lambda a: a.confirmed_at)
            doctor_number = find_doctor_number(most_recent.doctor_name)
            if doctor_number:
                return [doctor_number]

    return []


def _forward_report_to_doctor(
    final_state: dict,
    from_number: str,
    pdf_url: str | None = None,
    lab_id: str | None = None,
) -> None:
    """Send the text summary and (if available) the original PDF to the relevant doctor(s)."""
    from app.services.whatsapp import send_whatsapp_message_sync, send_whatsapp_media_sync

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
            send_whatsapp_media_sync(
                number,
                f"Original lab report — {patient_name}",
                pdf_url,
            )
        print(f"[Parser] Report forwarded to doctor {number}")
