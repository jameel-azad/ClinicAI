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
    resolve_slot,
)
from app.services.store import (
    cancel_appointment,
    get_appointment,
    get_active_appointments_for_patient,
    get_latest_appointment_for_patient,
    get_latest_approval_for_patient,
    update_pending_approval,
)

load_dotenv()

_CLINIC_NAME = os.getenv("CLINIC_NAME", "ClinicAI")


# ── LLM ───────────────────────────────────────────────────────────────────────

def _make_llm(vendor: str = "groq", model: str = None, enc_key: str = None):
    """Build a LangChain LLM using per-clinic config, falling back to env vars."""
    from app.services.llm_factory import get_llm_for_vendor
    return get_llm_for_vendor(
        vendor,
        model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        enc_key,
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
    "👨‍⚕️ Doctor: *{doctor}*\n"
    "📅 Date  : *{date}*\n"
    "🕐 Time  : *{time}*\n\n"
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
    "👨‍⚕️ Doctor: *{doctor}*\n"
    "📅 Date  : *{date}*\n"
    "🕐 Time  : *{time}*\n\n"
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
    "👨‍⚕️ Doctor: *{doctor}*\n"
    "📅 Date  : *{date}*\n"
    "🕐 Time  : *{time}*\n\n"
    "What new date and time would you like?\n"
    "_(e.g. '26th May at 4 PM')_"
)

MSG_RESCHEDULE_CONFIRM = (
    "Got it! Reschedule your appointment with *{doctor}* to:\n\n"
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

MSG_SYMPTOM_TO_BOOKING = (
    "I can see you're dealing with some health concerns — our doctors are here to help! 🏥\n\n"
    "To connect you with a doctor, let me set up an appointment. Could you share:\n\n"
    "👤 *Patient name*\n"
    "📅 *Preferred date* (e.g. 15 June)\n"
    "🕐 *Preferred time* (e.g. 5 PM)\n"
    "👨‍⚕️ *Doctor's name* (optional)\n\n"
    "_(Hindi or English, both work!)_ 😊"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_booking_entities(
    message: str,
    context: str = "",
    vendor: str = "groq",
    model: str = None,
    enc_key: str = None,
) -> dict:
    try:
        llm = _make_llm(vendor, model, enc_key)
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


_GREETING_WORDS = {
    "hi", "hii", "hiii", "hiiii", "hello", "helo", "hlo", "hey", "heyy", "heya",
    "yo", "namaste", "namaskar", "namastey", "hola", "salaam", "assalam", "adaab",
    "gm", "start", "greetings", "hey there", "hii there",
}
_GREETING_PHRASES = {
    "good morning", "good afternoon", "good evening", "good day",
    "hey there", "hi there", "hello there",
}

def _is_greeting(message: str) -> bool:
    """True when the message is a bare greeting ('hi', 'hello', 'namaste', 'gm')
    rather than an actual question — so we can reply with the welcome template."""
    msg = message.strip().lower()
    cleaned = re.sub(r"[^\w\s]", "", msg).strip()  # drop punctuation/emoji
    if not cleaned:
        return False
    words = cleaned.split()
    if len(words) <= 3:
        if any(w in _GREETING_WORDS for w in words):
            return True
        if any(p in msg for p in _GREETING_PHRASES):
            return True
    return False


def _is_affirmative(message: str) -> bool:
    return _word_match(
        message,
        words={"yes", "yeah", "yep", "y", "ok", "okay", "haan", "ha",
               "confirm", "confirmed", "bilkul", "sure", "done"},
        phrases={"theek hai", "हाँ", "हां", "ठीक है", "बिल्कुल", "ओके",
                 "जी हाँ", "हो जाएगा", "कर दो"},
    )


def _is_negative(message: str) -> bool:
    return _word_match(
        message,
        words={"no", "nope", "nahi", "nahin", "cancel", "stop", "nhi"},
        phrases={"band karo", "mat karo", "नहीं", "नही", "मत करो",
                 "बंद करो", "रद्द करो"},
    )


def _wants_to_continue(message: str) -> bool:
    return _word_match(message, words={"continue", "haan", "yes", "ok"}, phrases={"jari rakho"})


def _wants_to_stop(message: str) -> bool:
    return _word_match(message, words={"stop", "nahi", "cancel", "band", "no"})


def _finalize_slot(session: BookingSession) -> None:
    """Resolve vague date/time ('tomorrow', 'anytime') into a concrete bookable slot
    so the confirmation shows a real date/time and downstream calendar/reminders work.
    Mutates the session in place; best-effort (leaves values untouched on failure)."""
    try:
        session.requested_date, session.requested_time = resolve_slot(
            session.doctor_name, session.requested_date, session.requested_time
        )
    except Exception as exc:
        print(f"[WARN] slot resolution failed: {exc}")


def _is_past_date(date_str: str | None) -> tuple[bool, str | None]:
    """Return (is_past, display_str) for a free-text date.

    is_past=True  → the date resolves to before today (in clinic timezone).
    display_str   → normalised 'D Month YYYY' string, or None if unparseable.
    """
    if not date_str:
        return False, None
    try:
        from app.services.google_calendar import resolve_date
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata"))
        resolved = resolve_date(date_str, tz)
        if resolved is None:
            return False, None
        today = datetime.now(tz).date()
        display = f"{resolved.day} {resolved.strftime('%B %Y')}"
        return resolved < today, display
    except Exception:
        return False, None


def _validate_time_in_hours(time_str: str | None, doctor_name: str | None) -> str | None:
    """Return a user-facing error if time_str is outside doctor working hours, else None."""
    if not time_str:
        return None
    from app.services.google_calendar import is_vague_time
    if is_vague_time(time_str):
        return None
    try:
        from app.services.store import find_doctor_profile_by_name
        profile = find_doctor_profile_by_name(doctor_name) or {}
        hours_text = profile.get("working_hours") or ""
        m_h = re.search(r"(\d{1,2})(?::\d{2})?\s*[-–]\s*(\d{1,2})(?::\d{2})?", hours_text)
        start_h = int(m_h.group(1)) if m_h else int(os.getenv("CLINIC_OPEN_HOUR", "9"))
        end_h = int(m_h.group(2)) if m_h else int(os.getenv("CLINIC_CLOSE_HOUR", "20"))

        m_t = re.match(r"(\d{1,2})(?::\d{2})?\s*(am|pm)?", time_str.strip().lower())
        if not m_t:
            return None
        hour = int(m_t.group(1))
        meridiem = m_t.group(2)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        elif not meridiem and hour <= 12:
            return None  # ambiguous 12-hour without am/pm — skip validation

        if hour < start_h or hour >= end_h:
            def _fmt_h(h: int) -> str:
                sfx = "AM" if h < 12 else "PM"
                dh = h % 12 or 12
                return f"{dh}:00 {sfx}"
            return (
                f"Sorry, the doctor is not available at *{time_str}*. "
                f"Working hours are *{_fmt_h(start_h)}* to *{_fmt_h(end_h)}*.\n"
                "Please choose a time during working hours. _(e.g. '10 AM', '3:30 PM')_"
            )
    except Exception:
        pass
    return None


def _ask_for_missing(session: "BookingSession", missing: list) -> str:
    """Return a targeted prompt for exactly the missing booking fields."""
    if missing == ["requested_time"]:
        date_hint = f" on *{session.requested_date}*" if session.requested_date else ""
        return f"Got it! What time would you prefer{date_hint}?\n_(e.g. '5 PM', '3:30 PM')_"
    if missing == ["requested_date"]:
        return "What date would you prefer?\n_(e.g. '15th June', 'tomorrow')_"
    if missing == ["requested_date", "requested_time"]:
        return "What date and time would you prefer?\n_(e.g. '15 June at 5 PM')_"
    if missing == ["patient_name"]:
        return "Could you share the patient's name? 👤"
    # Multiple missing — list them
    parts = []
    if "patient_name" in missing: parts.append("👤 *Patient name*")
    if "requested_date" in missing: parts.append("📅 *Preferred date* (e.g. 15 June)")
    if "requested_time" in missing: parts.append("🕐 *Preferred time* (e.g. 5 PM)")
    if "doctor_name" in missing: parts.append("👨‍⚕️ *Doctor's name*")
    return "Almost there! Just need:\n\n" + "\n".join(parts)


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


def _fire_db_status_update(appointment_id: str, status: str, _context=None) -> None:
    """Fire-and-forget PostgreSQL status update for a cancelled/completed appointment."""
    try:
        import asyncio
        from app.services.patient_service import update_appointment_status_in_db
        loop = asyncio.get_running_loop()
        loop.create_task(update_appointment_status_in_db(appointment_id, status))
    except RuntimeError:
        try:
            from app.services.async_runner import run_async
            from app.services.patient_service import update_appointment_status_in_db
            run_async(update_appointment_status_in_db(appointment_id, status), timeout=5)
        except Exception:
            pass
    except Exception:
        pass


def _format_appointment_list(appts: list) -> str:
    """Format a numbered list of appointments for WhatsApp selection."""
    lines = ["Which appointment?\n"]
    for i, a in enumerate(appts, 1):
        lines.append(f"*{i}.* {a.doctor_name} — {a.date_str} at {a.time_str}")
    lines.append("\nReply with the number (e.g. *1*).")
    return "\n".join(lines)


def _parse_selection(message: str, max_count: int):
    """Return 0-based index from a 1-based reply, or None if invalid."""
    stripped = message.strip()
    if stripped.isdigit():
        n = int(stripped)
        if 1 <= n <= max_count:
            return n - 1
    return None


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
    intent = state.get("intent", "general_query")

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

            # Re-validate the stored date in case it was set before this state
            if session.requested_date:
                _past, _display = _is_past_date(session.requested_date)
                if _past:
                    session.requested_date = None
                    session.state = "COLLECTING_INFO"
                    return {
                        "session": session.model_dump(),
                        "current_booking_state": "COLLECTING_INFO",
                        "reply_message": (
                            f"Sorry, *{_display}* has already passed. "
                            "Please share a future date for your appointment.\n"
                            "_(e.g. 'tomorrow', '15 June', 'next Monday')_"
                        ),
                        "pipeline_log": [f"flow_node: past date '{_display}' rejected in COLLECT_DOCTOR_PREFERENCE"],
                    }
                if not _display:
                    # Invalid date (e.g. "31 February") — clear silently; re-asked below
                    session.requested_date = None

            # Check what's still missing after the doctor is chosen
            remaining = []
            if not session.patient_name: remaining.append("patient_name")
            if not session.requested_date: remaining.append("requested_date")
            if not session.requested_time: remaining.append("requested_time")

            if not remaining:
                _finalize_slot(session)
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

        # Could not resolve — show a clear "not found" message then re-list
        _attempted = incoming_message.strip()
        _not_found_msg = (
            f"Sorry, *{_attempted}* is not registered at this clinic.\n\n"
            if len(_attempted) <= 40
            else "Sorry, that doctor is not registered at this clinic.\n\n"
        )
        return {
            "session": session.model_dump(),
            "current_booking_state": "COLLECT_DOCTOR_PREFERENCE",
            "reply_message": _not_found_msg + format_for_whatsapp(doctors),
            "pipeline_log": ["flow_node: COLLECT_DOCTOR_PREFERENCE — doctor not found, re-showed list"],
        }
    # ── END COLLECT_DOCTOR_PREFERENCE ────────────────────────────────────────

    if booking_state == "BOOKED":
        if intent == "appointment_book":
            # Patient wants another appointment — start a fresh booking, keep identity
            fresh = BookingSession(
                from_number=from_number,
                clinic_id=session_dict.get("clinic_id"),
                clinic_twilio_number=session_dict.get("clinic_twilio_number"),
                patient_name=session_dict.get("patient_name"),
                journey_state="BOOKING_IN_PROGRESS",
            )
            return {
                "session": fresh.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": MSG_START_BOOKING,
                "pipeline_log": ["flow_node: BOOKED patient starting additional booking"],
            }
        # Status check or unrecognised message — show all active appointments
        active_appts = get_active_appointments_for_patient(from_number)
        if active_appts:
            if len(active_appts) == 1:
                a = active_appts[0]
                reply = (
                    f"✅ *Your appointment is confirmed!*\n\n"
                    f"👨‍⚕️ Doctor : *{a.doctor_name}*\n"
                    f"📅 Date   : *{a.date_str}*\n"
                    f"🕐 Time   : *{a.time_str}*\n\n"
                    "We'll send you a reminder before your appointment. 🙏"
                )
            else:
                lines = [f"✅ *You have {len(active_appts)} upcoming appointments:*\n"]
                for idx, a in enumerate(active_appts, 1):
                    lines.append(f"*{idx}.* {a.doctor_name} — {a.date_str} at {a.time_str}")
                lines.append("\nReply *cancel* or *reschedule* to manage one, or *book* for another.")
                reply = "\n".join(lines)
            return {
                "current_booking_state": "BOOKED",
                "reply_message": reply,
                "pipeline_log": ["flow_node: BOOKED — showed active appointment summary"],
            }
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
        if status == "cancelled":
            return {
                "session": None,
                "current_booking_state": "GREETING",
                "reply_message": "Your previous request was cancelled. Would you like to book a new appointment?",
                "pipeline_log": ["flow_node: patient-cancelled approval, resetting to GREETING"],
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

    # Bare greeting in any non-committed state → fresh welcome and session reset.
    # This prevents stale Redis sessions (from previous incomplete bookings) from
    # causing the classifier's LLM bot_response to leak through instead of MSG_GREETING.
    if _is_greeting(incoming_message) and booking_state in (
        "GREETING", "COLLECTING_INFO", "COLLECT_DOCTOR_PREFERENCE"
    ):
        fresh = BookingSession(
            from_number=from_number,
            clinic_id=session.clinic_id,
            clinic_twilio_number=session.clinic_twilio_number,
        )
        return {
            "session": fresh.model_dump(),
            "current_booking_state": "GREETING",
            "reply_message": MSG_GREETING,
            "pipeline_log": ["flow_node: bare greeting → welcome menu, session reset"],
        }

    # Apply entities first so the COLLECTING_INFO check below sees any data from
    # the current message (not just what was accumulated in previous turns).
    if entities.get("patient_name"): session.patient_name = entities["patient_name"]
    if entities.get("requested_date"): session.requested_date = entities["requested_date"]
    if entities.get("requested_time"): session.requested_time = entities["requested_time"]
    if entities.get("symptoms_mentioned"): session.symptoms = entities["symptoms_mentioned"]

    # Validate extracted doctor name against the clinic directory before accepting it.
    if entities.get("doctor_name"):
        from app.services.doctor_directory import (
            resolve_selection, all_doctors, format_for_whatsapp,
        )
        _raw_doctor = entities["doctor_name"]
        _all_docs = all_doctors()
        _resolved = resolve_selection(_raw_doctor, _all_docs)
        if _resolved:
            session.doctor_name = _resolved  # normalise to canonical name from DB
        else:
            # Doctor name provided but not in this clinic — show list with explanation
            session.doctor_name = None
            session.state = "COLLECT_DOCTOR_PREFERENCE"
            session.doctor_shortlist = [d.get("name") for d in _all_docs if d.get("name")]
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECT_DOCTOR_PREFERENCE",
                "reply_message": (
                    f"Sorry, *{_raw_doctor}* is not registered at this clinic.\n\n"
                    + format_for_whatsapp(_all_docs)
                ),
                "pipeline_log": [f"flow_node: doctor '{_raw_doctor}' not found in clinic → showing list"],
            }

    # Reject past/invalid dates — validate the date from the current message.
    if session.requested_date and entities.get("requested_date"):
        _past, _display = _is_past_date(session.requested_date)
        if _past:
            session.requested_date = None
            session.state = "COLLECTING_INFO"
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": (
                    f"Sorry, *{_display}* has already passed. "
                    "Please share a future date for your appointment.\n"
                    "_(e.g. 'tomorrow', '15 June', 'next Monday')_"
                ),
                "pipeline_log": [f"flow_node: past date '{_display}' rejected"],
            }
        if not _display:
            # Date string present but unresolvable (e.g. "31 February") — invalid
            raw = entities.get("requested_date", session.requested_date)
            session.requested_date = None
            session.state = "COLLECTING_INFO"
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": (
                    f"Sorry, *{raw}* doesn't look like a valid date. "
                    "Please share a real date like '15 June' or 'next Monday'."
                ),
                "pipeline_log": [f"flow_node: invalid date '{raw}' rejected"],
            }

    # If COLLECTING_INFO but still no data at all, treat as a fresh GREETING so
    # the patient gets the proper welcome prompt instead of a generic re-ask.
    if booking_state == "COLLECTING_INFO" and not any([
        session.patient_name, session.requested_date, session.requested_time, session.doctor_name
    ]):
        booking_state = "GREETING"
        session.state = "GREETING"

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

        # New patient opened with symptoms — bridge to the booking flow
        if state.get("intent") == "consultation_message" and booking_state == "GREETING":
            session.state = "COLLECTING_INFO"
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": MSG_SYMPTOM_TO_BOOKING,
                "pipeline_log": ["flow_node: consultation_message from new patient — bridged to booking"],
            }

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
            # A bare greeting gets the predefined welcome menu; a real general
            # question (timings, fees, …) keeps the classifier's tailored answer.
            reply = MSG_GREETING if _is_greeting(incoming_message) else (bot_response or MSG_GREETING)
        elif booking_state == "GREETING" and is_booking:
            reply = MSG_START_BOOKING
        else:
            # Mid-conversation with specific missing fields — use a targeted prompt
            # instead of the LLM bot_response (which is designed for classification,
            # not for tracking what's still left to collect).
            reply = _ask_for_missing(session, missing)
        return {
            "session": session.model_dump(),
            "current_booking_state": session.state,
            "reply_message": reply,
            "pipeline_log": [f"flow_node: COLLECTING_INFO — missing {missing}"],
        }
    else:
        _finalize_slot(session)
        _wh_msg = _validate_time_in_hours(session.requested_time, session.doctor_name)
        if _wh_msg:
            session.requested_time = None
            session.state = "COLLECTING_INFO"
            return {
                "session": session.model_dump(),
                "current_booking_state": "COLLECTING_INFO",
                "reply_message": _wh_msg,
                "pipeline_log": ["flow_node: time outside working hours, re-asking"],
            }
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
    clinic_twilio_number = state.get("clinic_twilio_number")

    if booking_state == "SELECT_APPOINTMENT_RESCHEDULE":
        active_appts = get_active_appointments_for_patient(from_number)
        if not active_appts:
            return {
                "reply_message": MSG_NO_RESCHEDULE,
                "pipeline_log": ["reschedule_node: no active appointments during selection"],
            }
        idx = _parse_selection(message, len(active_appts))
        if idx is None:
            return {
                "current_booking_state": "SELECT_APPOINTMENT_RESCHEDULE",
                "reply_message": (
                    f"Please reply with a number between 1 and {len(active_appts)}.\n\n"
                    + _format_appointment_list(active_appts)
                ),
                "pipeline_log": ["reschedule_node: invalid selection, re-asked"],
            }
        chosen = active_appts[idx]
        session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
        session.state = "RESCHEDULE_COLLECTING"
        session.selected_appointment_id = chosen.appointment_id
        session.requested_date = chosen.date_str
        session.requested_time = chosen.time_str
        session.doctor_name = chosen.doctor_name
        return {
            "session": session.model_dump(),
            "current_booking_state": "RESCHEDULE_COLLECTING",
            "reply_message": MSG_RESCHEDULE_START.format(
                doctor=chosen.doctor_name, date=chosen.date_str, time=chosen.time_str,
            ),
            "pipeline_log": [f"reschedule_node: selection {idx + 1} → {chosen.appointment_id}"],
        }

    if booking_state == "RESCHEDULE_COLLECTING":
        session = BookingSession(**session_dict)
        appt_context = (
            f"Current appointment is on {session.requested_date} at {session.requested_time}. "
            f"'same day'/'usi din'/'same date' means {session.requested_date}. "
            f"'same time'/'usi time' means {session.requested_time}."
        )
        entities = _extract_booking_entities(
            message,
            context=appt_context,
            vendor=state.get("llm_vendor", "groq"),
            model=state.get("llm_model"),
            enc_key=state.get("llm_enc_key"),
        )
        new_date = entities.get("requested_date") or session.new_requested_date
        new_time = entities.get("requested_time") or session.new_requested_time

        # Validate newly extracted date (past / invalid)
        if entities.get("requested_date") and new_date:
            _past, _display = _is_past_date(new_date)
            if _past:
                new_date = None
                session.new_requested_date = None
                session.new_requested_time = new_time
                return {
                    "session": session.model_dump(),
                    "current_booking_state": "RESCHEDULE_COLLECTING",
                    "reply_message": (
                        f"Sorry, *{_display}* has already passed. "
                        "Please share a future date.\n_(e.g. 'next Monday', '20 June')_"
                    ),
                    "pipeline_log": [f"reschedule_node: past date '{_display}' rejected"],
                }
            if not _display:
                new_date = None
                session.new_requested_date = None
                session.new_requested_time = new_time
                return {
                    "session": session.model_dump(),
                    "current_booking_state": "RESCHEDULE_COLLECTING",
                    "reply_message": (
                        "That doesn't look like a valid date. "
                        "Please share a date like '15 June' or 'next Monday'."
                    ),
                    "pipeline_log": ["reschedule_node: invalid date rejected"],
                }

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

        # Both present — validate time against working hours
        _wh_msg = _validate_time_in_hours(new_time, session.doctor_name)
        if _wh_msg:
            session.new_requested_time = None
            return {
                "session": session.model_dump(),
                "current_booking_state": "RESCHEDULE_COLLECTING",
                "reply_message": _wh_msg,
                "pipeline_log": ["reschedule_node: new time outside working hours, re-asking"],
            }

        session.state = "RESCHEDULE_CONFIRM"
        return {
            "session": session.model_dump(),
            "current_booking_state": "RESCHEDULE_CONFIRM",
            "reply_message": MSG_RESCHEDULE_CONFIRM.format(
                    doctor=session.doctor_name or "the doctor",
                    new_date=new_date,
                    new_time=new_time,
                ),
            "pipeline_log": ["reschedule_node: got both, asking confirmation"],
        }

    if booking_state == "RESCHEDULE_CONFIRM":
        session = BookingSession(**session_dict)

        if _is_affirmative(message):
            selected_id = session_dict.get("selected_appointment_id")
            appt = get_appointment(selected_id) if selected_id else get_latest_appointment_for_patient(from_number)
            if appt:
                cancel_appointment(appt.appointment_id)
                cancel_reminder(appt.appointment_id)
                _fire_db_status_update(appt.appointment_id, "cancelled")

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

    active_appts = get_active_appointments_for_patient(from_number)
    if not active_appts:
        return {
            "reply_message": MSG_NO_RESCHEDULE,
            "pipeline_log": ["reschedule_node: no appointment to reschedule"],
        }

    session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
    if len(active_appts) == 1:
        appt = active_appts[0]
        session.state = "RESCHEDULE_COLLECTING"
        session.selected_appointment_id = appt.appointment_id
        session.requested_date = appt.date_str
        session.requested_time = appt.time_str
        session.doctor_name = appt.doctor_name
        return {
            "session": session.model_dump(),
            "current_booking_state": "RESCHEDULE_COLLECTING",
            "reply_message": MSG_RESCHEDULE_START.format(
                doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
            ),
            "pipeline_log": ["reschedule_node: single appointment, asked for new date/time"],
        }

    # Multiple active appointments — show selection list
    session.state = "SELECT_APPOINTMENT_RESCHEDULE"
    session.pending_action = "reschedule"
    return {
        "session": session.model_dump(),
        "current_booking_state": "SELECT_APPOINTMENT_RESCHEDULE",
        "reply_message": _format_appointment_list(active_appts),
        "pipeline_log": [f"reschedule_node: {len(active_appts)} active appointments, showing selection"],
    }


def cancel_node(state: BookingState) -> dict:
    from app.services.identity import find_doctor_number
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.scheduler import cancel_reminder, cancel_no_show_jobs

    from_number = state["from_number"]
    message = state["incoming_message"]
    session_dict = state.get("session") or {}
    booking_state = session_dict.get("state", "GREETING")

    clinic_twilio_number = state.get("clinic_twilio_number")
    if booking_state == "SELECT_APPOINTMENT_CANCEL":
        active_appts = get_active_appointments_for_patient(from_number)
        if not active_appts:
            return {
                "session": None,
                "current_booking_state": "GREETING",
                "reply_message": MSG_NO_APPOINTMENT,
                "pipeline_log": ["cancel_node: no active appointments during selection"],
            }
        idx = _parse_selection(message, len(active_appts))
        if idx is None:
            return {
                "current_booking_state": "SELECT_APPOINTMENT_CANCEL",
                "reply_message": (
                    f"Please reply with a number between 1 and {len(active_appts)}.\n\n"
                    + _format_appointment_list(active_appts)
                ),
                "pipeline_log": ["cancel_node: invalid selection, re-asked"],
            }
        chosen = active_appts[idx]
        session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
        session.state = "CANCEL_CONFIRM"
        session.selected_appointment_id = chosen.appointment_id
        return {
            "session": session.model_dump(),
            "current_booking_state": "CANCEL_CONFIRM",
            "reply_message": MSG_CANCEL_CONFIRM.format(
                doctor=chosen.doctor_name, date=chosen.date_str, time=chosen.time_str,
            ),
            "pipeline_log": [f"cancel_node: selection {idx + 1} → {chosen.appointment_id}"],
        }

    if booking_state == "CANCEL_CONFIRM":
        if _is_affirmative(message):
            selected_id = session_dict.get("selected_appointment_id")
            appt = get_appointment(selected_id) if selected_id else get_latest_appointment_for_patient(from_number)
            if appt:
                cancel_appointment(appt.appointment_id)
                # Fire DB status update (fire-and-forget)
                _fire_db_status_update(appt.appointment_id, "cancelled", clinic_twilio_number)
                cancel_reminder(appt.appointment_id)
                cancel_no_show_jobs(appt.appointment_id)
                doctor_number = find_doctor_number(appt.doctor_name)
                if doctor_number:
                    send_whatsapp_message_sync(
                        doctor_number,
                        f"Patient {appt.patient_name or from_number} has cancelled their "
                        f"appointment on {appt.date_str} at {appt.time_str}.",
                        from_number=clinic_twilio_number,
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
            update_pending_approval(approval["approval_id"], status="cancelled")
            doctor_number = find_doctor_number(approval.get("doctor_name"))
            if doctor_number:
                send_whatsapp_message_sync(
                    doctor_number,
                    f"Patient {approval.get('patient_name') or from_number} has cancelled "
                    f"their appointment request {approval['approval_id']}.",
                    from_number=clinic_twilio_number,
                )
        return {
            "session": None,
            "current_booking_state": "GREETING",
            "reply_message": MSG_PENDING_CANCELLED,
            "pipeline_log": ["cancel_node: pending approval cancelled"],
        }

    active_appts = get_active_appointments_for_patient(from_number)
    if not active_appts:
        return {
            "reply_message": MSG_NO_APPOINTMENT,
            "pipeline_log": ["cancel_node: no appointment found"],
        }

    session = BookingSession(**session_dict) if session_dict else BookingSession(from_number=from_number)
    if len(active_appts) == 1:
        appt = active_appts[0]
        session.state = "CANCEL_CONFIRM"
        session.selected_appointment_id = appt.appointment_id
        return {
            "session": session.model_dump(),
            "current_booking_state": "CANCEL_CONFIRM",
            "reply_message": MSG_CANCEL_CONFIRM.format(
                doctor=appt.doctor_name, date=appt.date_str, time=appt.time_str,
            ),
            "pipeline_log": ["cancel_node: single appointment, asked for cancel confirmation"],
        }

    # Multiple active appointments — show selection list
    session.state = "SELECT_APPOINTMENT_CANCEL"
    session.pending_action = "cancel"
    return {
        "session": session.model_dump(),
        "current_booking_state": "SELECT_APPOINTMENT_CANCEL",
        "reply_message": _format_appointment_list(active_appts),
        "pipeline_log": [f"cancel_node: {len(active_appts)} active appointments, showing selection"],
    }


def appointment_status_node(state: BookingState) -> dict:
    from_number = state["from_number"]
    active_appts = get_active_appointments_for_patient(from_number)

    if active_appts:
        if len(active_appts) == 1:
            appt = active_appts[0]
            reply = (
                f"✅ *Your appointment is confirmed!*\n\n"
                f"👨‍⚕️ Doctor : *{appt.doctor_name}*\n"
                f"📅 Date   : *{appt.date_str}*\n"
                f"🕐 Time   : *{appt.time_str}*\n\n"
                "We'll send you a reminder before your appointment. 🙏"
            )
        else:
            lines = [f"✅ *You have {len(active_appts)} upcoming appointments:*\n"]
            for i, a in enumerate(active_appts, 1):
                lines.append(f"*{i}.* {a.doctor_name} — {a.date_str} at {a.time_str}")
            lines.append("\nReply *cancel* or *reschedule* to manage one.")
            reply = "\n".join(lines)
        return {
            "reply_message": reply,
            "pipeline_log": [f"appointment_status_node: {len(active_appts)} active appointment(s) found"],
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

    if booking_state in (
        "SELECT_APPOINTMENT_RESCHEDULE", "RESCHEDULE_COLLECTING", "RESCHEDULE_CONFIRM"
    ):
        return "reschedule_node"

    if booking_state in ("SELECT_APPOINTMENT_CANCEL", "CANCEL_CONFIRM"):
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
