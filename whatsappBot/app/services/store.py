from datetime import datetime
from typing import Optional
from app.schemas import BookingSession, AppointmentRecord

# ── Session store ──────────────────────────────────────────────────────────────
_sessions: dict[str, BookingSession] = {}


def get_session(from_number: str) -> Optional[BookingSession]:
    return _sessions.get(from_number)


def save_session(session: BookingSession) -> None:
    session.updated_at = datetime.now()
    _sessions[session.from_number] = session


def delete_session(from_number: str) -> None:
    _sessions.pop(from_number, None)


def all_sessions() -> dict:
    return {k: v.model_dump() for k, v in _sessions.items()}


# ── Appointment store ──────────────────────────────────────────────────────────
_appointments: dict[str, AppointmentRecord] = {}


def save_appointment(appt: AppointmentRecord) -> None:
    _appointments[appt.appointment_id] = appt


def get_appointment(appointment_id: str) -> Optional[AppointmentRecord]:
    return _appointments.get(appointment_id)


def get_appointments_by_number(from_number: str) -> list[AppointmentRecord]:
    return [a for a in _appointments.values() if a.from_number == from_number]


def mark_reminder_sent(appointment_id: str) -> None:
    appt = _appointments.get(appointment_id)
    if appt:
        appt.reminder_sent = True


def all_appointments() -> dict:
    return {k: v.model_dump() for k, v in _appointments.items()}
