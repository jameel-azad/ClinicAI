from app.services.appointment_approval import handle_doctor_approval_reply
from app.services.doctor_setup import handle_doctor_setup_message
from app.services.store import all_appointments, get_waiting_approvals_for_doctor


def handle_doctor_message(
    message: str,
    doctor_name: str | None = None,
    doctor_number: str | None = None,
) -> str:
    """
    First doctor-side interface.

    This is intentionally command-first: doctors talk to FellowAI and receive
    summaries, not raw patient chats.
    """
    text = message.strip().lower()
    name = doctor_name or "Doctor"

    if doctor_number:
        setup_reply = handle_doctor_setup_message(message, doctor_number, doctor_name)
        if setup_reply:
            return setup_reply

    if doctor_number:
        approval_reply = handle_doctor_approval_reply(message, doctor_number)
        if approval_reply:
            return approval_reply

    if not text:
        return _help_message(name)

    if text in {"help", "hi", "hello", "start"}:
        return _help_message(name)

    if text in {"today", "show today", "today appointments", "appointments"}:
        return _format_today_appointments()

    if text in {"pending", "inbox", "show inbox"}:
        return _format_pending_approvals(doctor_number)

    return (
        "I understood this as a doctor message, but I do not support that "
        "command yet.\n\n"
        "Try: today, pending, inbox, or help."
    )


def _help_message(name: str) -> str:
    return (
        f"Hello {name}. This is your FellowAI doctor interface.\n\n"
        "Commands you can use now:\n"
        "- setup doctor\n"
        "- profile\n"
        "- today\n"
        "- pending\n"
        "- inbox\n"
        "- help"
    )


def _format_today_appointments() -> str:
    appointments = list(all_appointments().values())
    if not appointments:
        return "Today: no appointments are currently stored."

    lines = ["Today appointments:"]
    for index, appt in enumerate(appointments, start=1):
        patient = appt.get("patient_name") or appt.get("from_number") or "Unknown patient"
        doctor = appt.get("doctor_name", "Doctor")
        date = appt.get("date_str", "TBD")
        time = appt.get("time_str", "TBD")
        symptoms = appt.get("symptoms") or []
        reason = f" - {', '.join(symptoms)}" if symptoms else ""
        lines.append(f"{index}. {patient} with {doctor} - {date} at {time}{reason}")

    return "\n".join(lines)


def _format_pending_approvals(doctor_number: str | None) -> str:
    if not doctor_number:
        return "FellowAI Inbox: no doctor number found for this request."

    approvals = get_waiting_approvals_for_doctor(doctor_number)
    if not approvals:
        return "FellowAI Inbox: no pending appointment approvals right now."

    lines = ["FellowAI Inbox - pending approvals:"]
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
