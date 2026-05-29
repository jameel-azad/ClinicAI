import os
import re
from datetime import datetime, timedelta, date as date_type
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES_BEFORE", "120"))  # 2 hours default
_DEMO_REMINDER_DELAY = os.getenv("DEMO_REMINDER_DELAY_MINUTES", "").strip()  # e.g. "2" for demo
CONSULTATION_TIMEOUT_MINUTES = int(os.getenv("CONSULTATION_TIMEOUT_MINUTES", "30"))
FOLLOWUP_DEFAULT_DAYS = int(os.getenv("FOLLOWUP_DEFAULT_DAYS", "2"))  # days if doctor doesn't mention
_DEMO_FOLLOWUP_DELAY = os.getenv("DEMO_FOLLOWUP_DELAY_MINUTES", "").strip()  # e.g. "3" for demo
_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")
_CLINIC_OPEN_HOUR = int(os.getenv("CLINIC_OPEN_HOUR", "9"))
_WEEKLY_INSIGHTS_HOUR = int(os.getenv("WEEKLY_INSIGHTS_HOUR", "8"))

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

scheduler = BackgroundScheduler(timezone=_TZ_NAME)


def _resolve_appointment_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse appointment date + time into a timezone-aware datetime."""
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


# ── Reminder job ───────────────────────────────────────────────────────────────

def _send_reminder_job(to: str, appointment_id: str, doctor: str, date_str: str, time_str: str):
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.store import mark_reminder_sent

    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    mins = REMINDER_MINUTES
    time_label = f"{mins // 60} hour{'s' if mins // 60 != 1 else ''}" if mins >= 60 else f"{mins} minute{'s' if mins != 1 else ''}"
    body = (
        f"⏰ *Reminder — {clinic_name}*\n\n"
        f"Your appointment with *{doctor}* is in {time_label}!\n"
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
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)

    # Demo mode: fire N minutes after approval, ignoring appointment time
    if _DEMO_REMINDER_DELAY:
        delay_mins = int(_DEMO_REMINDER_DELAY)
        fire_at = now + timedelta(minutes=delay_mins)
        print(f"[Reminder] DEMO MODE — firing in {delay_mins} min for {appointment_id}")
    else:
        appointment_dt = _resolve_appointment_datetime(date_str, time_str)

        if appointment_dt is None:
            print(f"[Reminder] Could not parse '{date_str} {time_str}' for {appointment_id} — skipping")
            return now

        fire_at = appointment_dt - timedelta(minutes=REMINDER_MINUTES)

        # If appointment is too soon (less than REMINDER_MINUTES away), fire in 30s
        if fire_at <= now:
            fire_at = now + timedelta(seconds=30)

    scheduler.add_job(
        func=_send_reminder_job,
        trigger=DateTrigger(run_date=fire_at),
        args=[to, appointment_id, doctor, date_str, time_str],
        id=f"reminder_{appointment_id}",
        replace_existing=True,
        misfire_grace_time=300,
    )

    print(
        f"[Reminder] Scheduled at {fire_at.strftime('%Y-%m-%d %H:%M')} "
        f"({REMINDER_MINUTES} min before appointment) — {appointment_id}"
    )
    return fire_at


# ── No-show recovery jobs ──────────────────────────────────────────────────────

_NO_SHOW_MSG_1 = (
    "👋 Hi! We noticed you may have missed your appointment today.\n\n"
    "If you'd like to reschedule, just reply *reschedule* and we'll get you a new slot right away.\n"
    "If you already visited, please ignore this message. 😊"
)

_NO_SHOW_MSG_2 = (
    "📋 Just a follow-up — we still have your appointment slot available for rescheduling.\n\n"
    "Reply *reschedule* to book a new time, or *cancel* if you no longer need the appointment.\n"
    "We're here to help! 🙏"
)


def _no_show_job(to: str, appointment_id: str, attempt: int):
    """Fires at +1hr (attempt=1) and +24hr (attempt=2) after missed appointment."""
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.store import get_last_active, get_appointment
    from zoneinfo import ZoneInfo

    appt = get_appointment(appointment_id)
    if not appt:
        print(f"[NoShow] Appointment {appointment_id} not found — skipping")
        return

    tz = ZoneInfo(_TZ_NAME)
    appt_dt = _resolve_appointment_datetime(appt.date_str, appt.time_str)
    if appt_dt is None:
        return

    last_active = get_last_active(to)
    if last_active and last_active > appt_dt:
        print(f"[NoShow] Patient {to} was active after appointment — not a no-show")
        return

    msg = _NO_SHOW_MSG_1 if attempt == 1 else _NO_SHOW_MSG_2
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    doctor = appt.doctor_name
    full_msg = (
        f"*{clinic_name}* — Missed Appointment\n\n"
        f"👨‍⚕️ Dr: *{doctor}* | 📅 {appt.date_str} | 🕐 {appt.time_str}\n\n"
        f"{msg}"
    )

    send_whatsapp_message_sync(to, full_msg)
    print(f"[NoShow] Sent attempt {attempt} for appointment {appointment_id} to {to}")


def schedule_no_show_check(
    to: str,
    appointment_id: str,
    date_str: str,
    time_str: str,
) -> None:
    """Schedule no-show recovery at appointment_time+1hr and +24hr."""
    appointment_dt = _resolve_appointment_datetime(date_str, time_str)
    if appointment_dt is None:
        print(f"[NoShow] Could not parse '{date_str} {time_str}' — skipping no-show setup")
        return

    check_1hr = appointment_dt + timedelta(hours=1)
    check_24hr = appointment_dt + timedelta(hours=24)

    scheduler.add_job(
        func=_no_show_job,
        trigger=DateTrigger(run_date=check_1hr),
        args=[to, appointment_id, 1],
        id=f"noshow_1hr_{appointment_id}",
        replace_existing=True,
        misfire_grace_time=600,
    )

    scheduler.add_job(
        func=_no_show_job,
        trigger=DateTrigger(run_date=check_24hr),
        args=[to, appointment_id, 2],
        id=f"noshow_24hr_{appointment_id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    print(
        f"[NoShow] Scheduled checks at +1hr ({check_1hr.strftime('%Y-%m-%d %H:%M')}) "
        f"and +24hr ({check_24hr.strftime('%Y-%m-%d %H:%M')}) for {appointment_id}"
    )


def cancel_no_show_jobs(appointment_id: str) -> None:
    for suffix in ("noshow_1hr", "noshow_24hr"):
        job_id = f"{suffix}_{appointment_id}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass


# ── Consultation timeout jobs ──────────────────────────────────────────────────

def _consultation_timeout_job(patient_number: str, consultation_id: str) -> None:
    """Fires after CONSULTATION_TIMEOUT_MINUTES of inactivity. Finalises the consultation."""
    import asyncio
    from app.services.store import get_consultation, save_consultation

    session = get_consultation(patient_number)
    if not session or not session.is_active or session.consultation_id != consultation_id:
        return

    session.ended_reason = "inactivity"
    session.is_active = False
    save_consultation(patient_number, session)

    print(f"[Consultation] Timeout fired for {patient_number} — finalising")
    try:
        from app.services.consultation_service import finalize_and_send
        asyncio.run(finalize_and_send(patient_number))
    except Exception as exc:
        print(f"[Consultation] Timeout finalisation failed for {patient_number}: {exc}")


def schedule_consultation_timeout(patient_number: str, consultation_id: str) -> None:
    """Schedule or reset the 30-min inactivity timer (replace_existing=True resets the clock)."""
    tz = ZoneInfo(_TZ_NAME)
    fire_at = datetime.now(tz) + timedelta(minutes=CONSULTATION_TIMEOUT_MINUTES)
    scheduler.add_job(
        func=_consultation_timeout_job,
        trigger=DateTrigger(run_date=fire_at),
        args=[patient_number, consultation_id],
        id=f"consult_timeout_{patient_number}",
        replace_existing=True,
        misfire_grace_time=300,
    )
    print(f"[Consultation] Timeout set for {patient_number} at {fire_at.strftime('%H:%M')} ({CONSULTATION_TIMEOUT_MINUTES} min)")


def reset_consultation_timeout(patient_number: str, consultation_id: str) -> None:
    """Reset the inactivity timer on any new message."""
    schedule_consultation_timeout(patient_number, consultation_id)


def cancel_consultation_timeout(patient_number: str) -> None:
    try:
        scheduler.remove_job(f"consult_timeout_{patient_number}")
        print(f"[Consultation] Timeout cancelled for {patient_number}")
    except Exception:
        pass


# ── After-hours flush jobs ─────────────────────────────────────────────────────

def _flush_afterhours_job(doctor_number: str) -> None:
    """Runs at clinic open time — re-injects queued after-hours messages into router_graph."""
    from app.services.store import get_after_hours_queue, clear_after_hours_queue

    queued = get_after_hours_queue(doctor_number)
    if not queued:
        return

    print(f"[AfterHours] Flushing {len(queued)} queued messages for doctor {doctor_number}")
    clear_after_hours_queue(doctor_number)

    try:
        from app.graph.router import router_graph
        for item in queued:
            from_number = item.get("from_number", "")
            body = item.get("body", "")
            if not from_number or not body:
                continue
            config = {"configurable": {"thread_id": from_number}}
            state_update = {"from_number": from_number, "incoming_message": body}
            try:
                router_graph.invoke(state_update, config=config)
            except Exception as msg_exc:
                print(f"[AfterHours] Failed to re-inject message from {from_number}: {msg_exc}")
    except Exception as exc:
        print(f"[AfterHours] Flush job failed: {exc}")


def schedule_afterhours_flush(doctor_number: str) -> None:
    """Register a daily cron job to flush the after-hours queue at clinic open time."""
    scheduler.add_job(
        func=_flush_afterhours_job,
        trigger=CronTrigger(hour=_CLINIC_OPEN_HOUR, minute=0, timezone=_TZ_NAME),
        args=[doctor_number],
        id=f"afterhours_flush_{doctor_number}",
        replace_existing=True,
    )
    print(f"[AfterHours] Flush scheduled daily at {_CLINIC_OPEN_HOUR:02d}:00 IST for {doctor_number}")


# ── Follow-up check-in jobs ────────────────────────────────────────────────────

def _strip_dr_prefix(name: str) -> str:
    """Remove leading 'Dr.' / 'Dr ' so templates can add it consistently."""
    import re as _re
    return _re.sub(r"(?i)^dr\.?\s*", "", name).strip()


def _followup_message_job(
    patient_number: str,
    patient_name: str,
    doctor_name: str,
    follow_up_questions: list,
) -> None:
    """Fires on the follow-up day — sends check-in questions to the patient."""
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.store import get_session, save_session
    from app.schemas import BookingSession

    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    name_greeting = f"Hi {patient_name}! 👋" if patient_name else "Hi! 👋"
    dr_name = _strip_dr_prefix(doctor_name)

    if follow_up_questions:
        questions_text = "\n".join(f"• {q}" for q in follow_up_questions)
        body = (
            f"{name_greeting}\n\n"
            f"*{clinic_name}* — Follow-up Check-in 🏥\n\n"
            f"*Dr. {dr_name}* wanted to check in on you today:\n\n"
            f"{questions_text}\n\n"
            "To book a follow-up appointment, just reply *book appointment*. 😊"
        )
    else:
        body = (
            f"{name_greeting}\n\n"
            f"*{clinic_name}* — Follow-up Check-in 🏥\n\n"
            f"*Dr. {dr_name}* wanted to check in on you. How are you feeling? 😊\n\n"
            "To book a follow-up appointment, just reply *book appointment*."
        )

    send_whatsapp_message_sync(patient_number, body)
    print(f"[FollowUp] Check-in sent to {patient_number}")

    try:
        session = get_session(patient_number) or BookingSession(from_number=patient_number)
        session.journey_state = "FOLLOW_UP_PENDING"
        session.state = "BOOKED"  # prevent booking flow from re-triggering
        save_session(session)
    except Exception as exc:
        print(f"[FollowUp] Could not update journey_state: {exc}")


def schedule_followup_message(
    patient_number: str,
    patient_name: str,
    doctor_name: str,
    follow_up_questions: list,
    follow_up_days: int | None,
) -> None:
    """Schedule the follow-up check-in message.

    Uses follow_up_days from the SOAP note (doctor-specified).
    Falls back to FOLLOWUP_DEFAULT_DAYS if the doctor didn't mention a date.
    In demo mode (DEMO_FOLLOWUP_DELAY_MINUTES set), fires after N minutes instead.
    """
    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)

    if _DEMO_FOLLOWUP_DELAY:
        delay_mins = int(_DEMO_FOLLOWUP_DELAY)
        fire_at = now + timedelta(minutes=delay_mins)
        print(f"[FollowUp] DEMO MODE — firing in {delay_mins} min for {patient_number}")
    else:
        days = follow_up_days if follow_up_days and follow_up_days > 0 else FOLLOWUP_DEFAULT_DAYS
        fire_at = now + timedelta(days=days)
        source = "doctor-specified" if follow_up_days else f"default ({FOLLOWUP_DEFAULT_DAYS}d)"
        print(f"[FollowUp] Scheduled in {days} day(s) ({source}) at {fire_at.strftime('%Y-%m-%d %H:%M')} for {patient_number}")

    scheduler.add_job(
        func=_followup_message_job,
        trigger=DateTrigger(run_date=fire_at),
        args=[patient_number, patient_name, doctor_name, follow_up_questions],
        id=f"followup_{patient_number}",
        replace_existing=True,
        misfire_grace_time=3600,
    )


# ── Weekly practice insights ───────────────────────────────────────────────────

def _weekly_insights_job(doctor_number: str) -> None:
    """Runs every Monday at WEEKLY_INSIGHTS_HOUR — sends 7-day practice summary to the doctor."""
    from app.services.store import all_appointments, get_last_active
    from app.services.whatsapp import send_whatsapp_message_sync
    from app.services.identity import find_doctor_name

    tz = ZoneInfo(_TZ_NAME)
    now = datetime.now(tz)
    week_ago = now - timedelta(days=7)
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")

    doctor_name = find_doctor_name(doctor_number) or doctor_number
    dr_label = _strip_dr_prefix(doctor_name)

    # Collect all appointments, filter to this doctor + booked in past 7 days
    all_appts_raw = all_appointments()
    recent: list[dict] = []
    for appt_data in all_appts_raw.values():
        if not isinstance(appt_data, dict):
            continue
        appt_doctor = appt_data.get("doctor_name", "")
        if not (
            appt_doctor.lower() in doctor_name.lower()
            or doctor_name.lower() in appt_doctor.lower()
        ):
            continue
        try:
            confirmed_raw = appt_data.get("confirmed_at")
            if not confirmed_raw:
                continue
            confirmed_dt = datetime.fromisoformat(str(confirmed_raw))
            if confirmed_dt.tzinfo is None:
                confirmed_dt = confirmed_dt.replace(tzinfo=tz)
            if confirmed_dt >= week_ago:
                recent.append(appt_data)
        except (ValueError, TypeError):
            continue

    total = len(recent)

    if total == 0:
        msg = (
            f"📊 *{clinic_name} — Weekly Practice Insights*\n"
            f"*Dr. {dr_label}* | {week_ago.strftime('%d %b')} – {now.strftime('%d %b %Y')}\n\n"
            "No appointments were booked this week.\n\n"
            "Have a great week! 🙏"
        )
        send_whatsapp_message_sync(doctor_number, msg)
        print(f"[WeeklyInsights] Sent (0 appointments) to {doctor_number}")
        return

    # Aggregate metrics
    day_counts: dict[str, int] = {}
    time_slots: dict[str, int] = {}
    symptom_counts: dict[str, int] = {}
    past_count = 0
    no_show_count = 0

    for appt in recent:
        appt_dt = _resolve_appointment_datetime(
            appt.get("date_str", ""), appt.get("time_str", "")
        )

        if appt_dt:
            # Day distribution
            day_name = appt_dt.strftime("%A")
            day_counts[day_name] = day_counts.get(day_name, 0) + 1

            # Time-of-day distribution
            hour = appt_dt.hour
            if hour < 12:
                slot = "Morning (before 12pm)"
            elif hour < 17:
                slot = "Afternoon (12–5pm)"
            else:
                slot = "Evening (after 5pm)"
            time_slots[slot] = time_slots.get(slot, 0) + 1

            # Past appointment analysis
            # Add 90 min buffer so appointment slot has clearly passed
            if appt_dt + timedelta(minutes=90) < now:
                past_count += 1
                # No-show proxy: appointment passed + reminder was sent (reminder fired
                # ~2h before, so doctor's reminder system was active) but patient was
                # NOT active after the appointment time.
                from_number = appt.get("from_number", "")
                if appt.get("reminder_sent") and from_number:
                    last_active = get_last_active(from_number)
                    if last_active is None or last_active < appt_dt:
                        no_show_count += 1

        # Symptom aggregation
        for sym in appt.get("symptoms") or []:
            if sym:
                sym_clean = sym.strip()
                if sym_clean:
                    symptom_counts[sym_clean] = symptom_counts.get(sym_clean, 0) + 1

    # Build WhatsApp message
    lines = [
        f"📊 *{clinic_name} — Weekly Practice Insights*",
        f"*Dr. {dr_label}* | {week_ago.strftime('%d %b')} – {now.strftime('%d %b %Y')}",
        "",
        f"📅 *Total appointments booked:* {total}",
    ]

    if past_count > 0:
        upcoming = total - past_count
        lines.append(f"✅ *Slots already passed:* {past_count}" + (f" | 📆 Upcoming: {upcoming}" if upcoming > 0 else ""))

    if no_show_count > 0:
        no_show_pct = round(no_show_count / past_count * 100) if past_count else 0
        lines.append(f"❌ *Estimated no-shows:* {no_show_count} ({no_show_pct}% of past slots)")

    if day_counts:
        busiest_day = max(day_counts, key=day_counts.get)
        lines.append(f"🗓️ *Busiest day:* {busiest_day} ({day_counts[busiest_day]} appointments)")

    if time_slots:
        busiest_slot = max(time_slots, key=time_slots.get)
        lines.append(f"⏰ *Busiest time:* {busiest_slot}")

    if symptom_counts:
        top3 = sorted(symptom_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        sym_text = ", ".join(f"{s} ({n})" for s, n in top3)
        lines.append(f"🤒 *Top complaints:* {sym_text}")

    lines += ["", "Have a great week! 🙏"]

    msg = "\n".join(lines)
    send_whatsapp_message_sync(doctor_number, msg)
    print(f"[WeeklyInsights] Sent to {doctor_number} — {total} appointments, {no_show_count} no-shows")


def schedule_weekly_insights(doctor_number: str) -> None:
    """Register weekly insights cron job — every Monday at WEEKLY_INSIGHTS_HOUR IST."""
    scheduler.add_job(
        func=_weekly_insights_job,
        trigger=CronTrigger(
            day_of_week="mon",
            hour=_WEEKLY_INSIGHTS_HOUR,
            minute=0,
            timezone=_TZ_NAME,
        ),
        args=[doctor_number],
        id=f"weekly_insights_{doctor_number}",
        replace_existing=True,
    )
    print(
        f"[WeeklyInsights] Scheduled every Monday at "
        f"{_WEEKLY_INSIGHTS_HOUR:02d}:00 IST for {doctor_number}"
    )
