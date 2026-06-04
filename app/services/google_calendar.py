import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def calendar_enabled() -> bool:
    return bool(os.getenv("GOOGLE_CALENDAR_ENABLED", "").lower() in {"1", "true", "yes"})


def calendar_setup_status() -> tuple[bool, str]:
    if not calendar_enabled():
        return False, "GOOGLE_CALENDAR_ENABLED is not true."

    credentials_file = _credentials_file()
    token_file = _token_file()

    if not credentials_file.exists():
        return False, f"Google OAuth credentials file not found: {credentials_file}"
    if not token_file.exists():
        return False, f"Google token file not found: {token_file}. Run the auth script first."

    try:
        _import_google_libs()
    except ImportError as exc:
        return False, f"Google Calendar dependencies are missing: {exc}"

    return True, "Google Calendar is configured."


def check_google_availability(date_str: str | None, time_str: str | None, calendar_id: str | None = None) -> tuple[bool, str]:
    ready, reason = calendar_setup_status()
    if not ready:
        return False, reason

    start, end = _appointment_window(date_str, time_str)
    service = _service()
    cal_id = calendar_id or _calendar_id()
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": _timezone_name(),
        "items": [{"id": cal_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result.get("calendars", {}).get(cal_id, {}).get("busy", [])

    if busy:
        return False, "Google Calendar shows this slot is busy."
    return True, "Google Calendar shows this slot is free."


def suggest_google_slots(
    date_str: str | None,
    time_str: str | None,
    count: int = 3,
    interval_minutes: int | None = None,
    calendar_id: str | None = None,
) -> list[dict]:
    ready, _ = calendar_setup_status()
    if not ready:
        return []

    start, _ = _appointment_window(date_str, time_str)
    interval = interval_minutes or int(os.getenv("APPOINTMENT_SLOT_INTERVAL_MINUTES", "30"))
    candidates = []

    for offset in range(interval, interval * 9, interval):
        candidates.append(start + timedelta(minutes=offset))
        if offset <= interval * 4:
            candidates.append(start - timedelta(minutes=offset))

    candidates = sorted(c for c in candidates if c.date() == start.date())
    slots = []
    for candidate in candidates:
        candidate_time = _format_time(candidate)
        available, _ = check_google_availability(date_str, candidate_time, calendar_id=calendar_id)
        if available:
            slots.append(
                {
                    "date_str": date_str,
                    "time_str": candidate_time,
                    "label": f"{date_str} at {candidate_time}",
                }
            )
        if len(slots) >= count:
            break

    return slots


def create_google_calendar_event(approval: dict, calendar_id: str | None = None) -> str | None:
    ready, reason = calendar_setup_status()
    if not ready:
        print(f"[Google Calendar] Skipped event creation: {reason}")
        return None

    start, end = _appointment_window(approval.get("date_str"), approval.get("time_str"))
    service = _service()
    cal_id = calendar_id or _calendar_id()
    patient_name = approval.get("patient_name") or approval.get("patient_number") or "Patient"
    doctor_name = approval.get("doctor_name") or "Doctor"
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    event = {
        "summary": f"Clinic appointment - {patient_name}",
        "description": (
            f"Doctor: {doctor_name}\n"
            f"Patient: {patient_name}\n"
            f"Patient WhatsApp: {approval.get('patient_number')}\n"
            f"Reason: {_format_symptoms(approval.get('symptoms'))}\n"
            f"{clinic_name} request: {approval.get('approval_id')}"
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": _timezone_name()},
        "end": {"dateTime": end.isoformat(), "timeZone": _timezone_name()},
    }
    created = service.events().insert(calendarId=cal_id, body=event).execute()
    return created.get("id")


def _service():
    Credentials, Request, build = _import_google_libs()
    creds = Credentials.from_authorized_user_file(str(_token_file()), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


def _import_google_libs():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    return Credentials, Request, build


def _appointment_window(date_str: str | None, time_str: str | None) -> tuple[datetime, datetime]:
    start = _parse_appointment_datetime(date_str, time_str)
    duration = int(os.getenv("APPOINTMENT_DURATION_MINUTES", "30"))
    return start, start + timedelta(minutes=duration)


def _parse_appointment_datetime(date_str: str | None, time_str: str | None) -> datetime:
    date_text = (date_str or "").lower()
    time_text = (time_str or "").lower()
    year = int(os.getenv("DEFAULT_APPOINTMENT_YEAR", str(datetime.now().year)))
    timezone = ZoneInfo(_timezone_name())

    day_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", date_text)
    month_match = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        date_text,
    )
    if not day_match or not month_match:
        raise ValueError(f"Could not parse appointment date: {date_str}")

    hour_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", time_text)
    if not hour_match:
        raise ValueError(f"Could not parse appointment time: {time_str}")

    day = int(day_match.group(1))
    month = MONTHS[month_match.group(1)]
    hour = int(hour_match.group(1))
    minute = int(hour_match.group(2) or "0")
    meridiem = hour_match.group(3)

    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0

    return datetime(year, month, day, hour, minute, tzinfo=timezone)


def _credentials_file() -> Path:
    return Path(os.getenv("GOOGLE_CALENDAR_CREDENTIALS_FILE", "google_credentials.json"))


def _token_file() -> Path:
    return Path(os.getenv("GOOGLE_CALENDAR_TOKEN_FILE", "google_token.json"))


def _calendar_id() -> str:
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")


def _timezone_name() -> str:
    return os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")


def _format_symptoms(symptoms: list[str] | None) -> str:
    return ", ".join(symptoms) if symptoms else "Not provided"


def _format_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")
