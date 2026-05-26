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
from app.services.whatsapp import send_whatsapp_message_sync, send_whatsapp_template_sync


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
        "status": "waiting_doctor",
    }
    save_pending_approval(approval)

    apt_content_sid = os.getenv("APPOINTMENT_APPROVAL_CONTENT_SID", "").strip()
    if apt_content_sid:
        send_whatsapp_template_sync(
            doctor_number,
            apt_content_sid,
            {
                "1": approval_id,
                "2": session.patient_name or patient_number,
                "3": session.doctor_name,
                "4": session.requested_date,
                "5": session.requested_time,
                "6": _format_symptoms(session.symptoms),
            },
        )
    else:
        doctor_message = (
            f"Appointment request {approval_id}\n\n"
            f"Patient: {session.patient_name or patient_number}\n"
            f"Doctor: {session.doctor_name}\n"
            f"Date: {session.requested_date}\n"
            f"Time: {session.requested_time}\n"
            f"Reason: {_format_symptoms(session.symptoms)}\n\n"
            f"Reply YES {approval_id} to approve, NO {approval_id} to reject."
        )
        send_whatsapp_message_sync(doctor_number, doctor_message)

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
    """Handle Approve/Reject tapped from a WhatsApp button for appointment approval."""
    payload = button_payload.strip().lower()
    if payload not in ("apt_approve", "apt_reject"):
        return None

    normalized_doctor = normalize_whatsapp_number(doctor_number)
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
            and _same(appt.get("date_str"), date_str)
            and _same(appt.get("time_str"), time_str)
        ):
            return False, "Local calendar already has a confirmed appointment."

    for approval in get_waiting_approvals_for_doctor(find_doctor_number(doctor_name) or ""):
        if (
            _same(approval.get("doctor_name"), doctor_name)
            and _same(approval.get("date_str"), date_str)
            and _same(approval.get("time_str"), time_str)
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
