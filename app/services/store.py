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


# Pending doctor approvals
_pending_approvals: dict[str, dict] = {}


def save_pending_approval(approval: dict) -> None:
    approval["updated_at"] = datetime.now().isoformat()
    _pending_approvals[approval["approval_id"]] = approval


def get_pending_approval(approval_id: str) -> Optional[dict]:
    return _pending_approvals.get(approval_id.upper())


def update_pending_approval(approval_id: str, **updates) -> Optional[dict]:
    approval = get_pending_approval(approval_id)
    if not approval:
        return None
    approval.update(updates)
    approval["updated_at"] = datetime.now().isoformat()
    return approval


def get_waiting_approvals_for_doctor(doctor_number: str) -> list[dict]:
    return [
        approval
        for approval in _pending_approvals.values()
        if approval.get("doctor_number") == doctor_number
        and approval.get("status") == "waiting_doctor"
    ]


def get_latest_approval_for_patient(patient_number: str) -> Optional[dict]:
    matches = [
        approval
        for approval in _pending_approvals.values()
        if approval.get("patient_number") == patient_number
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return matches[0]


def all_pending_approvals() -> dict:
    return _pending_approvals.copy()


# ── First-contact greeting tracker ────────────────────────────────────────────
_greeted_numbers: set[str] = set()


def has_been_greeted(number: str) -> bool:
    return number in _greeted_numbers


def mark_as_greeted(number: str) -> None:
    _greeted_numbers.add(number)


# Doctor profiles and setup sessions
_doctor_profiles: dict[str, dict] = {}
_doctor_setup_sessions: dict[str, dict] = {}
_slot_suggestions: dict[str, list[dict]] = {}


def save_doctor_profile(doctor_number: str, profile: dict) -> None:
    profile["doctor_number"] = doctor_number
    profile["updated_at"] = datetime.now().isoformat()
    _doctor_profiles[doctor_number] = profile


def get_doctor_profile(doctor_number: str) -> Optional[dict]:
    return _doctor_profiles.get(doctor_number)


def find_doctor_profile_by_name(doctor_name: str | None) -> Optional[dict]:
    if not doctor_name:
        return None
    wanted = _profile_key(doctor_name)
    for profile in _doctor_profiles.values():
        if _profile_key(profile.get("name")) == wanted:
            return profile
    return None


def all_doctor_profiles() -> dict:
    return _doctor_profiles.copy()


def save_doctor_setup_session(doctor_number: str, session: dict) -> None:
    session["updated_at"] = datetime.now().isoformat()
    _doctor_setup_sessions[doctor_number] = session


def get_doctor_setup_session(doctor_number: str) -> Optional[dict]:
    return _doctor_setup_sessions.get(doctor_number)


def clear_doctor_setup_session(doctor_number: str) -> None:
    _doctor_setup_sessions.pop(doctor_number, None)


def save_slot_suggestions(patient_number: str, suggestions: list[dict]) -> None:
    _slot_suggestions[patient_number] = suggestions


def get_slot_suggestions(patient_number: str) -> list[dict]:
    return _slot_suggestions.get(patient_number, [])


def clear_slot_suggestions(patient_number: str) -> None:
    _slot_suggestions.pop(patient_number, None)


# ── Pending SOAP approvals ─────────────────────────────────────────────────────
_pending_soaps: dict[str, dict] = {}


def save_pending_soap(soap_id: str, data: dict) -> None:
    data["soap_id"] = soap_id.upper()
    data["created_at"] = datetime.now().isoformat()
    _pending_soaps[soap_id.upper()] = data


def get_pending_soap(soap_id: str) -> Optional[dict]:
    return _pending_soaps.get(soap_id.upper())


def delete_pending_soap(soap_id: str) -> None:
    _pending_soaps.pop(soap_id.upper(), None)


def get_latest_soap_for_doctor(doctor_number: str) -> Optional[dict]:
    matches = [s for s in _pending_soaps.values() if s.get("doctor_number") == doctor_number]
    if not matches:
        return None
    return max(matches, key=lambda s: s.get("created_at", ""))


def _profile_key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())
