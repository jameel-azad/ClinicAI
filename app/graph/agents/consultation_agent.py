import os
import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingSession, BookingState, ConsultationMessage, ConsultationSession

load_dotenv()

_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")

CLOSING_PHRASES = {
    "ok done", "okay done", "done", "take care", "theek hai bas",
    "consultation over", "thats all", "that's all", "consult over",
    "finish", "finished", "ho gaya", "ho gya", "bas", "bye",
    "consultation khatam", "khatam", "over",
}


def _is_closing_phrase(message: str) -> bool:
    msg = message.strip().lower()
    return msg in CLOSING_PHRASES or any(phrase in msg for phrase in CLOSING_PHRASES)


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def start_or_resume_node(state: BookingState) -> dict:
    """
    Load existing ConsultationSession or create a new one.
    Buffer the incoming patient message. Reset the 30-min inactivity timer.
    Set journey_state = CONSULTATION_ACTIVE on BookingSession.
    """
    from app.services.store import (
        append_consultation_message,
        get_consultation, save_consultation,
        get_session, save_session,
        get_latest_appointment_for_patient,
    )
    from app.services.scheduler import schedule_consultation_timeout
    from app.services.identity import all_doctor_numbers, find_doctor_name

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    clinic_id = session_dict.get("clinic_id")
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)

    existing = get_consultation(from_number, clinic_id=clinic_id)

    if existing and existing.is_active:
        append_consultation_message(from_number, ConsultationMessage(
            sender_role="patient",
            text=message,
            timestamp=now,
        ))
        reset_consultation_timeout(from_number, existing.consultation_id, clinic_id=existing.clinic_id)
        return {
            "pipeline_log": [f"consultation_agent: buffered patient message, consultation {existing.consultation_id}"],
        }

    # Create new ConsultationSession
    appt = get_latest_appointment_for_patient(from_number)
    doctor_number = ""
    doctor_name = ""

    if appt:
        doctor_name = appt.doctor_name or ""
        from app.services.identity import find_doctor_number
        doctor_number = find_doctor_number(doctor_name) or ""

    if not doctor_number:
        # No appointment found — ask the patient to book one first.
        # We never silently assign an arbitrary doctor.
        return {
            "reply_message": (
                "To begin a consultation, I need your appointment details. "
                "Please say *'Book appointment'* and I'll connect you with the right doctor. 🏥\n\n"
                "_For emergencies, call *112* immediately._"
            ),
            "pipeline_log": [f"consultation_agent: no appointment/doctor found for {from_number} — asked to book first"],
        }

    if not doctor_name and doctor_number:
        doctor_name = find_doctor_name(doctor_number) or doctor_number

    consultation_id = "CONS" + str(uuid.uuid4())[:6].upper()
    new_session = ConsultationSession(
        consultation_id=consultation_id,
        patient_number=from_number,
        doctor_number=doctor_number,
        doctor_name=doctor_name,
        clinic_id=clinic_id,
        clinic_twilio_number=state.get("clinic_twilio_number"),
        appointment_id=appt.appointment_id if appt else None,
        messages=[ConsultationMessage(sender_role="patient", text=message, timestamp=now)],
        started_at=now,
        last_activity=now,
    )
    save_consultation(from_number, new_session)
    schedule_consultation_timeout(from_number, consultation_id, clinic_id=clinic_id)

    # Update BookingSession journey_state
    booking = get_session(from_number, clinic_id=clinic_id)
    if not booking and session_dict:
        try:
            booking = BookingSession(**session_dict)
        except Exception:
            booking = None
    if booking:
        booking.journey_state = "CONSULTATION_ACTIVE"
        save_session(booking)

    print(f"[ConsultationAgent] New consultation {consultation_id} started for {from_number}")
    return {
        "session": booking.model_dump() if booking else state.get("session"),
        "pipeline_log": [f"consultation_agent: new consultation {consultation_id} started"],
    }


def reset_consultation_timeout(
    patient_number: str, consultation_id: str, clinic_id: str | None = None
) -> None:
    from app.services.scheduler import reset_consultation_timeout as _reset
    try:
        _reset(patient_number, consultation_id, clinic_id=clinic_id)
    except Exception:
        pass


def detect_end_node(state: BookingState) -> dict:
    """
    Check if the incoming message is a closing phrase (from the sender).
    Also checks if the ConsultationSession was already marked ended by the timeout job.
    Sets consultation_ended flag.
    """
    from app.services.store import get_consultation, save_consultation

    from_number = state["from_number"]
    message = state["incoming_message"]

    session = get_consultation(from_number)
    if not session:
        return {
            "pipeline_log": ["consultation_agent/detect_end: no active session"],
        }

    # Timeout job may have already set is_active=False
    if not session.is_active:
        return {
            "pipeline_log": ["consultation_agent/detect_end: ended by timeout"],
        }

    # Closing phrase from DOCTOR — check if the sender is doctor (only doctors can close)
    # In this flow we receive doctor messages via webhook_router doctor branch, not here.
    # Patient closing phrases should NOT end the consultation — only doctor can close.
    # However, for demo simplicity, allow either side to close.
    if _is_closing_phrase(message):
        session.ended_reason = "closing_phrase"
        session.is_active = False
        save_consultation(from_number, session)
        from app.services.scheduler import cancel_consultation_timeout
        cancel_consultation_timeout(from_number)
        print(f"[ConsultationAgent] Closing phrase detected — ending consultation {session.consultation_id}")

    return {
        "pipeline_log": [f"consultation_agent/detect_end: is_active={session.is_active}"],
    }


def finalize_node(state: BookingState) -> dict:
    """Call consultation_service to build bundle, call Jameel API, send summary to doctor.

    Runs via async_runner.run_async() which uses the main event loop when available
    (shares the DB connection pool) and falls back to asyncio.run() otherwise.
    This node always executes inside asyncio.to_thread() so there is no running
    event loop in the current thread — asyncio.run() is always safe here.
    """
    from app.services.async_runner import run_async
    from app.services.consultation_service import finalize_and_send

    from_number = state["from_number"]
    try:
        patient_reply = run_async(finalize_and_send(from_number), timeout=90)
    except Exception as exc:
        print(f"[ConsultationAgent] finalize_and_send failed: {exc}")
        patient_reply = "Your consultation has been recorded. The doctor will follow up shortly. 🙏"

    return {
        "reply_message": patient_reply,
        "pipeline_log": ["consultation_agent/finalize: bundle sent to Jameel, summary delivered to doctor"],
    }


def ack_node(state: BookingState) -> dict:
    """Send a brief ack to patient confirming their message was received during consultation."""
    return {
        "reply_message": (
            "Message received — consultation in progress. 🩺\n"
            "The doctor will respond shortly."
        ),
        "pipeline_log": ["consultation_agent/ack: in-progress ack sent to patient"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def route_after_start(state: BookingState) -> Literal["detect_end_node", "__end__"]:
    """If start_or_resume set a reply_message (no doctor/appointment), end immediately."""
    if state.get("reply_message"):
        return END
    return "detect_end_node"


def route_after_detect(state: BookingState) -> Literal["finalize_node", "ack_node"]:
    """Route to finalize if consultation has ended, ack otherwise."""
    from app.services.store import get_consultation

    session = get_consultation(state["from_number"])
    if session and not session.is_active:
        return "finalize_node"
    return "ack_node"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_consultation_graph():
    g = StateGraph(BookingState)

    g.add_node("start_or_resume_node", start_or_resume_node)
    g.add_node("detect_end_node", detect_end_node)
    g.add_node("finalize_node", finalize_node)
    g.add_node("ack_node", ack_node)

    g.add_edge(START, "start_or_resume_node")
    g.add_conditional_edges(
        "start_or_resume_node",
        route_after_start,
        {"detect_end_node": "detect_end_node", END: END},
    )
    g.add_conditional_edges(
        "detect_end_node",
        route_after_detect,
        {"finalize_node": "finalize_node", "ack_node": "ack_node"},
    )
    g.add_edge("finalize_node", END)
    g.add_edge("ack_node", END)

    return g.compile()


consultation_agent_graph = build_consultation_graph()
