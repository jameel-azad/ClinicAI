"""
FollowUpAgent — handles followup_query and prescription_request intents.

If the patient is POST_CONSULT, acknowledges and tells them to check with doctor.
Otherwise, directs them to book an appointment.
"""

import os

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()


def followup_node(state: BookingState) -> dict:
    from app.services.store import get_latest_appointment_for_patient

    from_number = state["from_number"]
    intent = state.get("intent", "general_query")
    session_dict = state.get("session") or {}
    journey_state = session_dict.get("journey_state", "NEW_PATIENT")
    bot_response = state.get("bot_response")

    if journey_state == "POST_CONSULT":
        return {
            "reply_message": (
                "📋 Your recent consultation has been recorded.\n\n"
                "The doctor will send prescriptions or follow-up instructions shortly via WhatsApp. "
                "If you have an urgent query, please reply and the clinic will get back to you. 🙏"
            ),
            "pipeline_log": ["followup_agent: POST_CONSULT response sent"],
        }

    if intent == "prescription_request":
        appt = get_latest_appointment_for_patient(from_number)
        if appt:
            return {
                "reply_message": (
                    f"We'll note your prescription request for *{appt.doctor_name}*. "
                    "The doctor will review and send it to you shortly. 🙏\n\n"
                    "If urgent, please call the clinic directly."
                ),
                "pipeline_log": ["followup_agent: prescription request acknowledged"],
            }

    if bot_response:
        return {
            "reply_message": bot_response,
            "pipeline_log": ["followup_agent: used LLM bot_response"],
        }

    return {
        "reply_message": (
            "For follow-up queries or prescriptions, please book an appointment with the doctor.\n\n"
            "Would you like to book one now? Just say *book appointment* and we'll get started. 😊"
        ),
        "pipeline_log": ["followup_agent: default response — prompted to book"],
    }


def build_followup_graph():
    g = StateGraph(BookingState)
    g.add_node("followup_node", followup_node)
    g.add_edge(START, "followup_node")
    g.add_edge("followup_node", END)
    return g.compile()


followup_agent_graph = build_followup_graph()
