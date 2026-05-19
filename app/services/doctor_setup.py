from app.services.google_calendar import calendar_setup_status
from app.services.store import (
    clear_doctor_setup_session,
    get_doctor_profile,
    get_doctor_setup_session,
    save_doctor_profile,
    save_doctor_setup_session,
)


SETUP_STEPS = [
    "name",
    "google_email",
    "working_hours",
    "duration",
    "buffer",
]


def handle_doctor_setup_message(
    message: str,
    doctor_number: str,
    fallback_name: str | None = None,
) -> str | None:
    text = message.strip()
    lower = text.lower()
    existing = get_doctor_setup_session(doctor_number)

    if lower in {"setup doctor", "doctor setup", "setup", "connect calendar"}:
        session = {"step": "name", "profile": {}}
        if fallback_name:
            session["profile"]["name"] = fallback_name
            session["step"] = "google_email"
            save_doctor_setup_session(doctor_number, session)
            return "Doctor setup started.\n\nWhat Google Calendar email should FellowAI use?"
        save_doctor_setup_session(doctor_number, session)
        return "Doctor setup started.\n\nWhat is your doctor name? Example: Dr Pawan"

    if lower in {"profile", "doctor profile", "my profile"}:
        return _format_profile(get_doctor_profile(doctor_number))

    if not existing:
        return None

    step = existing["step"]
    profile = existing.get("profile", {})

    if step == "name":
        profile["name"] = text
        existing["step"] = "google_email"
        existing["profile"] = profile
        save_doctor_setup_session(doctor_number, existing)
        return "Got it. What Google Calendar email should FellowAI use?"

    if step == "google_email":
        profile["google_email"] = text
        existing["step"] = "working_hours"
        existing["profile"] = profile
        save_doctor_setup_session(doctor_number, existing)
        return (
            "Thanks. What are your clinic working hours?\n"
            "Example: Mon-Sat 10 AM-2 PM, 5 PM-8 PM"
        )

    if step == "working_hours":
        profile["working_hours"] = text
        existing["step"] = "duration"
        existing["profile"] = profile
        save_doctor_setup_session(doctor_number, existing)
        return "How long is one appointment slot? Example: 30 minutes"

    if step == "duration":
        profile["appointment_duration_minutes"] = _first_number(text, default=30)
        existing["step"] = "buffer"
        existing["profile"] = profile
        save_doctor_setup_session(doctor_number, existing)
        return "How much buffer time between appointments? Example: 5 minutes"

    if step == "buffer":
        profile["buffer_minutes"] = _first_number(text, default=0)
        profile["calendar_id"] = "primary"
        profile["timezone"] = "Asia/Kolkata"
        ready, reason = calendar_setup_status()
        profile["calendar_connected"] = ready
        profile["calendar_status"] = reason
        save_doctor_profile(doctor_number, profile)
        clear_doctor_setup_session(doctor_number)
        return (
            "Doctor profile saved.\n\n"
            f"{_format_profile(profile)}\n\n"
            "Calendar status: "
            f"{reason}\n\n"
            "If calendar is not connected yet, run the Google auth script and set "
            "GOOGLE_CALENDAR_ENABLED=true."
        )

    return None


def _format_profile(profile: dict | None) -> str:
    if not profile:
        return "No doctor profile saved yet. Send: setup doctor"

    return (
        "Doctor profile\n"
        f"Name: {profile.get('name')}\n"
        f"Google email: {profile.get('google_email')}\n"
        f"Working hours: {profile.get('working_hours')}\n"
        f"Slot duration: {profile.get('appointment_duration_minutes')} minutes\n"
        f"Buffer: {profile.get('buffer_minutes')} minutes"
    )


def _first_number(text: str, default: int) -> int:
    digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
    return int(digits[0]) if digits else default
