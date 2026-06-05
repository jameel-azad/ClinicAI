"""
BookingAgent — handles all appointment-related intents:
  appointment_book, appointment_cancel, appointment_reschedule,
  appointment_status, general_query (off-topic mid-flow)

Receives already-classified intent + loaded session from RouterAgent.
No internal intent classification or session loading needed.
"""

import json
import os
import re
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

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


# ── LLM ───────────────────────────────────────────────────────────────────────

def _groq_llm():
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0.1,
        max_tokens=150,
    )


# ── Reply templates ────────────────────────────────────────────────────────────

MSG_GREETING = (
    f"Namaste! Welcome to {_CLINIC_NAME} 🙏\n\n"
    "I'm your virtual receptionist. Here's how I can help you:\n\n"
    "📅 *Book a doctor's appointment*\n"
    "📋 *Share your lab report* for the doctor to review\n\n"
    "How may I assist you today?\n"
    "_(You can reply in Hindi or English)_"
)

MSG_ASK_DOCTOR = "Got it — *{date}* at *{time}*. 👍\n\nWhich doctor would you prefer?\n"

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

MSG_NEED_DATE = (
    "I didn't catch the date and time. Could you tell me when you'd like to come?\n"
    "_(e.g.'Date: 15th May 2026 and Time: 5 PM')_"
)

MSG_START_BOOKING = (
    "Sure! To book your appointment, I'll need a few details:\n\n"
    "👤 *Patient name*\n"
    "📋 *Symptoms*\n"
    "📅 *Preferred date* (e.g. 1st Jan)\n"
    "🕐 *Preferred time* (e.g. 5 PM)\n"
    "👨‍⚕️ *Doctor's name*\n\n"
    "_(You can share all at once or one by one — Hindi or English, both work!)_ 😊"
)

MSG_NEED_DOCTOR = "Which doctor would you like to see?\n_(e.g. 'Dr Mehta', 'Dr Sharma')_"

MSG_OFF_TOPIC = (
    "Sure! Let me note that. 📝\n\n"
    "Shall we continue with your appointment booking, or would you like to stop?\n"
    "_(Reply 'continue' to keep booking or 'stop' to cancel)_"
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

MSG_RESCHEDULE_NEED_DATE = "Got the time! What date would you like?\n_(e.g. '26th May')_"
MSG_RESCHEDULE_NEED_TIME = "Got the date! What time would you prefer?\n_(e.g. '4:00 PM')_"
MSG_RESCHEDULE_NEED_BOTH = "What new date and time would you like?\n_(e.g. '26th May at 4 PM')_"

MSG_NO_RESCHEDULE = (
    "You don't have any active appointment to reschedule. "
    "Would you like to book one? 😊"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    msg_words = set(re.findall(r"\b\w+\b", message.lower()))
    if msg_words & words:
        return True
    if phrases:
        msg_lower = message.lower()
        return any(p in msg_lower for p in phrases)
    return False


_BOOKING_KEYWORDS = {
    "book", "appointment", "appoint", "booking", "schedule",
    "milna", "dikhana", "dikha", "consult", "doctor",
}

def _has_booking_keywords(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _BOOKING_KEYWORDS)


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
    return _word_match(message, words={"continue", "haan", "yes", "ok"}, phrases={"jari rakho"})


def _wants_to_stop(message: str) -> bool:
    return _word_match(message, words={"stop", "nahi", "cancel", "band", "no"})


def _get_resume_message(session_dict: dict) -> str:
    state = session_dict.get("state", "GREETING")
    if state == "COLLECT_DATE_TIME":
        return MSG_NEED_DATE
    elif state == "COLLECT_DOCTOR_PREFERENCE":
        return MSG_ASK_DOCTOR.format(
            date=session_dict.get("requested_date", ""),
            time=session_dict.get("requested_time", ""),
        )
    elif state == "CONFIRM_SLOT":
        return MSG_CONFIRM.format(
            doctor=session_dict.get("doctor_name", ""),
            date=session_dict.get("requested_date", ""),
            time=session_dict.get("requested_time", ""),
        )
    return MSG_GREETING


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def off_topic_node(state: BookingState) -> dict:
    session_dict = state.get("session", {})
    booking_state = session_dict.get("state", "GREETING")
    message = state["incoming_message"].lower()
    bot_response = state.get("bot_response") or MSG_GREETING

    if booking_state == "GREETING" or not session_dict:
        return {
            "reply_message": bot_response,
            "is_off_topic": False,
            "pipeline_log": ["off_topic_node: answered general query, no session"],
        }

    if _wants_to_stop(message):
        return {
            "reply_message": MSG_CANCELLED,
            "is_off_topic": False,
            "session": None,
            "current_booking_state": "GREETING",
            "pipeline_log": ["off_topic_node: patient stopped, session cleared"],
        }

    if _wants_to_continue(message):
        return {
            "reply_message": _get_resume_message(session_dict),
            "is_off_topic": False,
            "pipeline_log": ["off_topic_node: patient wants to continue"],
        }

    return {
        "reply_message": MSG_OFF_TOPIC,
        "is_off_topic": True,
        "pipeline_log": ["off_topic_node: off-topic detected, asked to continue/stop"],
    }


def flow_node(state: BookingState) -> dict:
    from_number = state["from_number"]
    session_dict = state.get("session", {})
    booking_state = session_dict.get("state", "GREETING")
    entities = state.get("extracted_entities", {})
    bot_response = state.get("bot_response")
    incoming_message = state.get("incoming_message", "")

    # ── COLLECT_DOCTOR_PREFERENCE: patient is responding to the doctor list ──
    if booking_state == "COLLECT_DOCTOR_PREFERENCE":
        from app.services.doctor_directory import (
            resolve_selection, format_for_whatsapp,
            match_by_symptoms, all_doctors,
        )
        from app.services.store import find_doctor_profile_by_name

        session = BookingSession(**session_dict)
        shortlist = session.doctor_shortlist or []
        doctors = [find_doctor_profile_by_name(n) for n in shortlist]
        doctors = [d for d in doctors if d]
        if not doctors:
            doctors = match_by_symptoms(session.symptoms) if session.symptoms else all_doctors()

        resolved = resolve_selection(incoming_message, doctors)
        if resolved:
            session.doctor_name = resolved
            session.doctor_shortlist = None
            # Check what's still missing after the doctor is chosen
            remaining = []
            if not session.patient_name: remaining.append("patient_name")
            if not session.requested_date: remaining.append("requested_date")
            if not session.requested_time: remaining.append("requested_time")

            if not remaining:
                session.state = "CONFIRM_SLOT"
                return {
                    "session": session.model_dump(),
                    "current_booking_state": "CONFIRM_SLOT",
                    "reply_message": MSG_CONFIRM.format(
                        doctor=session.doctor_name,
                        date=session.requested_date,
                        time=session.requested_time,
                    ),
                    "pipeline_log": [f"flow_node: doctor={resolved}, all info present → CONFIRM_SLOT"],
                }

            # Still need name/date/time — ask for the remaining fields
            session.state = "COLLECTING_INFO"
            parts = [f"*{resolved}* selected!"]
            parts.append("\nI still need a couple of details:\n")
            if "patient_name" in remaining: parts.append("👤 *Patient name*")
            if "requested_date" in remaining: parts.append("📅 *Preferred date* (e.g. 28th May)")
            if "requested_time" in remaining: parts.append("🕐 *Preferred time* (e.g. 5 PM)")
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": "\n".join(parts),
                "pipeline_log": [f"flow_node: doctor={resolved}, still need {remaining}"],
            }

        # Could not resolve — re-show the doctor list
        return {
            "session": session.model_dump(),
            "current_booking_state": "COLLECT_DOCTOR_PREFERENCE",
            "reply_message": "I didn't catch that. Please pick a doctor:\n\n" + format_for_whatsapp(doctors),
            "pipeline_log": ["flow_node: COLLECT_DOCTOR_PREFERENCE — unresolved, re-asked"],
        }
    # ── END COLLECT_DOCTOR_PREFERENCE ────────────────────────────────────────

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

    session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)

    # If COLLECTING_INFO but no data collected yet, treat as a fresh GREETING
    if booking_state == "COLLECTING_INFO" and not any([
        session.patient_name, session.requested_date, session.requested_time, session.doctor_name
    ]):
        booking_state = "GREETING"
        session.state = "GREETING"

    if entities.get("patient_name"): session.patient_name = entities["patient_name"]
    if entities.get("requested_date"): session.requested_date = entities["requested_date"]
    if entities.get("requested_time"): session.requested_time = entities["requested_time"]
    if entities.get("doctor_name"): session.doctor_name = entities["doctor_name"]
    if entities.get("symptoms_mentioned"): session.symptoms = entities["symptoms_mentioned"]

    missing = []
    if not session.patient_name: missing.append("patient_name")
    if not session.requested_date: missing.append("requested_date")
    if not session.requested_time: missing.append("requested_time")
    if not session.doctor_name: missing.append("doctor_name")

    if missing:
        is_booking = (
            state.get("intent") == "appointment_book"
            or _has_booking_keywords(state.get("incoming_message", ""))
        )

        # When doctor_name is the only remaining unknown, show the doctor selection list
        if missing == ["doctor_name"] and is_booking:
            from app.services.doctor_directory import (
                match_by_symptoms, all_doctors, format_for_whatsapp,
            )
            doctors = match_by_symptoms(session.symptoms) if session.symptoms else all_doctors()
            session.state = "COLLECT_DOCTOR_PREFERENCE"
            session.doctor_shortlist = [d.get("name") for d in doctors if d.get("name")]
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECT_DOCTOR_PREFERENCE",
                "reply_message": format_for_whatsapp(doctors),
                "pipeline_log": ["flow_node: doctor_name only missing → showing doctor list"],
            }

        if is_booking or booking_state not in ("GREETING",):
            session.state = "COLLECTING_INFO"

        if booking_state == "GREETING" and not is_booking:
            reply = MSG_GREETING
        elif booking_state == "GREETING" and is_booking:
            reply = MSG_START_BOOKING
        else:
            reply = bot_response or MSG_START_BOOKING
        return {
            "session": session.model_dump(),
            "current_booking_state": session.state,
            "reply_message": reply,
            "pipeline_log": [f"flow_node: COLLECTING_INFO — missing {missing}"],
        }
    else:
        session.state = "CONFIRM_SLOT"
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
        return {
            "current_booking_state": "GREETING",
            "session": None,
            "appointment_id": None,
            "reply_message": MSG_CANCELLED,
            "pipeline_log": ["confirm_node: patient said no, session cleared"],
        }

    return {
        "current_booking_state": "CONFIRM_SLOT",
        "reply_message": (
            f"Sorry, I didn't catch that. Please reply *yes* to confirm or *no* to cancel.\n\n"
            f"👨‍⚕️ *{session.doctor_name}* | 📅 {session.requested_date} | 🕐 {session.requested_time}"
        ),
        "pipeline_log": ["confirm_node: unclear response, re-asked"],
    }


def reschedule_node(state: BookingState) -> dict:
    from app.services.scheduler import cancel_reminder

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    booking_state = session_dict.get("state", "GREETING")

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
            "reply_message": MSG_RESCHEDULE_CONFIRM.format(new_date=new_date, new_time=new_time),
            "pipeline_log": ["reschedule_node: got both, asking confirmation"],
        }

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
                doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
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
            doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
        ),
        "pipeline_log": ["reschedule_node: asked for new date/time"],
    }


def cancel_node(state: BookingState) -> dict:
    from app.services.identity import find_doctor_number
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.scheduler import cancel_reminder, cancel_no_show_jobs

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    booking_state = session_dict.get("state", "GREETING")

    if booking_state == "CANCEL_CONFIRM":
        if _is_affirmative(message):
            appt = get_latest_appointment_for_patient(from_number)
            if appt:
                cancel_appointment(appt.appointment_id)
                cancel_reminder(appt.appointment_id)
                cancel_no_show_jobs(appt.appointment_id)
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
                        doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
                    ),
                    "pipeline_log": [f"cancel_node: appointment {appt.appointment_id} cancelled"],
                }
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

    if booking_state in ("COLLECTING_INFO", "CONFIRM_SLOT"):
        return {
            "session": None,
            "current_booking_state": "GREETING",
            "reply_message": MSG_CANCELLED,
            "pipeline_log": ["cancel_node: cancelled in-progress booking"],
        }

    if booking_state == "WAITING_DOCTOR_APPROVAL":
        appt = get_latest_appointment_for_patient(from_number)
        if appt:
            session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
            session.state = "CANCEL_CONFIRM"
            return {
                "session": session.model_dump(),
                "current_booking_state": "CANCEL_CONFIRM",
                "reply_message": MSG_CANCEL_CONFIRM.format(
                    doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
                ),
                "pipeline_log": ["cancel_node: approval already done, asked for cancel confirmation"],
            }
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
            doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
        ),
        "pipeline_log": ["cancel_node: asked for cancel confirmation"],
    }


def appointment_status_node(state: BookingState) -> dict:
    from_number = state["from_number"]
    appt = get_latest_appointment_for_patient(from_number)

    if appt:
        return {
            "reply_message": (
                f"✅ *Your appointment is confirmed!*\n\n"
                f"👨‍⚕️ Doctor : *{appt.doctor_name}*\n"
                f"📅 Date   : *{appt.date_str}*\n"
                f"🕐 Time   : *{appt.time_str}*\n\n"
                "We'll send you a reminder before your appointment. 🙏"
            ),
            "pipeline_log": ["appointment_status_node: confirmed appointment found"],
        }

    approval = get_latest_approval_for_patient(from_number)
    if approval and approval.get("status") == "waiting_doctor":
        return {
            "reply_message": (
                "⏳ Your appointment request is *waiting for doctor approval*.\n\n"
                f"👨‍⚕️ Doctor : *{approval.get('doctor_name', '?')}*\n"
                f"📅 Date   : *{approval.get('requested_date', '?')}*\n"
                f"🕐 Time   : *{approval.get('requested_time', '?')}*\n\n"
                "We'll notify you as soon as the doctor responds."
            ),
            "pipeline_log": ["appointment_status_node: pending approval found"],
        }

    return {
        "reply_message": (
            "You don't have any active appointment at the moment. "
            "Would you like to book one? 😊"
        ),
        "pipeline_log": ["appointment_status_node: no appointment found"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def route_booking(
    state: BookingState,
) -> Literal["flow_node", "off_topic_node", "confirm_node", "cancel_node",
             "reschedule_node", "appointment_status_node"]:
    intent = state.get("intent", "general_query")
    booking_state = state.get("current_booking_state", "GREETING")

    if intent == "appointment_status":
        return "appointment_status_node"

    if booking_state in ("RESCHEDULE_COLLECTING", "RESCHEDULE_CONFIRM"):
        return "reschedule_node"

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

def build_booking_agent_graph():
    g = StateGraph(BookingState)

    g.add_node("off_topic_node", off_topic_node)
    g.add_node("flow_node", flow_node)
    g.add_node("confirm_node", confirm_node)
    g.add_node("cancel_node", cancel_node)
    g.add_node("reschedule_node", reschedule_node)
    g.add_node("appointment_status_node", appointment_status_node)

    g.add_conditional_edges(
        START,
        route_booking,
        {
            "flow_node": "flow_node",
            "off_topic_node": "off_topic_node",
            "confirm_node": "confirm_node",
            "cancel_node": "cancel_node",
            "reschedule_node": "reschedule_node",
            "appointment_status_node": "appointment_status_node",
        },
    )

    g.add_edge("off_topic_node", END)
    g.add_edge("flow_node", END)
    g.add_edge("confirm_node", END)
    g.add_edge("cancel_node", END)
    g.add_edge("reschedule_node", END)
    g.add_edge("appointment_status_node", END)

    return g.compile()


booking_agent_graph = build_booking_agent_graph()
