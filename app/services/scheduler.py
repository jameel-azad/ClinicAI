import os
import re
from datetime import datetime, timedelta, date as date_type
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

load_dotenv()

REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES_BEFORE", "5"))
_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Singleton scheduler — started once in main.py lifespan
scheduler = BackgroundScheduler(timezone=_TZ_NAME)


def _resolve_appointment_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse appointment date + time into a timezone-aware datetime.
    Handles relative dates (today/aaj, tomorrow/kal, parso) and
    absolute dates (15 May, 15th June 2026).
    Returns None if parsing fails.
    """
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    date_lower = (date_str or "").lower().strip()

    if date_lower in {"today", "aaj"}:
        base = now.date()
    elif date_lower in {"tomorrow", "kal"}:
        base = (now + timedelta(days=1)).date()
    elif date_lower in {"day after tomorrow", "parso"}:
        base = (now + timedelta(days=2)).date()
    else:
        day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", date_lower)
        month_m = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            date_lower,
        )
        if not day_m or not month_m:
            return None
        year_m = re.search(r"\b(20\d{2})\b", date_lower)
        year = int(year_m.group(1)) if year_m else now.year
        try:
            base = date_type(year, _MONTHS[month_m.group(1)], int(day_m.group(1)))
        except ValueError:
            return None

    time_lower = (time_str or "").lower()
    time_m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", time_lower)
    if not time_m:
        return None

    hour = int(time_m.group(1))
    minute = int(time_m.group(2) or "0")
    meridiem = time_m.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    try:
        return datetime(base.year, base.month, base.day, hour, minute, tzinfo=tz)
    except ValueError:
        return None


def _send_reminder_job(to: str, appointment_id: str, doctor: str, date_str: str, time_str: str):
    """The actual job function APScheduler calls in a background thread.
    Imports are done inside to avoid circular imports.
    """
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.store import mark_reminder_sent

    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    body = (
        f"⏰ *Reminder — {clinic_name}*\n\n"
        f"Your appointment with *{doctor}* is coming up!\n"
        f"📅 {date_str}  🕐 {time_str}\n\n"
        f"Please arrive 5–10 minutes early. Reply if you need to reschedule."
    )

    success = send_whatsapp_message_sync(to, body)
    if success:
        mark_reminder_sent(appointment_id)
        print(f"[Reminder] Sent for appointment {appointment_id}")
    else:
        print(f"[Reminder] FAILED for appointment {appointment_id}")


def cancel_reminder(appointment_id: str) -> None:
    job_id = f"reminder_{appointment_id}"
    try:
        scheduler.remove_job(job_id)
        print(f"[Reminder] Cancelled job {job_id}")
    except Exception:
        pass


def schedule_reminder(
    to: str,
    appointment_id: str,
    doctor: str,
    date_str: str,
    time_str: str,
) -> datetime:
    appointment_dt = _resolve_appointment_datetime(date_str, time_str)

    if appointment_dt is None:
        print(
            f"[Reminder] Could not parse '{date_str} {time_str}' for {appointment_id} — skipping"
        )
        return datetime.now()

    now = datetime.now(appointment_dt.tzinfo)
    fire_at = now + timedelta(seconds=20)  # demo: fire 20s after booking confirmed

    scheduler.add_job(
        func=_send_reminder_job,
        trigger=DateTrigger(run_date=fire_at),
        args=[to, appointment_id, doctor, date_str, time_str],
        id=f"reminder_{appointment_id}",
        replace_existing=True,
        misfire_grace_time=60,
    )

    print(
        f"[Reminder] Scheduled for {fire_at.strftime('%Y-%m-%d %H:%M')} "
        f"({REMINDER_MINUTES} min before appointment) — {appointment_id}"
    )
    return fire_at
