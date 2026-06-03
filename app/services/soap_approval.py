import os
import re
import shutil

from app.services.clinical_scribe import get_scribe_pdf_path, _format_fhir_whatsapp_summary
from app.services.store import delete_pending_soap, get_latest_soap_for_doctor, get_pending_soap, save_pending_soap
from app.services.whatsapp import send_whatsapp_document_sync, send_whatsapp_message_sync


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
    # Match REGEN with original casing preserved so feedback text isn't uppercased
    regen_match = re.match(
        r"REGEN\s+((?:SOAP|RX)[A-F0-9]{6})(?:\s+(.+))?",
        message.strip(),
        re.DOTALL | re.IGNORECASE,
    )

    if approve_match:
        return _approve(approve_match.group(1), approve_match.group(2))

    if reject_match:
        return _reject(reject_match.group(1))

    if regen_match:
        return _regen(regen_match.group(1).upper(), (regen_match.group(2) or "").strip())

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
    caption = f"Doctor's consultation note for {patient_name} is attached."

    delete_pending_soap(soap_id)

    follow_up_questions = soap.get("follow_up_questions") or []
    follow_up_days = soap.get("follow_up_days")

    if public_url:
        filename = f"consultation_{soap_id}.pdf"
        sent = send_whatsapp_document_sync(patient_number, public_url, filename, caption)
        if sent:
            _mark_post_consult(patient_number)
            _schedule_followup(patient_number, patient_name, soap.get("doctor_number", ""), follow_up_questions, follow_up_days)
            _save_consultation_record(soap, patient_number, patient_name, public_url)
            return f"✅ Prescription note approved and sent to {patient_number}."
        return f"⚠️ Approved but WhatsApp delivery to {patient_number} failed. Please send manually."

    pdf_path = get_scribe_pdf_path(document_id) if document_id else None
    return (
        f"✅ Approved, but PUBLIC_BASE_URL is not configured — cannot attach the PDF.\n"
        f"Please forward manually to {patient_number}.\n"
        f"PDF: {pdf_path or 'unavailable'}"
    )


def _reject(soap_id: str) -> str | None:
    soap = get_pending_soap(soap_id)
    if not soap:
        return None
    delete_pending_soap(soap_id)
    return f"❌ Prescription note {soap_id} rejected and discarded."


def _regen(soap_id: str, feedback: str) -> str | None:
    """Re-run the SOAP + FHIR pipeline using the stored transcript and doctor feedback."""
    soap = get_pending_soap(soap_id)
    if not soap:
        return None

    transcript = soap.get("transcript", "")
    if not transcript:
        return (
            f"Cannot regenerate {soap_id} — the original transcript was not stored. "
            "Please record a new voice note."
        )

    document_id = soap.get("document_id", "")
    patient_name = soap.get("patient_name", "")
    patient_number = soap.get("patient_number", "")
    doctor_number = soap.get("doctor_number", "")
    doctor_name = soap.get("doctor_name", "")

    augmented_transcript = (
        f"[DOCTOR CORRECTION: {feedback}]\n\n--- ORIGINAL TRANSCRIPT ---\n{transcript}"
        if feedback
        else transcript
    )

    try:
        from app.graph.scribe.nodes import (
            soap_generator_node,
            extract_entities_node,
            fhir_coding_node,
            grounding_check_node,
            followup_generator_node,
            pdf_output_node,
        )
        from app.graph.scribe.state import ScribeState
        from app.services.clinical_scribe import GENERATED_DIR, _pdf_store, _public_pdf_url

        state: ScribeState = {
            "audio_path": "",
            "transcript": augmented_transcript,
            "doctor_name": doctor_name,
            "patient_name": patient_name,
            "clinic_name": os.getenv("CLINIC_NAME", "ClinicAI"),
            "errors": [],
        }

        state = {**state, **soap_generator_node(state)}
        state = {**state, **extract_entities_node(state)}
        state = {**state, **fhir_coding_node(state)}
        state = {**state, **grounding_check_node(state)}
        state = {**state, **followup_generator_node(state)}
        state = {**state, **pdf_output_node(state)}

        new_pdf_path = state.get("pdf_path", "")
        if not new_pdf_path or not os.path.exists(new_pdf_path):
            return f"Regeneration failed — PDF could not be generated for {soap_id}."

        # Overwrite the existing stored PDF (same document_id keeps the URL stable)
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        target = GENERATED_DIR / f"{document_id}.pdf"
        shutil.copyfile(new_pdf_path, str(target))
        _pdf_store[document_id] = str(target)

        # Update Redis record in-place — keep original transcript for future REGENs
        save_pending_soap(soap_id, {
            **soap,
            "transcript": transcript,
            "clinical_entities": state.get("clinical_entities") or {},
            "fhir_bundle": state.get("fhir_bundle") or {},
            "snomed_mappings": state.get("snomed_mappings") or [],
            "follow_up_questions": state.get("follow_up_questions") or [],
            "follow_up_days": state.get("follow_up_days"),
        })

        fhir_summary = _format_fhir_whatsapp_summary(
            state.get("snomed_mappings") or [],
            state.get("fhir_bundle") or {},
        )
        public_url = _public_pdf_url(document_id)

        regen_msg = (
            f"🔄 Regenerated prescription for *{patient_name or 'patient'}*.\n\n"
            + (f"Feedback applied: _{feedback}_\n\n" if feedback else "")
            + fhir_summary
            + "Reply:\n"
            f"✅ *APPROVE {soap_id}* — sends to patient\n"
            f"❌ *REJECT {soap_id}* — discards\n"
            f"🔄 *REGEN {soap_id} <more feedback>* — regenerate again"
        )

        if public_url:
            filename = f"consultation_{soap_id}.pdf"
            send_whatsapp_document_sync(doctor_number, public_url, filename, regen_msg)
        else:
            send_whatsapp_message_sync(doctor_number, regen_msg)

        return f"🔄 Regenerating prescription for {soap_id} — updated note sent to you for review."

    except Exception as exc:
        return f"Regeneration failed for {soap_id}: {exc}"


def _scribe_pdf_url(document_id: str | None) -> str | None:
    if not document_id:
        return None
    base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/scribe/pdf/{document_id}"


def _mark_post_consult(patient_number: str) -> None:
    """Transition patient session to POST_CONSULT so follow-up messages route correctly."""
    try:
        from app.services.store import get_session, save_session
        from app.schemas import BookingSession
        session = get_session(patient_number) or BookingSession(from_number=patient_number)
        session.journey_state = "POST_CONSULT"
        save_session(session)
        print(f"[SOAP] journey_state → POST_CONSULT for {patient_number}")
    except Exception as exc:
        print(f"[SOAP] Could not update patient session to POST_CONSULT: {exc}")


def _save_consultation_record(soap: dict, patient_number: str, patient_name: str, pdf_url: str | None) -> None:
    """Fire-and-forget: persist consultation to DB so it appears in the dashboard."""
    try:
        import asyncio
        from app.services.store import get_session
        from app.services.patient_service import save_consultation_record

        booking = get_session(patient_number)
        clinic_id = booking.clinic_id if booking else None
        if not clinic_id:
            return

        soap_result = {
            "soap_note": soap.get("soap_note") or {},
            "clinical_entities": soap.get("clinical_entities") or {},
            "fhir_bundle": soap.get("fhir_bundle") or {},
            "soap_note_pdf_url": pdf_url,
        }
        loop = asyncio.get_running_loop()
        loop.create_task(save_consultation_record(
            clinic_id=clinic_id,
            patient_phone=patient_number,
            patient_name=patient_name,
            doctor_phone=soap.get("doctor_number"),
            chief_complaint=None,
            soap_result=soap_result,
        ))
    except Exception as exc:
        print(f"[SOAP] Could not save consultation record: {exc}")


def _schedule_followup(
    patient_number: str,
    patient_name: str,
    doctor_number: str,
    follow_up_questions: list,
    follow_up_days: int | None,
) -> None:
    """Schedule the follow-up check-in message for the patient."""
    try:
        from app.services.store import get_latest_appointment_for_patient
        from app.services.scheduler import schedule_followup_message

        appt = get_latest_appointment_for_patient(patient_number)
        doctor_name = appt.doctor_name if appt else doctor_number

        schedule_followup_message(
            patient_number=patient_number,
            patient_name=patient_name or "",
            doctor_name=doctor_name,
            follow_up_questions=follow_up_questions,
            follow_up_days=follow_up_days,
        )
    except Exception as exc:
        print(f"[SOAP] Could not schedule follow-up message: {exc}")
