import asyncio
import os
import re
import uuid

from app.schemas import AppointmentRecord, BookingSession
from app.services.google_calendar import (
    calendar_enabled,
    check_google_availability,
    create_google_calendar_event,
    suggest_google_slots,
)
from app.services.identity import find_doctor_number, normalize_whatsapp_number
from app.services.scheduler import schedule_reminder
from app.services.store import (
    all_appointments,
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
from app.services.whatsapp import send_whatsapp_interactive_buttons, send_whatsapp_message_sync


async def send_approval_request_to_doctor(
    doctor_number: str,
    approval_id: str,
    patient_name: str,
    date_str: str,
    time_str: str,
    symptoms: str,
) -> bool:
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
    return await send_whatsapp_interactive_buttons(doctor_number, body, buttons)


def send_approval_request_sync(
    doctor_number: str,
    approval_id: str,
    patient_name: str,
    date_str: str,
    time_str: str,
    symptoms: str,
) -> bool:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    send_approval_request_to_doctor(
                        doctor_number, approval_id, patient_name, date_str, time_str, symptoms
                    ),
                )
                return future.result(timeout=15)
        return loop.run_until_complete(
            send_approval_request_to_doctor(
                doctor_number, approval_id, patient_name, date_str, time_str, symptoms
            )
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("[approval] send failed: %s", exc)
        return False


def request_doctor_approval(session: BookingSession, patient_number: str) -> tuple[str, str | None]:
    doctor_number = find_doctor_number(session.doctor_name)
    if not doctor_number:
        return (
            "I have your appointment details, but no doctor WhatsApp number is configured yet. "
            "Please ask the clinic admin to set DOCTOR_WHATSAPP_NUMBERS.",
            None,
        )

    slot_available, availability_reason = is_slot_available(
        session.doctor_name,
        session.requested_date,
        session.requested_time,
    )
    if not slot_available:
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
        "status": "waiting_doctor",
    }
    save_pending_approval(approval)

    send_approval_request_sync(
        doctor_number,
        approval_id,
        session.patient_name or patient_number,
        session.requested_date,
        session.requested_time,
        _format_symptoms(session.symptoms),
    )

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
) -> tuple[bool, str]:
    if calendar_enabled():
        try:
            return check_google_availability(date_str, time_str)
        except Exception as exc:
            print(f"[WARN] Google Calendar check failed, falling back to local: {exc}")
            # Fall through to local calendar check below

    for appt in all_appointments().values():
        if (
            _same(appt.get("doctor_name"), doctor_name)
            and _same_date(appt.get("date_str"), date_str)
            and _same_time(appt.get("time_str"), time_str)
        ):
            return False, "Local calendar already has a confirmed appointment."

    for approval in get_waiting_approvals_for_doctor(find_doctor_number(doctor_name) or ""):
        if (
            _same(approval.get("doctor_name"), doctor_name)
            and _same_date(approval.get("date_str"), date_str)
            and _same_time(approval.get("time_str"), time_str)
        ):
            return False, "Local calendar already has a pending request for that slot."

    return True, "The local calendar shows this slot is free."


def suggest_alternative_slots(
    patient_number: str,
    doctor_name: str | None,
    date_str: str | None,
    time_str: str | None,
) -> list[dict]:
    if calendar_enabled():
        suggestions = suggest_google_slots(date_str, time_str)
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

    # Persist patient to DB on confirmed appointment (idempotent — unique on clinic+phone)
    clinic_id = approval.get("clinic_id")
    if clinic_id:
        try:
            import asyncio
            from app.services.patient_service import upsert_patient
            loop = asyncio.get_running_loop()
            loop.create_task(
                upsert_patient(clinic_id, approval["patient_number"], approval.get("patient_name"))
            )
        except RuntimeError:
            # Called from a background thread — use run_async fallback
            try:
                from app.services.async_runner import run_async
                run_async(
                    upsert_patient(clinic_id, approval["patient_number"], approval.get("patient_name")),
                    timeout=10,
                )
            except Exception as _pe:
                print(f"[WARN] Could not persist patient on approval: {_pe}")
        except Exception as _pe:
            print(f"[WARN] Could not persist patient on approval: {_pe}")
    google_event_id = create_google_calendar_event(approval)
    update_pending_approval(
        appointment_id,
        status="approved",
        google_calendar_event_id=google_event_id,
    )

    schedule_reminder(
        to=appt.from_number,
        appointment_id=appointment_id,
        doctor=appt.doctor_name,
        date_str=appt.date_str,
        time_str=appt.time_str,
    )

    from app.services.scheduler import schedule_no_show_check
    schedule_no_show_check(
        to=appt.from_number,
        appointment_id=appointment_id,
        date_str=appt.date_str,
        time_str=appt.time_str,
    )

    send_whatsapp_message_sync(
        appt.from_number,
        (
            "Appointment confirmed.\n\n"
            f"Doctor: {appt.doctor_name}\n"
            f"Date: {appt.date_str}\n"
            f"Time: {appt.time_str}\n\n"
            "The doctor has approved this slot."
        ),
    )

    return f"Approved {appointment_id}. I have confirmed the appointment with the patient."


def _reject(approval: dict) -> str:
    approval_id = approval["approval_id"]
    update_pending_approval(approval_id, status="rejected")
    send_whatsapp_message_sync(
        approval["patient_number"],
        (
            f"{approval.get('doctor_name') or 'The doctor'} could not approve that slot. "
            "Please send another preferred date and time."
        ),
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
