"""
AfterHoursAgent — queues messages received outside clinic hours and sends an ack.

Clinic hours are controlled by CLINIC_OPEN_HOUR / CLINIC_CLOSE_HOUR env vars.
Queued messages are flushed back into the router at open time by a daily
APScheduler cron job registered via schedule_afterhours_flush().
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()

CLINIC_OPEN_HOUR  = int(os.getenv("CLINIC_OPEN_HOUR",  "9"))
CLINIC_CLOSE_HOUR = int(os.getenv("CLINIC_CLOSE_HOUR", "20"))
_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")


def is_clinic_open() -> bool:
    now = datetime.now(ZoneInfo(_TZ_NAME))
    return CLINIC_OPEN_HOUR <= now.hour < CLINIC_CLOSE_HOUR


def queue_node(state: BookingState) -> dict:
    from app.services.store import queue_after_hours_message
    from app.services.identity import all_doctor_numbers

    from_number = state["from_number"]
    message = state["incoming_message"]
    doctor_numbers = all_doctor_numbers()
    doctor_number = doctor_numbers[0] if doctor_numbers else "unknown"

    queue_after_hours_message(doctor_number, from_number, message)
    print(f"[AfterHours] Queued message from {from_number} for doctor {doctor_number}")

    return {
        "pipeline_log": [f"after_hours_agent: queued message from {from_number}"],
    }


def ack_node(state: BookingState) -> dict:
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    open_str = f"{CLINIC_OPEN_HOUR % 12 or 12} {'AM' if CLINIC_OPEN_HOUR < 12 else 'PM'}"
    close_str = f"{CLINIC_CLOSE_HOUR % 12 or 12} {'AM' if CLINIC_CLOSE_HOUR < 12 else 'PM'}"

    return {
        "reply_message": (
            f"🌙 *{clinic_name}* is currently closed.\n\n"
            f"Our hours are *{open_str} – {close_str} IST* (Mon–Sat).\n\n"
            "We've received your message and will respond first thing when we open. 🙏\n"
            "_If this is an emergency, please call *112* immediately._"
        ),
        "pipeline_log": ["after_hours_agent: ack sent"],
    }


def build_after_hours_graph():
    g = StateGraph(BookingState)
    g.add_node("queue_node", queue_node)
    g.add_node("ack_node", ack_node)
    g.add_edge(START, "queue_node")
    g.add_edge("queue_node", "ack_node")
    g.add_edge("ack_node", END)
    return g.compile()


after_hours_agent_graph = build_after_hours_graph()
