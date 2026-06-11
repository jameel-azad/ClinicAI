import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

_log = logging.getLogger(__name__)
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()

CLINIC_OPEN_HOUR  = int(os.getenv("CLINIC_OPEN_HOUR",  "9"))
CLINIC_CLOSE_HOUR = int(os.getenv("CLINIC_CLOSE_HOUR", "20"))
_TZ_NAME = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Asia/Kolkata")


def is_clinic_open(open_hour: int = CLINIC_OPEN_HOUR, close_hour: int = CLINIC_CLOSE_HOUR) -> bool:
    now = datetime.now(ZoneInfo(_TZ_NAME))
    return open_hour <= now.hour < close_hour


def queue_node(state: BookingState) -> dict:
    from app.services.store import (
        queue_after_hours_message,
        get_appointments_by_number,
    )
    from app.services.identity import (
        find_doctor_number, all_doctor_numbers, normalize_whatsapp_number,
    )

    from_number = state["from_number"]
    message = state["incoming_message"]

    # Capture clinic context so the flush job can re-inject with the right hours
    clinic_meta = {
        "clinic_id": state.get("clinic_id"),
        "clinic_open_hour": state.get("clinic_open_hour") or CLINIC_OPEN_HOUR,
        "clinic_close_hour": state.get("clinic_close_hour") or CLINIC_CLOSE_HOUR,
    }

    # Find patient's assigned doctor from their most recent appointment
    assigned_doctor = None
    try:
        appts = get_appointments_by_number(normalize_whatsapp_number(from_number))
        if appts:
            most_recent = max(appts, key=lambda a: a.confirmed_at)
            assigned_doctor = find_doctor_number(most_recent.doctor_name)
    except Exception:
        pass

    if assigned_doctor:
        queue_after_hours_message(assigned_doctor, from_number, message, metadata=clinic_meta)
        _log.info("[AfterHours] Queued message from %s for assigned doctor %s", from_number, assigned_doctor)
    else:
        # No appointment context — queue to all doctors so any can respond
        all_nums = all_doctor_numbers()
        for doc_num in all_nums:
            queue_after_hours_message(doc_num, from_number, message, metadata=clinic_meta)
        _log.info("[AfterHours] No appointment found — queued message from %s to all %d doctor(s)", from_number, len(all_nums))

    return {
        "pipeline_log": [f"after_hours_agent: queued message from {from_number}"],
    }


def ack_node(state: BookingState) -> dict:
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")
    open_hour  = state.get("clinic_open_hour")  or CLINIC_OPEN_HOUR
    close_hour = state.get("clinic_close_hour") or CLINIC_CLOSE_HOUR
    open_str  = f"{open_hour  % 12 or 12} {'AM' if open_hour  < 12 else 'PM'}"
    close_str = f"{close_hour % 12 or 12} {'AM' if close_hour < 12 else 'PM'}"

    return {
        "reply_message": (
            f"🌙 *{clinic_name}* is currently closed.\n\n"
            f"Our hours are *{open_str} – {close_str}* (Mon–Sat).\n\n"
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
