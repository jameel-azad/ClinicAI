import json
import os
import re
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.schemas import BookingSession, BookingState

from app.prompts import BOOKING_ENTITY_PROMPT
from app.services.appointment_approval import (
    latest_patient_approval_status,
    request_doctor_approval,
    request_suggested_slot_approval,
)
from app.services.store import (
    cancel_appointment,
    get_latest_appointment_for_patient,
    get_latest_approval_for_patient,
    update_pending_approval,
)

load_dotenv()

_CLINIC_NAME = os.getenv("CLINIC_NAME", "ClinicAI")

# ── LLM for entity extraction ──────────────────────────────────────────────────

def _groq_llm():
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0.1,
        max_tokens=150,
    )


# ── Reply message templates ────────────────────────────────────────────────────
# All bot messages live here — easy to edit without touching logic.

MSG_GREETING = (
    f"Namaste! Welcome to {_CLINIC_NAME} 🙏\n\n"
    "I'm your virtual receptionist. Here's how I can help you:\n\n"
    "📅 *Book a doctor's appointment*\n"
    "📋 *Share your lab report* for the doctor to review\n\n"
    "How may I assist you today?\n"
    "_(You can reply in Hindi or English)_"
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

MSG_CANCEL_CONFIRM = (
    "Are you sure you want to cancel your appointment?\n\n"
    "👨‍⚕️ Doctor : *{doctor}*\n"
    "📅 Date   : *{date}*\n"
    "🕐 Time   : *{time}*\n\n"
    "Reply *yes* to cancel or *no* to keep it."
)

MSG_CANCEL_CONFIRMED = (
    "✅ Your appointment with *{doctor}* on *{date}* at *{time}* has been cancelled.\n\n"
    "Feel free to book a new appointment anytime. 😊"
)

MSG_NO_APPOINTMENT = (
    "You don't have any active appointment to cancel. "
    "Would you like to book one? 😊"
)

MSG_PENDING_CANCELLED = (
    "Your appointment request is still waiting for doctor approval — "
    "it has been cancelled. Feel free to book again anytime. 😊"
)

MSG_RESCHEDULE_START = (
    "Sure! Your current appointment:\n\n"
    "👨‍⚕️ Doctor : *{doctor}*\n"
    "📅 Date   : *{date}*\n"
    "🕐 Time   : *{time}*\n\n"
    "What new date and time would you like?\n"
    "_(e.g. '26th May at 4 PM')_"
)

MSG_RESCHEDULE_CONFIRM = (
    "Got it! Reschedule to:\n\n"
    "📅 Date : *{new_date}*\n"
    "🕐 Time : *{new_time}*\n\n"
    "Reply *yes* to confirm or *no* to keep your current appointment."
)

MSG_RESCHEDULE_NEED_DATE = (
    "Got the time! What date would you like?\n"
    "_(e.g. '26th May')_"
)

MSG_RESCHEDULE_NEED_TIME = (
    "Got the date! What time would you prefer?\n"
    "_(e.g. '4:00 PM')_"
)

MSG_RESCHEDULE_NEED_BOTH = (
    "What new date and time would you like?\n"
    "_(e.g. '26th May at 4 PM')_"
)

MSG_NO_RESCHEDULE = (
    "You don't have any active appointment to reschedule. "
    "Would you like to book one? 😊"
)


# ── Entity extractor ───────────────────────────────────────────────────────────

def _extract_booking_entities(message: str, context: str = "") -> dict:
    try:
        llm = _groq_llm()
        prompt = BOOKING_ENTITY_PROMPT
        if context:
            prompt = f"REFERENCE APPOINTMENT CONTEXT: {context}\n\n" + prompt
        response = llm.invoke([
            SystemMessage(content="Extract booking details. Return ONLY valid JSON."),
            HumanMessage(content=prompt + f'"{message}"'),
        ])
        raw = response.content
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"[WARN] Entity extraction failed: {e}")
        return {"patient_name": None, "requested_date": None,
                "requested_time": None, "doctor_name": None}


def _word_match(message: str, words: set, phrases: set | None = None) -> bool:
    """Match whole words only (avoids 'ha' matching inside 'khansi').
    Optionally also checks multi-word phrases with substring match.
    """
    msg_words = set(re.findall(r"\b\w+\b", message.lower()))
    if msg_words & words:
        return True
    if phrases:
        msg_lower = message.lower()
        return any(p in msg_lower for p in phrases)
    return False


def _is_affirmative(message: str) -> bool:
    return _word_match(
        message,
        words={"yes", "yeah", "yep", "y", "ok", "okay", "haan", "ha",
               "confirm", "confirmed", "bilkul", "sure", "done"},
        phrases={"theek hai"},
    )


def _is_negative(message: str) -> bool:
    return _word_match(
        message,
        words={"no", "nope", "nahi", "nahin", "cancel", "stop", "nhi"},
        phrases={"band karo", "mat karo"},
    )


def _wants_to_continue(message: str) -> bool:
    return _word_match(
        message,
        words={"continue", "haan", "yes", "ok"},
        phrases={"jari rakho"},
    )


def _wants_to_stop(message: str) -> bool:
    return _word_match(
        message,
        words={"stop", "nahi", "cancel", "band", "no"},
    )


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
        # When entering the flow without explicit appointment_book intent (e.g., user said "Yes"
        # responding to the bot's "Would you like to book?" question), use MSG_GREETING so
        # we don't echo back the classifier's generic low-confidence response.
        if booking_state == "GREETING" and state.get("intent") != "appointment_book":
            reply = MSG_GREETING
        else:
            reply = bot_response or MSG_GREETING
        return {
            "session": session.model_dump(),
            "current_booking_state": "COLLECTING_INFO",
            "reply_message": reply,
            "pipeline_log": [f"flow_node: COLLECTING_INFO — missing {missing}"],
        }
    else:
        session.state = "CONFIRM_SLOT"
        # Always use the structured confirmation format — the classifier's bot_response
        # may be a generic greeting (e.g., when intent was general_query), not a proper confirmation.
        reply = MSG_CONFIRM.format(
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

    if _is_negative(message):
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


def reschedule_node(state: BookingState) -> dict:
    """
    NODE 3e — Reschedule handler.
    Three steps:
    1. Show current appointment, ask for new date/time  → RESCHEDULE_COLLECTING
    2. Collect new date/time (one or both per message)  → RESCHEDULE_CONFIRM
    3. Confirm yes/no → cancel old + re-run approval, or keep original
    """
    from app.services.scheduler import cancel_reminder

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    booking_state = session_dict.get("state", "GREETING")

    # ── Step 2: collecting new date/time ──────────────────────────────────────
    if booking_state == "RESCHEDULE_COLLECTING":
        session = BookingSession(**session_dict)
        appt_context = (
            f"Current appointment is on {session.requested_date} at {session.requested_time}. "
            f"'same day'/'usi din'/'same date' means {session.requested_date}. "
            f"'same time'/'usi time' means {session.requested_time}."
        )
        entities = _extract_booking_entities(message, context=appt_context)
        new_date = entities.get("requested_date") or session.new_requested_date
        new_time = entities.get("requested_time") or session.new_requested_time
        session.new_requested_date = new_date
        session.new_requested_time = new_time

        if not new_date and not new_time:
            return {
                "session": session.model_dump(),
                "current_booking_state": "RESCHEDULE_COLLECTING",
                "reply_message": MSG_RESCHEDULE_NEED_BOTH,
                "pipeline_log": ["reschedule_node: no date/time extracted, re-asked"],
            }
        if not new_date:
            return {
                "session": session.model_dump(),
                "current_booking_state": "RESCHEDULE_COLLECTING",
                "reply_message": MSG_RESCHEDULE_NEED_DATE,
                "pipeline_log": ["reschedule_node: got time, need date"],
            }
        if not new_time:
            return {
                "session": session.model_dump(),
                "current_booking_state": "RESCHEDULE_COLLECTING",
                "reply_message": MSG_RESCHEDULE_NEED_TIME,
                "pipeline_log": ["reschedule_node: got date, need time"],
            }

        session.state = "RESCHEDULE_CONFIRM"
        return {
            "session": session.model_dump(),
            "current_booking_state": "RESCHEDULE_CONFIRM",
            "reply_message": MSG_RESCHEDULE_CONFIRM.format(
                new_date=new_date,
                new_time=new_time,
            ),
            "pipeline_log": ["reschedule_node: got both, asking confirmation"],
        }

    # ── Step 3: patient confirming or declining ────────────────────────────────
    if booking_state == "RESCHEDULE_CONFIRM":
        session = BookingSession(**session_dict)

        if _is_affirmative(message):
            appt = get_latest_appointment_for_patient(from_number)
            if appt:
                cancel_appointment(appt.appointment_id)
                cancel_reminder(appt.appointment_id)

            session.requested_date = session.new_requested_date
            session.requested_time = session.new_requested_time
            session.new_requested_date = None
            session.new_requested_time = None

            reply, approval_id = request_doctor_approval(session, from_number)
            session.state = "WAITING_DOCTOR_APPROVAL" if approval_id else "CONFIRM_SLOT"
            return {
                "session": session.model_dump(),
                "current_booking_state": session.state,
                "appointment_id": approval_id,
                "reply_message": reply,
                "pipeline_log": [f"reschedule_node: old cancelled, new approval sent id={approval_id}"],
            }

        if _is_negative(message):
            session.state = "BOOKED"
            session.new_requested_date = None
            session.new_requested_time = None
            return {
                "session": session.model_dump(),
                "current_booking_state": "BOOKED",
                "reply_message": "No problem! Your original appointment is kept. 😊",
                "pipeline_log": ["reschedule_node: patient declined reschedule"],
            }

        return {
            "current_booking_state": "RESCHEDULE_CONFIRM",
            "reply_message": (
                f"Please reply *yes* to reschedule to *{session.new_requested_date}* at "
                f"*{session.new_requested_time}*, or *no* to keep your current appointment."
            ),
            "pipeline_log": ["reschedule_node: unclear response, re-asked"],
        }

    # ── Step 1: patient just asked to reschedule ───────────────────────────────

    # Handle stale WAITING_DOCTOR_APPROVAL — check if approval is already done
    if booking_state == "WAITING_DOCTOR_APPROVAL":
        appt = get_latest_appointment_for_patient(from_number)
        if not appt:
            return {
                "reply_message": MSG_NO_RESCHEDULE,
                "pipeline_log": ["reschedule_node: no confirmed appointment in WAITING state"],
            }
        session = BookingSession(**session_dict)
        session.state = "RESCHEDULE_COLLECTING"
        return {
            "session": session.model_dump(),
            "current_booking_state": "RESCHEDULE_COLLECTING",
            "reply_message": MSG_RESCHEDULE_START.format(
                doctor=appt.doctor_name,
                date=appt.date_str,
                time=appt.time_str,
            ),
            "pipeline_log": ["reschedule_node: started from WAITING state"],
        }

    appt = get_latest_appointment_for_patient(from_number)
    if not appt:
        return {
            "reply_message": MSG_NO_RESCHEDULE,
            "pipeline_log": ["reschedule_node: no appointment to reschedule"],
        }

    session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
    session.state = "RESCHEDULE_COLLECTING"
    return {
        "session": session.model_dump(),
        "current_booking_state": "RESCHEDULE_COLLECTING",
        "reply_message": MSG_RESCHEDULE_START.format(
            doctor=appt.doctor_name,
            date=appt.date_str,
            time=appt.time_str,
        ),
        "pipeline_log": ["reschedule_node: asked for new date/time"],
    }


def cancel_node(state: BookingState) -> dict:
    """
    NODE 3d — Cancellation handler.
    Handles cancellation of confirmed appointments and pending approvals.
    Two-step: first ask for confirmation, then execute on yes.
    """
    from app.services.identity import find_doctor_number
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.scheduler import cancel_reminder

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    booking_state = session_dict.get("state", "GREETING")

    # ── Step 2: patient is confirming/declining the cancellation ──────────────
    if booking_state == "CANCEL_CONFIRM":
        if _is_affirmative(message):
            appt = get_latest_appointment_for_patient(from_number)
            if appt:
                cancel_appointment(appt.appointment_id)
                cancel_reminder(appt.appointment_id)
                doctor_number = find_doctor_number(appt.doctor_name)
                if doctor_number:
                    send_whatsapp_message_sync(
                        doctor_number,
                        f"Patient {appt.patient_name or from_number} has cancelled their "
                        f"appointment on {appt.date_str} at {appt.time_str}.",
                    )
                return {
                    "session": None,
                    "current_booking_state": "GREETING",
                    "reply_message": MSG_CANCEL_CONFIRMED.format(
                        doctor=appt.doctor_name,
                        date=appt.date_str,
                        time=appt.time_str,
                    ),
                    "pipeline_log": [f"cancel_node: appointment {appt.appointment_id} cancelled"],
                }
            # Appointment disappeared between steps — clear and move on
            return {
                "session": None,
                "current_booking_state": "GREETING",
                "reply_message": "Your appointment has been cancelled. 😊",
                "pipeline_log": ["cancel_node: appointment not found on confirm step"],
            }

        if _is_negative(message):
            session = BookingSession(**session_dict)
            session.state = "BOOKED"
            return {
                "session": session.model_dump(),
                "current_booking_state": "BOOKED",
                "reply_message": "No problem! Your appointment is kept. 😊",
                "pipeline_log": ["cancel_node: patient chose not to cancel"],
            }

        return {
            "current_booking_state": "CANCEL_CONFIRM",
            "reply_message": "Please reply *yes* to cancel or *no* to keep your appointment.",
            "pipeline_log": ["cancel_node: unclear response, re-asked"],
        }

    # ── Step 1: patient just requested cancellation ────────────────────────────

    # Mid-booking (not yet confirmed) — just drop the in-progress session
    if booking_state in ("COLLECTING_INFO", "CONFIRM_SLOT"):
        return {
            "session": None,
            "current_booking_state": "GREETING",
            "reply_message": MSG_CANCELLED,
            "pipeline_log": ["cancel_node: cancelled in-progress booking"],
        }

    # Waiting for doctor approval — but first check if doctor already approved
    if booking_state == "WAITING_DOCTOR_APPROVAL":
        appt = get_latest_appointment_for_patient(from_number)
        if appt:
            # Doctor already approved — session state just wasn't updated yet
            session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
            session.state = "CANCEL_CONFIRM"
            return {
                "session": session.model_dump(),
                "current_booking_state": "CANCEL_CONFIRM",
                "reply_message": MSG_CANCEL_CONFIRM.format(
                    doctor=appt.doctor_name,
                    date=appt.date_str,
                    time=appt.time_str,
                ),
                "pipeline_log": ["cancel_node: approval already done, asked for cancel confirmation"],
            }
        # Still genuinely waiting — cancel the pending request
        approval = get_latest_approval_for_patient(from_number)
        if approval and approval.get("status") == "waiting_doctor":
            update_pending_approval(approval["approval_id"], status="rejected")
            doctor_number = find_doctor_number(approval.get("doctor_name"))
            if doctor_number:
                send_whatsapp_message_sync(
                    doctor_number,
                    f"Patient {approval.get('patient_name') or from_number} has cancelled "
                    f"their appointment request {approval['approval_id']}.",
                )
        return {
            "session": None,
            "current_booking_state": "GREETING",
            "reply_message": MSG_PENDING_CANCELLED,
            "pipeline_log": ["cancel_node: pending approval cancelled"],
        }

    # Confirmed appointment — ask for confirmation first
    appt = get_latest_appointment_for_patient(from_number)
    if not appt:
        return {
            "reply_message": MSG_NO_APPOINTMENT,
            "pipeline_log": ["cancel_node: no appointment found"],
        }

    session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
    session.state = "CANCEL_CONFIRM"
    return {
        "session": session.model_dump(),
        "current_booking_state": "CANCEL_CONFIRM",
        "reply_message": MSG_CANCEL_CONFIRM.format(
            doctor=appt.doctor_name,
            date=appt.date_str,
            time=appt.time_str,
        ),
        "pipeline_log": ["cancel_node: asked for cancel confirmation"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def route_after_session(
    state: BookingState,
) -> Literal["emergency_node", "flow_node", "off_topic_node", "confirm_node", "cancel_node", "reschedule_node"]:
    intent = state.get("intent", "general_query")
    booking_state = state.get("current_booking_state", "GREETING")

    if intent == "emergency":
        return "emergency_node"

    # Mid-reschedule states always continue in reschedule_node
    if booking_state in ("RESCHEDULE_COLLECTING", "RESCHEDULE_CONFIRM"):
        return "reschedule_node"

    # Mid-cancellation always continues in cancel_node
    if booking_state == "CANCEL_CONFIRM":
        return "cancel_node"

    if intent == "appointment_reschedule":
        return "reschedule_node"

    if intent == "appointment_cancel":
        return "cancel_node"

    if booking_state == "CONFIRM_SLOT":
        return "confirm_node"

    if booking_state not in ("GREETING", "BOOKED"):
        return "flow_node"

    if intent == "appointment_book":
        return "flow_node"

    if booking_state == "GREETING":
        return "flow_node"

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
    g.add_node("cancel_node", cancel_node)
    g.add_node("reschedule_node", reschedule_node)

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
            "cancel_node": "cancel_node",
            "reschedule_node": "reschedule_node",
        },
    )

    g.add_edge("emergency_node", END)
    g.add_edge("off_topic_node", END)
    g.add_edge("flow_node", END)
    g.add_edge("confirm_node", END)
    g.add_edge("cancel_node", END)
    g.add_edge("reschedule_node", END)


    memory = MemorySaver()
    return g.compile(checkpointer=memory)


booking_graph = build_booking_graph()
