import json
import os
import re
import uuid
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.schemas import BookingSession, AppointmentRecord, BookingState

from app.prompts import BOOKING_ENTITY_PROMPT
from app.services.appointment_approval import (
    latest_patient_approval_status,
    request_doctor_approval,
    request_suggested_slot_approval,
)
from app.services.store import save_appointment
from app.services.scheduler import schedule_reminder

load_dotenv()

# ── LLM for entity extraction ──────────────────────────────────────────────────

def _groq_llm():
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model="llama-3.3-70b-versatile",
        temperature=0.1,
        max_tokens=150,
    )


# ── Reply message templates ────────────────────────────────────────────────────
# All bot messages live here — easy to edit without touching logic.

MSG_GREETING = (
    "👋 Hello! Welcome to ClinicAI Assistant.\n\n"
    "I can help you book an appointment. What date and time works for you?\n"
)

MSG_ASK_DOCTOR = (
    "Got it — *{date}* at *{time}*. 👍\n\n"
    "Which doctor would you prefer?\n"
)

MSG_CONFIRM = (
    "Please confirm your appointment:\n\n"
    "👨‍⚕️ Doctor : *{doctor}*\n"
    "📅 Date   : *{date}*\n"
    "🕐 Time   : *{time}*\n\n"
    "Reply *yes* to confirm or *no* to cancel."
)

MSG_BOOKED = (
    "✅ *Appointment Confirmed!*\n\n"
    "👨‍⚕️ Doctor : *{doctor}*\n"
    "📅 Date   : *{date}*\n"
    "🕐 Time   : *{time}*\n\n"
    "We'll send you a reminder before your appointment. See you then! 🙏"
)

MSG_CANCELLED = (
    "No problem! Your booking has been cancelled. "
    "Feel free to message us again when you'd like to book. 😊"
)

MSG_EMERGENCY = (
    "🚨 *This sounds like an emergency.*\n\n"
    "Please call *112* (India emergency) or go to the nearest hospital immediately.\n"
    "If you need the clinic's emergency line, call us directly."
)

MSG_NEED_DATE = (
    "I didn't catch the date and time. Could you tell me when you'd like to come?\n"
    "_(e.g.'Date: 15th May 2026 and Time: 5 PM')_"
)

MSG_NEED_DOCTOR = (
    "Which doctor would you like to see?\n"
    "_(e.g. 'Dr Mehta', 'Dr Sharma')_"
)

MSG_OFF_TOPIC = (
    "Sure! Let me note that. 📝\n\n"
    "Shall we continue with your appointment booking, or would you like to stop?\n"
    "_(Reply 'continue' to keep booking or 'stop' to cancel)_"
)

MSG_ALREADY_BOOKED = (
    "You already have an active booking in progress. "
    "Reply *continue* to resume or *stop* to start over."
)


# ── Entity extractor ───────────────────────────────────────────────────────────

def _extract_booking_entities(message: str) -> dict:
    try:
        llm = _groq_llm()
        response = llm.invoke([
            SystemMessage(content="Extract booking details. Return ONLY valid JSON."),
            HumanMessage(content=BOOKING_ENTITY_PROMPT + f'"{message}"'),
        ])
        raw = response.content
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"[WARN] Entity extraction failed: {e}")
        return {"patient_name": None, "requested_date": None,
                "requested_time": None, "doctor_name": None}


def _is_affirmative(message: str) -> bool:
    msg = message.lower().strip()
    yes_words = {"yes", "yeah", "yep", "y", "ok", "okay", "haan", "ha",
                 "confirm", "confirmed", "theek hai", "bilkul", "sure", "done"}
    return any(w in msg for w in yes_words)


def _is_negative(message: str) -> bool:
    msg = message.lower().strip()
    no_words = {"no", "nope", "n", "nahi", "nahin", "cancel", "stop",
                "band karo", "mat karo", "nhi"}
    return any(w in msg for w in no_words)


def _wants_to_continue(message: str) -> bool:
    msg = message.lower().strip()
    return any(w in msg for w in {"continue", "haan", "yes", "ok", "jari rakho"})


def _wants_to_stop(message: str) -> bool:
    msg = message.lower().strip()
    return any(w in msg for w in {"stop", "nahi", "cancel", "band", "no"})


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def intent_node(state: BookingState) -> dict:
    from app.graph.classifier import classifier_graph

    message = state["incoming_message"]
    initial = {
        "from_number": state["from_number"],
        "raw_message": message,
        "is_valid": False, "validation_error": None,
        "processed_message": "", "intent": "general_query",
        "confidence": 0.0, "entities": {}, "bot_response": None,
        "llm_error": None, "all_intents": [], "is_multi_intent": False,
        "is_injection": False, "injection_reason": None,
        "is_emergency": False, "pipeline_log": [],
    }
    result = classifier_graph.invoke(initial)

    return {
        "intent": result["intent"],
        "confidence": result["confidence"],
        "extracted_entities": result.get("entities", {}),
        "bot_response": result.get("bot_response"),
        "pipeline_log": [f"intent_node: intent={result['intent']} conf={result['confidence']:.2f}"],
    }


def session_node(state: BookingState) -> dict:
    existing = state.get("session")

    if existing:
        return {
            "is_new_session": False,
            "current_booking_state": existing.get("state", "GREETING"),
            "pipeline_log": [f"session_node: loaded existing session state={existing.get('state')}"],
        }
    else:
        new_session = BookingSession(from_number=state["from_number"])
        return {
            "session": new_session.model_dump(),
            "is_new_session": True,
            "current_booking_state": "GREETING",
            "pipeline_log": ["session_node: created new session"],
        }


def emergency_node(state: BookingState) -> dict:
    """
    NODE 3a — Emergency handler.
    Patient sent an emergency message. Reply immediately with emergency info.
    Delete any in-progress booking session.
    """
    return {
        "reply_message": MSG_EMERGENCY,
        "is_off_topic": False,
        "session": None,
        "current_booking_state": "GREETING",
        "pipeline_log": ["emergency_node: ⚠ emergency response sent, session cleared"],
    }


def off_topic_node(state: BookingState) -> dict:
    """
    NODE 3b — Off-topic handler.
    Patient sent something unrelated mid-booking-flow.
    Bot acknowledges gracefully and asks if they want to continue.
    """
    session_dict = state.get("session", {})
    booking_state = session_dict.get("state", "GREETING")
    message = state["incoming_message"].lower()

    bot_response = state.get("bot_response") or MSG_GREETING

    # If they have NO active session, answer their question (or fallback to greeting)
    if booking_state == "GREETING" or not session_dict:
        return {
            "reply_message": bot_response,
            "is_off_topic": False,
            "pipeline_log": ["off_topic_node: answered general query, no session"],
        }

    # If they want to stop mid-flow
    if _wants_to_stop(message):
        return {
            "reply_message": MSG_CANCELLED,
            "is_off_topic": False,
            "session": None,
            "current_booking_state": "GREETING",
            "pipeline_log": ["off_topic_node: patient stopped, session cleared"],
        }

    # If they want to continue
    if _wants_to_continue(message):
        return {
            "reply_message": _get_resume_message(session_dict),
            "is_off_topic": False,
            "pipeline_log": ["off_topic_node: patient wants to continue"],
        }

    # Truly off-topic — ask if they want to continue
    return {
        "reply_message": MSG_OFF_TOPIC,
        "is_off_topic": True,
        "pipeline_log": ["off_topic_node: off-topic detected, asked patient to continue/stop"],
    }


def _get_resume_message(session_dict: dict) -> str:
    """Returns the right prompt to resume based on current booking state."""
    state = session_dict.get("state", "GREETING")
    if state == "COLLECT_DATE_TIME":
        return MSG_NEED_DATE
    elif state == "COLLECT_DOCTOR_PREFERENCE":
        date = session_dict.get("requested_date", "")
        time = session_dict.get("requested_time", "")
        return MSG_ASK_DOCTOR.format(date=date, time=time)
    elif state == "CONFIRM_SLOT":
        return MSG_CONFIRM.format(
            doctor=session_dict.get("doctor_name", ""),
            date=session_dict.get("requested_date", ""),
            time=session_dict.get("requested_time", ""),
        )
    return MSG_GREETING


def flow_node(state: BookingState) -> dict:
    """
    NODE 3c — Main booking flow state machine.
    Advances the patient through all 5 booking states.

    GREETING                → send greeting, move to COLLECT_DATE_TIME
    COLLECT_DATE_TIME       → extract date/time, move to COLLECT_DOCTOR_PREFERENCE
    COLLECT_DOCTOR_PREFERENCE → extract doctor, move to CONFIRM_SLOT
    CONFIRM_SLOT            → wait for yes/no, handled by confirm_node
    BOOKED                  → already booked, inform patient
    """
    from_number = state["from_number"]
    session_dict = state.get("session", {})
    booking_state = session_dict.get("state", "GREETING")
    entities = state.get("extracted_entities", {})
    bot_response = state.get("bot_response")

    # If they are already booked
    if booking_state == "BOOKED":
        return {
            "current_booking_state": "BOOKED",
            "reply_message": "You already have a confirmed appointment! We'll send you a reminder. 😊",
            "pipeline_log": ["flow_node: already BOOKED"],
        }

    if booking_state == "WAITING_DOCTOR_APPROVAL":
        status = latest_patient_approval_status(from_number)
        if status == "approved":
            session = BookingSession(**session_dict)
            session.state = "BOOKED"
            return {
                "session": session.model_dump(),
                "current_booking_state": "BOOKED",
                "reply_message": "Your appointment has been approved by the doctor and is now confirmed.",
                "pipeline_log": ["flow_node: doctor approval already completed"],
            }
        if status == "rejected":
            return {
                "session": None,
                "current_booking_state": "GREETING",
                "reply_message": "The doctor could not approve that slot. Please send another date and time.",
                "pipeline_log": ["flow_node: doctor rejected pending appointment"],
            }
        return {
            "current_booking_state": "WAITING_DOCTOR_APPROVAL",
            "reply_message": (
                "Your appointment request is still waiting for doctor approval. "
                "I will message you as soon as the doctor replies."
            ),
            "pipeline_log": ["flow_node: waiting for doctor approval"],
        }

    # If we're stuck in confirm slot (e.g. they didn't say yes/no)
    if booking_state == "CONFIRM_SLOT":
        session = BookingSession(**session_dict)
        return {
            "current_booking_state": "CONFIRM_SLOT",
            "reply_message": MSG_CONFIRM.format(
                doctor=session.doctor_name or "doctor",
                date=session.requested_date or "?",
                time=session.requested_time or "?",
            ),
            "pipeline_log": ["flow_node: CONFIRM_SLOT — re-prompted confirmation"],
        }

    # Initialize or load session
    if session_dict:
        session = BookingSession(**session_dict)
    else:
        session = BookingSession(from_number=from_number)

    # Accumulate entities
    if entities.get("patient_name"): session.patient_name = entities["patient_name"]
    if entities.get("requested_date"): session.requested_date = entities["requested_date"]
    if entities.get("requested_time"): session.requested_time = entities["requested_time"]
    if entities.get("doctor_name"): session.doctor_name = entities["doctor_name"]
    if entities.get("symptoms_mentioned"): session.symptoms = entities["symptoms_mentioned"]

    # If the user says "any doctor", the entities might have "doctor_name": null, 
    # but the intent node should catch it. Let's default if missing and they are otherwise done.
    missing = []
    if not session.patient_name: missing.append("patient_name")
    if not session.requested_date: missing.append("requested_date")
    if not session.requested_time: missing.append("requested_time")
    if not session.doctor_name: missing.append("doctor_name")

    # If only doctor is missing, but they previously gave date/time, we might just assign a doctor
    # But now the LLM asks for doctor dynamically via bot_response!

    if missing:
        session.state = "COLLECTING_INFO"
        return {
            "session": session.model_dump(),
            "current_booking_state": "COLLECTING_INFO",
            "reply_message": bot_response or MSG_GREETING,
            "pipeline_log": [f"flow_node: COLLECTING_INFO — missing {missing}"],
        }
    else:
        session.state = "CONFIRM_SLOT"
        # Use LLM's dynamic confirmation if available, else fallback
        reply = bot_response or MSG_CONFIRM.format(
            doctor=session.doctor_name,
            date=session.requested_date,
            time=session.requested_time,
        )
        return {
            "session": session.model_dump(),
            "current_booking_state": "CONFIRM_SLOT",
            "reply_message": reply,
            "pipeline_log": ["flow_node: all entities present, moving to CONFIRM_SLOT"],
        }


def confirm_node(state: BookingState) -> dict:
    """
    NODE 4 — Confirmation handler.
    Only runs when booking_state == CONFIRM_SLOT.
    Handles yes (create appointment + schedule reminder) or no (cancel).
    """
    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session", {})
    session = BookingSession(**session_dict)

    if message.strip() in {"1", "2", "3"}:
        reply, approval_id = request_suggested_slot_approval(session, from_number, message)
        session.state = "WAITING_DOCTOR_APPROVAL" if approval_id else "CONFIRM_SLOT"
        return {
            "session": session.model_dump(),
            "current_booking_state": session.state,
            "appointment_id": approval_id,
            "reply_message": reply,
            "pipeline_log": [f"confirm_node: selected suggested slot id={approval_id}"],
        }

    if _is_affirmative(message):
        reply, approval_id = request_doctor_approval(session, from_number)
        session.state = "WAITING_DOCTOR_APPROVAL" if approval_id else "CONFIRM_SLOT"
        return {
            "session": session.model_dump(),
            "current_booking_state": session.state,
            "appointment_id": approval_id,
            "reply_message": reply,
            "pipeline_log": [f"confirm_node: sent doctor approval request id={approval_id}"],
        }

    if _is_affirmative(message):
        # ── Confirm the appointment ────────────────────────────────────────────
        appt_id = str(uuid.uuid4())[:8].upper()
        appt = AppointmentRecord(
            appointment_id=appt_id,
            from_number=from_number,
            patient_name=session.patient_name,
            doctor_name=session.doctor_name or "Dr Sharma",
            date_str=session.requested_date or "TBD",
            time_str=session.requested_time or "TBD",
            symptoms=session.symptoms,
        )
        save_appointment(appt)

        # ── Update session to BOOKED ───────────────────────────────────────────
        session.state = "BOOKED"

        # ── Schedule reminder ──────────────────────────────────────────────────
        fire_at = schedule_reminder(
            to=from_number,
            appointment_id=appt_id,
            doctor=appt.doctor_name,
            date_str=appt.date_str,
            time_str=appt.time_str,
        )

        reply = MSG_BOOKED.format(
            doctor=appt.doctor_name,
            date=appt.date_str,
            time=appt.time_str,
        )

        return {
            "session": session.model_dump(),
            "current_booking_state": "BOOKED",
            "appointment_id": appt_id,
            "reply_message": reply,
            "pipeline_log": [
                f"confirm_node: BOOKED appt_id={appt_id}",
                f"confirm_node: reminder scheduled at {fire_at.strftime('%H:%M:%S')}",
            ],
        }

    elif _is_negative(message):
        # ── Cancel ────────────────────────────────────────────────────────────
        return {
            "current_booking_state": "GREETING",
            "session": None,
            "appointment_id": None,
            "reply_message": MSG_CANCELLED,
            "pipeline_log": ["confirm_node: patient said no, session cleared"],
        }

    else:
        # ── Unclear response — re-ask ──────────────────────────────────────────
        return {
            "current_booking_state": "CONFIRM_SLOT",
            "reply_message": (
                f"Sorry, I didn't catch that. Please reply *yes* to confirm or *no* to cancel.\n\n"
                f"👨‍⚕️ *{session.doctor_name}* | 📅 {session.requested_date} | 🕐 {session.requested_time}"
            ),
            "pipeline_log": ["confirm_node: unclear response, re-asked"],
        }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def route_after_session(
    state: BookingState,
) -> Literal["emergency_node", "flow_node", "off_topic_node", "confirm_node"]:
    """
    The central routing decision of the booking graph.
    Decides which node handles this message based on:
    1. Is it an emergency? → emergency_node
    2. Is it a CONFIRM_SLOT state + patient replying to confirmation? → confirm_node
    3. Is it appointment_book intent? → flow_node
    4. Anything else mid-flow? → off_topic_node
    """
    intent = state.get("intent", "general_query")
    booking_state = state.get("current_booking_state", "GREETING")

    # Always handle emergencies immediately
    if intent == "emergency":
        return "emergency_node"

    # If we're waiting for confirmation, send to confirm_node
    if booking_state == "CONFIRM_SLOT":
        return "confirm_node"

    # If patient wants to book OR is mid-flow, go to flow_node
    if intent == "appointment_book" or booking_state not in ("GREETING", "BOOKED"):
        return "flow_node"

    # Everything else (general query, off-topic during flow)
    return "off_topic_node"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_booking_graph():
    g = StateGraph(BookingState)

    g.add_node("intent_node", intent_node)
    g.add_node("session_node", session_node)
    g.add_node("emergency_node", emergency_node)
    g.add_node("off_topic_node", off_topic_node)
    g.add_node("flow_node", flow_node)
    g.add_node("confirm_node", confirm_node)

    g.add_edge(START, "intent_node")
    g.add_edge("intent_node", "session_node")
    g.add_conditional_edges(
        "session_node",
        route_after_session,
        {
            "emergency_node": "emergency_node",
            "flow_node": "flow_node",
            "off_topic_node": "off_topic_node",
            "confirm_node": "confirm_node",
        },
    )

    g.add_edge("emergency_node", END)
    g.add_edge("off_topic_node", END)
    g.add_edge("flow_node", END)
    g.add_edge("confirm_node", END)


    memory = MemorySaver()
    return g.compile(checkpointer=memory)


booking_graph = build_booking_graph()
