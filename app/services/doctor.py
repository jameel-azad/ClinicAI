import os
import re

import re as _re

def _strip_dr(name: str) -> str:
    """Remove leading 'Dr.' / 'Dr ' so templates can add it once consistently."""
    return _re.sub(r"(?i)^dr\.?\s*", "", name).strip()


from app.services.appointment_approval import handle_appointment_button_reply, handle_doctor_approval_reply
from app.services.soap_approval import handle_soap_approval_reply, handle_soap_button_reply
from app.services.store import (
    all_appointments,
    delete_pending_lab_review,
    get_pending_lab_review,
    get_waiting_approvals_for_doctor,
)


def handle_doctor_message(
    message: str,
    doctor_name: str | None = None,
    doctor_number: str | None = None,
    button_payload: str = "",
    clinic_twilio_number: str | None = None,
) -> str:
    text = message.strip().lower()
    name = doctor_name or "Doctor"

    # Button taps come in via ButtonPayload — handle before anything else
    if button_payload and doctor_number:
        soap_reply = handle_soap_button_reply(button_payload, doctor_number)
        if soap_reply:
            return soap_reply
        apt_reply = handle_appointment_button_reply(button_payload, doctor_number)
        if apt_reply:
            return apt_reply

    # CLOSE command — doctor explicitly ends a patient's follow-up session
    if doctor_number:
        close_reply = _handle_close_session(message, doctor_number, name, clinic_twilio_number)
        if close_reply:
            return close_reply

    if doctor_number:
        soap_reply = handle_soap_approval_reply(message, doctor_number)
        if soap_reply:
            return soap_reply

    if doctor_number:
        lab_reply = _handle_lab_review_ack(message, doctor_number, name, clinic_twilio_number)
        if lab_reply:
            return lab_reply

    if doctor_number:
        approval_reply = handle_doctor_approval_reply(message, doctor_number)
        if approval_reply:
            return approval_reply

    # MSG +91NUMBER message  — forward a reply to a patient
    if doctor_number:
        msg_reply = _handle_patient_msg(message, name, clinic_twilio_number)
        if msg_reply:
            return msg_reply

    if not text or text in {"hi", "hello", "start"}:
        return _doctor_greeting(name)

    if text == "help":
        return _help_message(name)

    if text in {"today", "show today", "today appointments", "appointments"}:
        return _format_today_appointments()

    if text in {"pending", "inbox", "show inbox"}:
        return _format_pending_approvals(doctor_number)

    # Natural language queries — keyword-based matching for common doctor questions
    _has_today = re.search(r"\btoday\b|\baaj\b|\btoday'?s?\b", text)
    _has_appt = re.search(r"\bappointment", text)
    _has_pending = re.search(r"\bpending\b|\bwaiting\b|\binbox\b|\bapproval\b", text)
    if _has_today and (_has_appt or _has_pending):
        return _format_today_appointments()
    if _has_pending and not _has_today:
        return _format_pending_approvals(doctor_number)

    # If doctor has an active reply context, silently forward freetext to that patient
    if doctor_number:
        ctx_reply = _handle_context_reply(message, doctor_number, name, text, clinic_twilio_number)
        if ctx_reply:
            return ctx_reply

    return (
        "I understood this as a doctor message, but I do not support that "
        "command yet.\n\n"
        "Try: today, pending, inbox, or help."
    )


def _handle_patient_msg(message: str, doctor_name: str, clinic_twilio_number: str | None = None) -> str | None:
    """
    Handle: MSG +91XXXXXXXXXX your reply text
    Forwards the doctor's freetext reply directly to a patient.
    """
    from app.services.whatsapp import send_whatsapp_message_sync

    match = re.match(
        r"(?i)^MSG\s+(\+?\d[\d\s\-()+]{7,}\d)\s+(.+)",
        message.strip(),
        re.DOTALL,
    )
    if not match:
        return None

    raw_number = match.group(1).strip()
    patient_text = match.group(2).strip()

    # Normalise to E.164-like format
    digits = re.sub(r"\D", "", raw_number)
    patient_number = f"+{digits}" if raw_number.startswith("+") else digits

    if not patient_text:
        return "Please include a message after the number. Example: *MSG +91NUMBER Hi, please take rest.*"

    outbound = f"📩 *Dr. {_strip_dr(doctor_name)}:* {patient_text}"
    sent = send_whatsapp_message_sync(patient_number, outbound, from_number=clinic_twilio_number)
    if sent:
        return f"✅ Message sent to {patient_number}."
    return f"⚠️ Could not send message to {patient_number}. Please try again."


def _handle_context_reply(message: str, doctor_number: str, doctor_name: str, text_lower: str, clinic_twilio_number: str | None = None) -> str | None:
    """
    If the doctor has an active reply context (a patient just messaged them),
    silently forward their freetext to that patient — no command needed.
    After a successful send, the patient is popped from the queue so the next
    most-recent patient becomes the new default recipient.
    """
    from app.services.store import get_doctor_reply_context, pop_doctor_reply_context
    from app.services.whatsapp import send_whatsapp_message_sync

    ctx = get_doctor_reply_context(doctor_number)
    if not ctx:
        return None

    patient_number = ctx.get("patient_number", "")
    patient_name = ctx.get("patient_name") or "patient"

    if not patient_number or not message.strip():
        return None

    # Guard: if the doctor has a pending SOAP note and their message looks like
    # they are trying to manually tell the patient the prescription was sent,
    # redirect them to the APPROVE command instead of silently relaying text.
    # Without this, the patient receives only a freetext relay ("Dr. X: prescription
    # sent") and never gets the actual clinical note.
    if re.search(r"\bprescri|\brx\b|\bmedic|\bconsult|\bnote\b|\breport\b", message.lower()):
        try:
            from app.services.store import get_latest_soap_for_doctor
            pending = get_latest_soap_for_doctor(doctor_number)
            if pending:
                soap_id = pending.get("soap_id", "")
                return (
                    f"⚠️ There is a prescription note waiting for approval for *{patient_name}*.\n\n"
                    f"To send the actual prescription to the patient, please approve it:\n"
                    f"✅ *APPROVE {soap_id}* — sends the consultation note to {patient_name}\n\n"
                    f"_Your message was NOT forwarded. Use APPROVE to deliver the prescription._"
                )
        except Exception:
            pass

    outbound = f"📩 *Dr. {_strip_dr(doctor_name)}:* {message.strip()}"
    sent = send_whatsapp_message_sync(patient_number, outbound, from_number=clinic_twilio_number)
    if sent:
        pop_doctor_reply_context(doctor_number, patient_number)
        return f"✅ Sent to {patient_name}."
    return f"Could not reach {patient_name} ({patient_number}). Please try again."


def _doctor_greeting(name: str) -> str:
    clinic = os.getenv("CLINIC_NAME", "ClinicAI")
    return (
        f"Hello Dr. {_strip_dr(name)}! 👋\n\n"
        f"Welcome to {clinic}. Here's what you can do:\n\n"
        "🎙️ *Voice note* → Send an audio recording and I'll generate a prescription & summary PDF for your patient\n"
        "✅ *Appointments* → Approve or suggest an alternate time for pending patient bookings\n\n"
        "How can I help you today?"
    )


def _help_message(name: str) -> str:
    clinic = os.getenv("CLINIC_NAME", "ClinicAI")
    return (
        f"Hello {name}. This is your {clinic} doctor interface.\n\n"
        "Commands:\n"
        "- *today* — today's appointments\n"
        "- *pending / inbox* — pending approvals\n"
        "- *APPROVE / REJECT {id}* — SOAP note approval\n"
        "- *REGEN {id} feedback* — regenerate SOAP with correction\n"
        "- *YES / NO {id}* — appointment approval\n"
        "- *OK LAB{id}* — acknowledge lab report\n"
        "- *MSG +91NUMBER message* — send a message to any patient\n"
        "- *help* — show this menu\n\n"
        "💡 When a patient sends you a follow-up reply, just type your response — it goes straight to them."
    )


def _appt_is_today(appt: dict) -> bool:
    from datetime import date as _date, datetime as _datetime
    today = _date.today()
    appt_dt = appt.get("appointment_datetime")
    if appt_dt:
        if isinstance(appt_dt, str):
            try:
                appt_dt = _datetime.fromisoformat(appt_dt)
            except Exception:
                appt_dt = None
        if isinstance(appt_dt, _datetime):
            return appt_dt.date() == today
    # Fallback: parse date_str when appointment_datetime is missing or unparseable
    _M = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    ds = (appt.get("date_str") or "").lower().strip()
    if ds in {"today", "aaj"}:
        return True
    day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", ds)
    mon_m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", ds)
    yr_m = re.search(r"\b(20\d{2})\b", ds)
    if day_m and mon_m:
        try:
            yr = int(yr_m.group(1)) if yr_m else today.year
            return _date(yr, _M[mon_m.group(1)[:3]], int(day_m.group(1))) == today
        except Exception:
            pass
    return False


_STATUS_LABEL = {
    "active": "Confirmed",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def _format_today_appointments() -> str:
    all_appts = list(all_appointments().values())
    today_appts = [
        a for a in all_appts
        if _appt_is_today(a) and a.get("status", "active") != "cancelled"
    ]

    if not today_appts:
        return "Today: no appointments scheduled for today."

    lines = ["Today appointments:"]
    for index, appt in enumerate(today_appts, start=1):
        patient = appt.get("patient_name") or appt.get("from_number") or "Unknown patient"
        doctor = appt.get("doctor_name", "Doctor")
        date = appt.get("date_str", "TBD")
        time = appt.get("time_str", "TBD")
        symptoms = appt.get("symptoms") or []
        reason = f" - {', '.join(symptoms)}" if symptoms else ""
        status = appt.get("status", "active")
        label = _STATUS_LABEL.get(status, status.capitalize())
        lines.append(f"{index}. {patient} with {doctor} - {date} at {time}{reason} [{label}]")

    return "\n".join(lines)


def _handle_lab_review_ack(message: str, doctor_number: str, doctor_name: str, clinic_twilio_number: str | None = None) -> str | None:
    """Handle doctor saying 'OK LAB123' — notifies the patient."""
    from app.services.whatsapp import send_whatsapp_message_sync

    match = re.search(r"\bOK\s+(LAB[A-Z0-9]{6})\b", message.strip().upper())
    if not match:
        return None

    lab_id = match.group(1)
    review = get_pending_lab_review(lab_id)
    if not review:
        return f"Lab review *{lab_id}* not found or already acknowledged."

    patient_number = review.get("patient_number", "")
    patient_name = review.get("patient_name") or "patient"

    if patient_number:
        send_whatsapp_message_sync(
            patient_number,
            f"✅ Dr. {_strip_dr(doctor_name)} has reviewed your lab report and acknowledged it. "
            "If you have any concerns, feel free to reach out.",
            from_number=clinic_twilio_number,
        )

    delete_pending_lab_review(lab_id)
    print(f"[lab_ack] {lab_id} acknowledged by {doctor_number}, patient {patient_number} notified")
    return f"✅ Acknowledged. {patient_name.capitalize()} has been notified."


def _handle_close_session(message: str, doctor_number: str, doctor_name: str, clinic_twilio_number: str | None = None) -> str | None:
    """Handle CLOSE command — doctor explicitly ends a patient's follow-up session.

    Accepts:
      CLOSE +91XXXXXXXXXX   — close specific patient
      CLOSE                 — close the patient from active reply context
    """
    from app.services.store import get_doctor_reply_context, pop_doctor_reply_context, reset_session, get_session
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.identity import normalize_whatsapp_number

    match = re.match(
        r"(?i)^CLOSE(?:\s+(\+?\d[\d\s\-()+]{7,}\d))?$",
        message.strip(),
    )
    if not match:
        return None

    raw_number = (match.group(1) or "").strip()

    if raw_number:
        digits = re.sub(r"\D", "", raw_number)
        patient_number = f"+{digits}" if raw_number.startswith("+") else digits
    else:
        # Try active reply context first (most recent patient who messaged)
        ctx = get_doctor_reply_context(doctor_number)
        if ctx:
            patient_number = ctx.get("patient_number", "")
        else:
            # Context was popped after doctor replied — scan sessions for a
            # FOLLOW_UP_PENDING patient still linked to this doctor
            from app.services.store import all_sessions
            patient_number = ""
            seen: set[str] = set()
            for _sk, sdata in all_sessions().items():
                fn = sdata.get("from_number", "")
                if not fn or fn in seen:
                    continue
                seen.add(fn)
                if (
                    sdata.get("journey_state") == "FOLLOW_UP_PENDING"
                    and _strip_dr(sdata.get("doctor_name") or "").lower()
                    == _strip_dr(doctor_name).lower()
                ):
                    patient_number = fn
                    break
        if not patient_number:
            return "No active follow-up patient found. Use: *CLOSE +91PATIENT_NUMBER*"

    # Look up patient session to get name and clinic_id
    session = get_session(patient_number)
    patient_name = (session.patient_name if session else None) or patient_number
    clinic_id = session.clinic_id if session else None

    # Reset the patient's session to NEW_PATIENT
    reset_session(patient_number, clinic_id)

    # Remove from doctor reply context if present
    pop_doctor_reply_context(doctor_number, patient_number)

    # Notify patient
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    send_whatsapp_message_sync(
        patient_number,
        f"Your follow-up session with *Dr. {_strip_dr(doctor_name)}* is now complete. "
        f"Your consultation records have been saved. 😊\n\n"
        f"Feel free to reach out anytime to book a new appointment. Take care! 🙏\n"
        f"— {clinic_name}",
        from_number=clinic_twilio_number,
    )

    return f"✅ Session closed for *{patient_name}*. They've been notified and their session has been reset."


def _format_pending_approvals(doctor_number: str | None) -> str:
    clinic = os.getenv("CLINIC_NAME", "ClinicAI")
    if not doctor_number:
        return f"{clinic} Inbox: no doctor number found for this request."

    approvals = get_waiting_approvals_for_doctor(doctor_number)
    if not approvals:
        return f"{clinic} Inbox: no pending appointment approvals right now."

    lines = [f"{clinic} Inbox - pending approvals:"]
    for index, approval in enumerate(approvals, start=1):
        lines.extend(
            [
                "",
                f"{index}. {approval['approval_id']}",
                f"Patient: {approval.get('patient_name') or approval.get('patient_number')}",
                f"Date: {approval.get('date_str')}",
                f"Time: {approval.get('time_str')}",
                f"Reply YES {approval['approval_id']} or NO {approval['approval_id']}",
            ]
        )
    return "\n".join(lines)
