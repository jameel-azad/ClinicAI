"""
EmergencyAgent — responds to emergency intent.

Sends "Call 112" to patient AND notifies all configured doctors.
Clears the patient session so they start fresh afterwards.
"""

import os

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()

MSG_EMERGENCY = (
    "🚨 *This sounds like an emergency.*\n\n"
    "Please call *112* (India emergency) or go to the nearest hospital immediately.\n"
    "If you need the clinic's emergency line, call us directly."
)


def emergency_node(state: BookingState) -> dict:
    from app.services.identity import all_doctor_numbers
    from app.services.whatsapp import send_whatsapp_message_sync

    from_number = state["from_number"]
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")

    for doctor_number in all_doctor_numbers():
        send_whatsapp_message_sync(
            doctor_number,
            f"🚨 *{clinic_name} — EMERGENCY ALERT*\n\n"
            f"Patient *{from_number}* has reported a medical emergency on WhatsApp.\n"
            "Please respond immediately or call 112.",
        )

    return {
        "reply_message": MSG_EMERGENCY,
        "is_off_topic": False,
        "session": None,
        "current_booking_state": "GREETING",
        "pipeline_log": ["emergency_agent: ⚠ emergency response sent, doctors notified, session cleared"],
    }


def build_emergency_graph():
    g = StateGraph(BookingState)
    g.add_node("emergency_node", emergency_node)
    g.add_edge(START, "emergency_node")
    g.add_edge("emergency_node", END)
    return g.compile()


emergency_agent_graph = build_emergency_graph()
