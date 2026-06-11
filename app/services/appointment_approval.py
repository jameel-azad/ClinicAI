import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas import AppointmentRecord, BookingSession
from app.services.google_calendar import (
    calendar_enabled,
    check_google_availability,
    create_google_calendar_event,
    is_vague_time,
    period_window,
    resolve_date,
    suggest_google_slots,
)
from app.services.identity import find_doctor_number, normalize_whatsapp_number
from app.services.scheduler import schedule_reminder
from app.services.store import (
    all_appointments,
    find_doctor_profile_by_name,
    get_latest_approval_for_patient,
    get_pending_approval,
    get_slot_suggestions,
    get_waiting_approvals_for_doctor,
    save_slot_suggestions,
    save_appointment,
    save_pending_approval,
    clear_slot_suggestions,
    update_pending_approval,
)
from app.services.whatsapp import (
    send_whatsapp_interactive_buttons,
    send_whatsapp_message_sync,
    send_whatsapp_template_async,
    send_whatsapp_template_sync,
)


async def send_approval_request_to_doctor(
    doctor_number: str,
    approval_id: str,
    patient_name: str,
    date_str: str,
    time_str: str,
    symptoms: str,
    doctor_name: str = "",
    clinic_twilio_number: str | None = None,
) -> bool:
    content_sid = os.getenv("APPOINTMENT_APPROVAL_CONTENT_SID", "").strip()
    if content_sid:
        return await send_whatsapp_template_async(
            doctor_number,
            content_sid,
            {
                "1": patient_name,
                "2": doctor_name or "Doctor",
                "3": date_str,
                "4": time_str,
                "5": symptoms or "Not specified",
            },
            from_number=clinic_twilio_number,
        )
    # Fallback: plain text with button list
    body = (
        f"📅 *New Appointment Request*\n\n"
        f"Patient: *{patient_name}*\n"
        f"Date: {date_str} at {time_str}\n"
        f"Symptoms: {symptoms or 'Not specified'}\n"
        f"Ref: {approval_id}"
    )
    buttons = [
        {"id": f"approve_{approval_id}", "title": "✅ Approve"},
        {"id": f"reject_{approval_id}", "title": "❌ Reject"},
        {"id": f"suggest_{approval_id}", "title": "🕐 Suggest Time"},
    ]
    return await send_whatsapp_interactive_buttons(doctor_number, body, buttons, from_number=clinic_twilio_number)


def send_approval_request_sync(
    doctor_number: str,
    approval_id: str,
    patient_name: str,
    date_str: str,
    time_str: str,
    symptoms: str,
    doctor_name: str = "",
    clinic_twilio_number: str | None = None,
) -> bool:
    import logging
    logger = logging.getLogger(__name__)
    try:
        result = asyncio.run(
            send_approval_request_to_doctor(
                doctor_number, approval_id, patient_name, date_str, time_str, symptoms,
                doctor_name, clinic_twilio_number,
            )
        )
        if not result:
            logger.error("[approval] Twilio rejected message to doctor %s for approval %s", doctor_number, approval_id)
        return result
    except RuntimeError:
        import concurrent.futures
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    send_approval_request_to_doctor(
                        doctor_number, approval_id, patient_name, date_str, time_str, symptoms,
                        doctor_name, clinic_twilio_number,
                    ),
                )
                return future.result(timeout=20)
        except Exception as exc:
            logger.error("[approval] send failed (thread fallback): %s", exc)
            return False
    except Exception as exc:
        logger.error("[approval] send failed: %s", exc)
        return False


_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _parse_working_days(text: str) -> set[int]:
    """Parse 'Mon-Sat' from a working-hours string → {0,1,2,3,4,5}. Defaults Mon-Sat."""
    m = re.search(
        r"(mon|tue|wed|thu|fri|sat|sun)\s*[-–]\s*(mon|tue|wed|thu|fri|sat|sun)",
        (text or "").lower(),
    )
    if m:
        start, end = _DOW[m.group(1)], _DOW[m.group(2)]
        if start <= end:
            return set(range(start, end + 1))
        return set(range(start, 7)) | set(range(0, end + 1))
    return {0, 1, 2, 3, 4, 5}


def _doctor_hours(profile: dict) -> tuple[int, int, set[int]]:
    """Return (start_hour, end_hour, working_weekdays) from a doctor profile."""
    text = profile.get("working_hours") or ""
    m = re.search(r"(\d{1,2})(?::\d{2})?\s*[-–]\s*(\d{1,2})(?::\d{2})?", text)
    start = int(m.group(1)) if m else int(os.getenv("CLINIC_OPEN_HOUR", "9"))
    end = int(m.group(2)) if m else int(os.getenv("CLINIC_CLOSE_HOUR", "18"))
    return start, end, _parse_working_days(text)


def _fmt_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def resolve_slot(
    doctor_name: str | None,
    date_str: str | None,
    time_str: str | None,
) -> tuple[str | None, str | None]:
    """Turn a vague date/time ('tomorrow', 'anytime') into a concrete, bookable slot.

    - Resolves relative/weekday/explicit dates to a concrete 'D Month YYYY' string.
    - Skips forward to the next working day when the date lands on a clinic-closed day.
    - For a vague time, scans the doctor's working-hour window and returns the first
      slot ``is_slot_available`` reports free (covers Google + local calendars).

    Idempotent: a date/time that is already concrete is returned unchanged. Falls back
    to the original strings if the date cannot be parsed.
    """
    profile = find_doctor_profile_by_name(doctor_name) or {}
    start_h, end_h, work_days = _doctor_hours(profile)
    tz = ZoneInfo(os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata"))

    resolved = resolve_date(date_str, tz)
    if resolved is None:
        return date_str, time_str  # unparseable — leave as-is

    for _ in range(7):  # roll to next working day if clinic is closed
        if resolved.weekday() in work_days:
            break
        resolved = resolved + timedelta(days=1)
    resolved_date = f"{resolved.day} {resolved.strftime('%B %Y')}"

    if not is_vague_time(time_str):
        return resolved_date, time_str

    win = period_window(time_str) or (start_h, end_h)
    win_start, win_end = max(start_h, win[0]), min(end_h, win[1])
    if win_start >= win_end:
        win_start, win_end = start_h, end_h

    duration = int(
        profile.get("appointment_duration_minutes")
        or os.getenv("APPOINTMENT_DURATION_MINUTES", "30")
    )
    buffer = int(profile.get("buffer_minutes") or 0)
    step = max(15, duration + buffer)

    cursor = datetime(resolved.year, resolved.month, resolved.day, win_start, 0)
    window_end = datetime(resolved.year, resolved.month, resolved.day, win_end, 0)
    first_slot = _fmt_time(cursor)
    while cursor < window_end:
        candidate = _fmt_time(cursor)
        available, _ = is_slot_available(doctor_name, resolved_date, candidate)
        if available:
            return resolved_date, candidate
        cursor += timedelta(minutes=step)

    # No free slot found in the window — fall back to the first slot of the day.
    return resolved_date, first_slot


def request_doctor_approval(session: BookingSession, patient_number: str) -> tuple[str, str | None]:
    doctor_number = find_doctor_number(session.doctor_name)
    if not doctor_number:
        return (
            "I have your appointment details, but no doctor WhatsApp number is configured yet. "
            "Please ask the clinic admin to set DOCTOR_WHATSAPP_NUMBERS.",
            None,
        )

    # Resolve any vague date/time ('tomorrow', 'anytime') to a concrete bookable slot
    # before checking availability. Idempotent — a no-op if already concrete.
    session.requested_date, session.requested_time = resolve_slot(
        session.doctor_name, session.requested_date, session.requested_time
    )

    slot_available, availability_reason = is_slot_available(
        session.doctor_name,
        session.requested_date,
        session.requested_time,
        patient_number=patient_number,
    )
    if not slot_available:
        # Patient-level duplicate gets a clear, specific message without suggestions
        if "You already have" in availability_reason:
            return availability_reason, None
        suggestions = suggest_alternative_slots(
            patient_number,
            session.doctor_name,
            session.requested_date,
            session.requested_time,
        )
        if suggestions:
            return (
                f"{session.doctor_name} is not available at {session.requested_time} on "
                f"{session.requested_date}. {availability_reason}\n\n"
                "Available nearby slots:\n"
                f"{_format_suggestions(suggestions)}\n\n"
                "Reply 1, 2, or 3 to choose a slot.",
                None,
            )
        return (
            f"{session.doctor_name} is not available at {session.requested_time} on "
            f"{session.requested_date}. {availability_reason} Please send another preferred time.",
            None,
        )

    approval_id = f"APT{str(uuid.uuid4())[:5].upper()}"
    approval = {
        "approval_id": approval_id,
        "patient_number": patient_number,
        "patient_name": session.patient_name,
        "doctor_name": session.doctor_name,
        "doctor_number": doctor_number,
        "date_str": session.requested_date,
        "time_str": session.requested_time,
        "symptoms": session.symptoms,
        "clinic_id": session.clinic_id,
        "clinic_twilio_number": session.clinic_twilio_number,
        "status": "waiting_doctor",
    }
    save_pending_approval(approval)

    print(f"[Approval] Sending request {approval_id} to doctor {doctor_number}")
    sent = send_approval_request_sync(
        doctor_number,
        approval_id,
        session.patient_name or patient_number,
        session.requested_date,
        session.requested_time,
        _format_symptoms(session.symptoms),
        session.doctor_name or "",
        clinic_twilio_number=session.clinic_twilio_number,
    )
    print(f"[Approval] Message sent={sent} to doctor {doctor_number}")

    return (
        f"Thanks. {availability_reason} I have sent this appointment request "
        f"to {session.doctor_name} for final approval. I will confirm here once the doctor replies.\n\n"
        f"Request ID: {approval_id}",
        approval_id,
    )


def request_suggested_slot_approval(
    session: BookingSession,
    patient_number: str,
    selection_message: str,
) -> tuple[str, str | None]:
    selection = _slot_selection(selection_message)
    if selection is None:
        return "Please reply with one of the available slot numbers: 1, 2, or 3.", None

    suggestions = get_slot_suggestions(patient_number)
    if selection >= len(suggestions):
        return "That slot option is not available anymore. Please choose 1, 2, or 3.", None

    slot = suggestions[selection]
    session.requested_date = slot["date_str"]
    session.requested_time = slot["time_str"]
    clear_slot_suggestions(patient_number)
    return request_doctor_approval(session, patient_number)


def handle_doctor_approval_reply(message: str, doctor_number: str) -> str | None:
    text = message.strip()
    action = _approval_action(text)
    if not action:
        return None

    approval_id = _approval_id(text)
    normalized_doctor = normalize_whatsapp_number(doctor_number)

    if not approval_id:
        waiting = get_waiting_approvals_for_doctor(normalized_doctor)
        if len(waiting) == 1:
            approval_id = waiting[0]["approval_id"]
        elif len(waiting) > 1:
            ids = ", ".join(item["approval_id"] for item in waiting)
            return f"Please include the request ID. Pending requests: {ids}"
        else:
            return "There are no pending appointment approvals for you right now."

    approval = get_pending_approval(approval_id)
    if not approval:
        return f"I could not find appointment request {approval_id}."

    if approval.get("doctor_number") != normalized_doctor:
        return "This appointment request is assigned to another doctor number."

    if approval.get("status") != "waiting_doctor":
        return f"Request {approval_id} is already {approval.get('status')}."

    if action == "approve":
        return _approve(approval)

    return _reject(approval)


def handle_appointment_button_reply(button_payload: str, doctor_number: str) -> str | None:
    """Handle button payloads from Meta interactive buttons for appointment approval."""
    payload = button_payload.strip().lower()
    normalized_doctor = normalize_whatsapp_number(doctor_number)

    # Handle new Meta interactive button IDs: approve_<ID> / reject_<ID> / suggest_<ID>
    if payload.startswith("approve_") or payload.startswith("reject_") or payload.startswith("suggest_"):
        parts = payload.split("_", 1)
        action = parts[0]
        approval_id_raw = parts[1].upper() if len(parts) > 1 else ""

        approval = get_pending_approval(approval_id_raw)
        if not approval:
            return f"I could not find appointment request {approval_id_raw}."

        if approval.get("doctor_number") != normalized_doctor:
            return "This appointment request is assigned to another doctor number."

        if approval.get("status") != "waiting_doctor":
            return f"Request {approval_id_raw} is already {approval.get('status')}."

        if action == "approve":
            return _approve(approval)
        if action == "reject":
            return _reject(approval)
        if action == "suggest":
            return (
                f"Please send your preferred alternative date and time for appointment "
                f"{approval_id_raw} and I will update the patient."
            )

    # Legacy fallback: apt_approve / apt_reject (kept for backward compatibility)
    if payload in ("apt_approve", "apt_reject"):
        waiting = get_waiting_approvals_for_doctor(normalized_doctor)

        if not waiting:
            return "There are no pending appointment approvals for you right now."

        if len(waiting) > 1:
            ids = ", ".join(item["approval_id"] for item in waiting)
            return (
                f"You have {len(waiting)} pending approvals. "
                f"Reply YES/NO + the request ID to specify which one:\n{ids}"
            )

        approval = waiting[0]
        if approval.get("status") != "waiting_doctor":
            return f"Request {approval['approval_id']} is already {approval.get('status')}."

        return _approve(approval) if payload == "apt_approve" else _reject(approval)

    return None


def is_slot_available(
    doctor_name: str | None,
    date_str: str | None,
    time_str: str | None,
    patient_number: str | None = None,
) -> tuple[bool, str]:
    if calendar_enabled():
        try:
            profile = find_doctor_profile_by_name(doctor_name) or {}
            cal_id = profile.get("google_calendar_id") or None
            return check_google_availability(date_str, time_str, calendar_id=cal_id)
        except Exception as exc:
            print(f"[WARN] Google Calendar check failed, falling back to local: {exc}")
            # Fall through to local calendar check below

    for appt in all_appointments().values():
        if (
            _same(appt.get("doctor_name"), doctor_name)
            and _same_date(appt.get("date_str"), date_str)
            and _same_time(appt.get("time_str"), time_str)
            and appt.get("status", "active") == "active"
        ):
            # Same patient booking same slot again → duplicate
            if patient_number and appt.get("from_number") == patient_number:
                return False, f"You already have an appointment with Dr. {doctor_name} at that time."
            # Different patient → slot taken by someone else
            return False, "Local calendar already has a confirmed appointment."

    for approval in get_waiting_approvals_for_doctor(find_doctor_number(doctor_name) or ""):
        if (
            _same(approval.get("doctor_name"), doctor_name)
            and _same_date(approval.get("date_str"), date_str)
            and _same_time(approval.get("time_str"), time_str)
        ):
            if patient_number and approval.get("patient_number") == patient_number:
                return False, f"You already have a pending request with Dr. {doctor_name} at that time."
            return False, "Local calendar already has a pending request for that slot."

    return True, "The local calendar shows this slot is free."


def suggest_alternative_slots(
    patient_number: str,
    doctor_name: str | None,
    date_str: str | None,
    time_str: str | None,
) -> list[dict]:
    if calendar_enabled():
        profile = find_doctor_profile_by_name(doctor_name) or {}
        cal_id = profile.get("google_calendar_id") or None
        suggestions = suggest_google_slots(date_str, time_str, calendar_id=cal_id)
        save_slot_suggestions(patient_number, suggestions)
        return suggestions

    suggestions = _suggest_local_slots(doctor_name, date_str, time_str)
    save_slot_suggestions(patient_number, suggestions)
    return suggestions


def latest_patient_approval_status(patient_number: str) -> str | None:
    approval = get_latest_approval_for_patient(patient_number)
    if not approval:
        return None
    return approval.get("status")


def _approve(approval: dict) -> str:
    appointment_id = approval["approval_id"]
    appt = AppointmentRecord(
        appointment_id=appointment_id,
        from_number=approval["patient_number"],
        patient_name=approval.get("patient_name"),
        doctor_name=approval.get("doctor_name") or "Doctor",
        date_str=approval.get("date_str") or "TBD",
        time_str=approval.get("time_str") or "TBD",
        symptoms=approval.get("symptoms"),
    )
    save_appointment(appt)

    # Persist appointment (and patient) to PostgreSQL on confirmation
    clinic_id = approval.get("clinic_id")
    if clinic_id:
        try:
            import asyncio
            from app.services.patient_service import save_appointment_to_db
            loop = asyncio.get_running_loop()
            loop.create_task(save_appointment_to_db(clinic_id, appt, approval))
        except RuntimeError:
            try:
                from app.services.async_runner import run_async
                from app.services.patient_service import save_appointment_to_db
                run_async(save_appointment_to_db(clinic_id, appt, approval), timeout=10)
            except Exception as _pe:
                print(f"[WARN] Could not persist appointment to DB: {_pe}")
        except Exception as _pe:
            print(f"[WARN] Could not persist appointment to DB: {_pe}")
    profile = find_doctor_profile_by_name(approval.get("doctor_name", "")) or {}
    cal_id = profile.get("google_calendar_id") or None
    try:
        google_event_id = create_google_calendar_event(approval, calendar_id=cal_id)
    except Exception as exc:
        # A calendar hiccup must never block the confirmation the patient is waiting for.
        print(f"[WARN] Google Calendar event creation failed for {appointment_id}: {exc}")
        google_event_id = None
    update_pending_approval(
        appointment_id,
        status="approved",
        google_calendar_event_id=google_event_id,
    )

    clinic_twilio_number = approval.get("clinic_twilio_number")
    schedule_reminder(
        to=appt.from_number,
        appointment_id=appointment_id,
        doctor=appt.doctor_name,
        date_str=appt.date_str,
        time_str=appt.time_str,
        clinic_twilio_number=clinic_twilio_number,
    )

    from app.services.scheduler import schedule_no_show_check
    schedule_no_show_check(
        to=appt.from_number,
        appointment_id=appointment_id,
        date_str=appt.date_str,
        time_str=appt.time_str,
        clinic_twilio_number=clinic_twilio_number,
    )

    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    send_whatsapp_message_sync(
        appt.from_number,
        (
            f"✅ *Appointment Confirmed* — {clinic_name}\n\n"
            f"Doctor: *{appt.doctor_name}*\n"
            f"Date: {appt.date_str}\n"
            f"Time: {appt.time_str}\n\n"
            "Please arrive 5–10 minutes early. Reply if you need to reschedule."
        ),
        from_number=clinic_twilio_number,
    )

    return f"Approved {appointment_id}. I have confirmed the appointment with the patient."


def _reject(approval: dict) -> str:
    approval_id = approval["approval_id"]
    update_pending_approval(approval_id, status="rejected")
    send_whatsapp_message_sync(
        approval["patient_number"],
        (
            f"❌ *{approval.get('doctor_name') or 'The doctor'}* could not approve that slot.\n\n"
            "Please send another preferred date and time and we'll find you a new slot."
        ),
        from_number=approval.get("clinic_twilio_number"),
    )
    return f"Rejected {approval_id}. I have asked the patient for another slot."


def _approval_action(message: str) -> str | None:
    lower = message.lower().strip()
    if re.search(r"\b(yes|approve|approved|ok|confirm)\b", lower):
        return "approve"
    if re.search(r"\b(no|reject|rejected|decline|deny)\b", lower):
        return "reject"
    return None


def _approval_id(message: str) -> str | None:
    match = re.search(r"\bAPT[A-Z0-9]{5}\b", message.upper())
    return match.group(0) if match else None


def _same(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def _normalize_date(date_str: str | None) -> str | None:
    """Normalize a free-text date string to YYYY-MM-DD for reliable comparison.
    Falls back to the lowercased raw string when parsing fails.
    """
    if not date_str:
        return None
    try:
        from app.services.scheduler import _resolve_appointment_datetime
        dt = _resolve_appointment_datetime(date_str, "12:00 PM")
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return date_str.strip().lower()


def _normalize_time(time_str: str | None) -> str | None:
    """Normalize a free-text time string to HH:MM (24 h) for reliable comparison."""
    if not time_str:
        return None
    import re as _re
    t = time_str.strip().lower()
    m = _re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if not m:
        return t
    hr, mn = int(m.group(1)), int(m.group(2) or "0")
    mer = m.group(3)
    if mer == "pm" and hr != 12:
        hr += 12
    elif mer == "am" and hr == 12:
        hr = 0
    return f"{hr:02d}:{mn:02d}"


def _same_date(left: str | None, right: str | None) -> bool:
    nl, nr = _normalize_date(left), _normalize_date(right)
    return nl is not None and nl == nr


def _same_time(left: str | None, right: str | None) -> bool:
    nl, nr = _normalize_time(left), _normalize_time(right)
    return nl is not None and nl == nr


def _format_symptoms(symptoms: list[str] | None) -> str:
    return ", ".join(symptoms) if symptoms else "Not provided"


def _slot_selection(message: str) -> int | None:
    stripped = message.strip()
    if stripped in {"1", "2", "3"}:
        return int(stripped) - 1
    return None


def _format_suggestions(suggestions: list[dict]) -> str:
    return "\n".join(
        f"{index}. {slot['label']}"
        for index, slot in enumerate(suggestions, start=1)
    )


_DEFAULT_SLOT_CANDIDATES = ["10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "5:00 PM", "5:30 PM"]


def _suggest_local_slots(
    doctor_name: str | None,
    date_str: str | None,
    time_str: str | None,
) -> list[dict]:
    env_slots = os.getenv("APPOINTMENT_SLOT_CANDIDATES", "")
    candidates = [t.strip() for t in env_slots.split(",") if t.strip()] or _DEFAULT_SLOT_CANDIDATES
    suggestions = []
    for candidate in candidates:
        if _same(candidate, time_str):
            continue
        available, _ = is_slot_available(doctor_name, date_str, candidate)
        if available:
            suggestions.append(
                {
                    "date_str": date_str,
                    "time_str": candidate,
                    "label": f"{date_str} at {candidate}",
                }
            )
        if len(suggestions) >= 3:
            break
    return suggestions
