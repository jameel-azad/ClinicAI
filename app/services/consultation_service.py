"""
Consultation bundle builder and Jameel scribe API integration.

When JAMEEL_SCRIBE_URL is set in .env, the consultation bundle is POSTed to
Jameel's API and the result is delivered to the doctor via WhatsApp.

When JAMEEL_SCRIBE_URL is empty (default), stub mode kicks in:
the existing local scribe pipeline is bypassed and a placeholder summary
is returned so the rest of the flow (doctor notification, journey state update)
can be tested end-to-end without Jameel's API being ready.
"""

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

load_dotenv()

JAMEEL_SCRIBE_URL = os.getenv("JAMEEL_SCRIBE_URL", "").strip()
_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")


def build_consultation_bundle(session) -> dict:
    """Build the consultation_bundle matching Jameel's integration contract."""
    return {
        "patient_id": session.patient_number,
        "doctor_id": session.doctor_number,
        "messages": [
            {
                "sender_role": m.sender_role,
                "text": m.text,
                "audio_url": m.audio_url,
                "duration_secs": m.duration_secs,
                "timestamp": m.timestamp.isoformat() if hasattr(m.timestamp, "isoformat") else str(m.timestamp),
            }
            for m in session.messages
        ],
        "audio_files": session.audio_files,
    }


async def _call_jameel(bundle: dict) -> dict:
    """
    POST consultation bundle to Jameel's API.

    If JAMEEL_SCRIBE_URL is set: call the external API.
    If empty: run the local scribe pipeline directly (same app, no HTTP hop).
    """
    if not JAMEEL_SCRIBE_URL:
        from app.services.scribe_service import process_consultation_bundle
        try:
            return await process_consultation_bundle(bundle)
        except Exception as exc:
            print(f"[ConsultationService] Local scribe pipeline failed: {exc}")
            return {
                "soap_note_pdf_url": None,
                "follow_up_questions": [],
                "missing_sections": [],
                "summary_for_whatsapp": (
                    "Consultation recorded. Your doctor will follow up shortly. 🙏"
                ),
            }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(JAMEEL_SCRIBE_URL, json=bundle)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        print(f"[ConsultationService] Jameel API call failed: {exc}")
        return {
            "soap_note_pdf_url": None,
            "follow_up_questions": [],
            "missing_sections": [],
            "summary_for_whatsapp": (
                "Consultation recorded. Your doctor will follow up shortly. 🙏"
            ),
        }


async def finalize_and_send(patient_number: str) -> str:
    """
    1. Load ConsultationSession from Redis
    2. Build consultation_bundle per Jameel's contract
    3. Call Jameel API (or stub)
    4. Send summary_for_whatsapp to doctor
    5. Store follow-up questions on BookingSession, set journey_state = POST_CONSULT
    6. Delete ConsultationSession from Redis
    Returns: reply message to send to patient
    """
    from app.services.store import (
        get_consultation, delete_consultation,
        get_session, save_session,
    )
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.schemas import BookingSession

    session = get_consultation(patient_number)
    if not session:
        return "Consultation session not found — please contact the clinic."

    bundle = build_consultation_bundle(session)
    result = await _call_jameel(bundle)

    summary = result.get("summary_for_whatsapp", "")
    follow_up_qs = result.get("follow_up_questions", [])
    soap_pdf_url = result.get("soap_note_pdf_url")
    low_conf_sections = result.get("low_confidence_sections", [])

    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    doctor_summary = (
        f"📋 *{clinic_name} — Consultation Summary*\n\n"
        f"Patient: *{patient_number}*\n"
        f"Messages: {len(session.messages)} | Audio files: {len(session.audio_files)}\n"
        f"Ended: {session.ended_reason or 'closing phrase'}\n\n"
        f"{summary}"
    )
    if follow_up_qs:
        qs_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(follow_up_qs))
        doctor_summary += f"\n\n*Follow-up questions to ask patient:*\n{qs_text}"
    if soap_pdf_url:
        doctor_summary += f"\n\n📄 SOAP PDF: {soap_pdf_url}"
    if low_conf_sections:
        sections_str = ", ".join(f"[{s}]" for s in low_conf_sections)
        doctor_summary += (
            f"\n\n⚠️ *Low confidence warning:* I am not confident about the "
            f"{sections_str} section(s). Please review the SOAP note carefully."
        )

    send_whatsapp_message_sync(session.doctor_number, doctor_summary)
    print(f"[ConsultationService] Summary sent to doctor {session.doctor_number}")

    booking_session = get_session(patient_number)
    if booking_session:
        booking_session.journey_state = "POST_CONSULT"
        if follow_up_qs:
            booking_session.symptoms = booking_session.symptoms or []
        save_session(booking_session)

    delete_consultation(patient_number)
    print(f"[ConsultationService] ConsultationSession deleted for {patient_number}")

    # Persist medical record to PostgreSQL (non-blocking — failure must not affect WhatsApp flow)
    try:
        from app.services.patient_service import save_consultation_record
        from app.services.clinic_resolver import resolve_clinic_by_twilio_number
        # Resolve clinic from booking session's "to" number
        booking = get_session(patient_number)
        clinic_id = getattr(booking, "clinic_id", None) if booking else None
        if clinic_id:
            import asyncio
            asyncio.create_task(save_consultation_record(
                clinic_id=clinic_id,
                patient_phone=patient_number,
                patient_name=getattr(booking, "patient_name", None) if booking else None,
                doctor_phone=session.doctor_number,
                chief_complaint=getattr(booking, "symptoms", None) if booking else None,
                soap_result=result,
            ))
    except Exception as _exc:
        print(f"[ConsultationService] Non-fatal: failed to save patient record: {_exc}")

    return (
        "Your consultation has been recorded. "
        "The doctor will send any prescriptions or follow-up instructions shortly. 🙏"
    )
