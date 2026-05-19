import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

load_dotenv()

REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES_BEFORE", "5"))

# Singleton scheduler — started once in main.py lifespan
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def _send_reminder_job(to: str, appointment_id: str, doctor: str, date_str: str, time_str: str):
    """
    The actual job function APScheduler calls in a background thread.
    Imports are done inside to avoid circular imports.
    """
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.store import mark_reminder_sent

    body = (
        f"⏰ *Reminder — FellowAI*\n\n"
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


def schedule_reminder(
    to: str,
    appointment_id: str,
    doctor: str,
    date_str: str,
    time_str: str,
) -> datetime:

    fire_at = datetime.now() + timedelta(minutes=REMINDER_MINUTES)

    scheduler.add_job(
        func=_send_reminder_job,
        trigger=DateTrigger(run_date=fire_at),
        args=[to, appointment_id, doctor, date_str, time_str],
        id=f"reminder_{appointment_id}",
        replace_existing=True,
        misfire_grace_time=60,  # Fire even if up to 60 sec late
    )

    print(
        f"[Reminder] Scheduled for {fire_at.strftime('%H:%M:%S')} "
        f"({REMINDER_MINUTES} min from now) — appointment {appointment_id}"
    )
    return fire_at
