import os
import re

from app.services.clinical_scribe import get_scribe_pdf_path
from app.services.store import delete_pending_soap, get_latest_soap_for_doctor, get_pending_soap
from app.services.whatsapp import send_whatsapp_media_sync, send_whatsapp_message_sync


def handle_soap_button_reply(button_payload: str, doctor_number: str) -> str | None:
    """Handle APPROVE/REJECT tapped from a WhatsApp button (ButtonPayload field)."""
    payload = button_payload.strip().lower()
    if payload not in ("soap_approve", "soap_reject"):
        return None

    soap = get_latest_soap_for_doctor(doctor_number)
    if not soap:
        return "No pending prescriptions found for your number."

    soap_id = soap.get("soap_id", "")
    if payload == "soap_approve":
        return _approve(soap_id, None)
    return _reject(soap_id)


def handle_soap_approval_reply(message: str, doctor_number: str) -> str | None:
    upper = message.strip().upper()

    approve_match = re.match(
        r"APPROVE\s+((?:SOAP|RX)[A-F0-9]{6})(?:\s+(\+?\d[\d\s\-()+]{7,}\d))?", upper
    )
    reject_match = re.match(r"REJECT\s+((?:SOAP|RX)[A-F0-9]{6})", upper)

    if approve_match:
        return _approve(approve_match.group(1), approve_match.group(2))

    if reject_match:
        return _reject(reject_match.group(1))

    return None


def _approve(soap_id: str, override_number: str | None) -> str | None:
    soap = get_pending_soap(soap_id)
    if not soap:
        return None

    patient_number = override_number or soap.get("patient_number")
    patient_name = soap.get("patient_name") or "patient"
    document_id = soap.get("document_id")

    if not patient_number:
        return (
            f"Please include the patient's WhatsApp number:\n"
            f"*APPROVE {soap_id} +PATIENT_NUMBER*"
        )

    digits = re.sub(r"\D", "", patient_number)
    patient_number = f"+{digits}" if patient_number.strip().startswith("+") else digits

    public_url = _scribe_pdf_url(document_id)
    body = f"Doctor's consultation note for {patient_name} is attached."

    delete_pending_soap(soap_id)

    if public_url:
        sent = send_whatsapp_media_sync(patient_number, body, public_url)
        if sent:
            return f"✅ Prescription note approved and sent to {patient_number}."
        return f"⚠️ Approved but WhatsApp delivery to {patient_number} failed. Please send manually."

    pdf_path = get_scribe_pdf_path(document_id) if document_id else None
    return (
        f"✅ Approved, but PUBLIC_BASE_URL is not configured — cannot attach via Twilio.\n"
        f"Please forward manually to {patient_number}.\n"
        f"PDF: {pdf_path or 'unavailable'}"
    )


def _reject(soap_id: str) -> str | None:
    soap = get_pending_soap(soap_id)
    if not soap:
        return None
    delete_pending_soap(soap_id)
    return f"❌ Prescription note {soap_id} rejected and discarded."


def _scribe_pdf_url(document_id: str | None) -> str | None:
    if not document_id:
        return None
    base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/scribe/pdf/{document_id}"
