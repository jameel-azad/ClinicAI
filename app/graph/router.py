"""
RouterAgent — the top-level LangGraph orchestrator.

Flow:
  START
    → after_hours_check_node  (if closed: queue + ack → END)
    → intent_node             (classifier_graph)
    → session_node            (load/create BookingSession from Redis)
    → dispatch to sub-agent graph (inline as a node that calls the agent graph)

Sub-agents:
  booking_agent   — appointment_book/cancel/reschedule/status, general_query
  consultation_agent — consultation_message + CONSULTATION_ACTIVE state
  lab_agent       — lab_report_share intent (no PDF attached)
  followup_agent  — followup_query, prescription_request
  after_hours_agent — outside 9am–8pm IST
  emergency_agent — emergency intent
"""

import logging
import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingSession, BookingState
from app.graph.classifier import classifier_graph
from app.graph.agents.after_hours_agent import (
    after_hours_agent_graph, is_clinic_open, CLINIC_OPEN_HOUR, CLINIC_CLOSE_HOUR,
)
from app.graph.agents.booking_agent import booking_agent_graph
from app.graph.agents.emergency_agent import emergency_agent_graph
from app.graph.agents.followup_agent import followup_agent_graph
from app.graph.agents.lab_agent import lab_agent_graph

load_dotenv()

_log = logging.getLogger(__name__)


def _build_checkpointer():
    """Return a Redis checkpointer, falling back to MemorySaver if Redis is unavailable."""
    try:
        from langgraph.checkpoint.redis import RedisSaver
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        cp = RedisSaver(redis_url=redis_url)
        cp.setup()
        _log.info("[router] LangGraph checkpointer: Redis (%s)", redis_url.split("@")[-1] if "@" in redis_url else redis_url)
        return cp
    except Exception as exc:
        from langgraph.checkpoint.memory import MemorySaver
        _log.warning(
            "[router] Redis checkpointer unavailable (%s) — "
            "falling back to MemorySaver (graph state lost on restart).", exc,
        )
        return MemorySaver()


EMPTY_ENTITIES = {
    "patient_name": None, "doctor_name": None, "requested_date": None,
    "requested_time": None, "symptoms_mentioned": None, "medication_mentioned": None,
}


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def after_hours_check_node(state: BookingState) -> dict:
    """Detect whether the clinic is closed and flag it on the state.

    The AI now stays fully available after hours (booking, FAQ, status, lab,
    emergency). Only doctor-facing consultation messages are deferred later in
    route_after_session — see after_hours_dispatch_node.
    """
    open_hour  = state.get("clinic_open_hour")  or CLINIC_OPEN_HOUR
    close_hour = state.get("clinic_close_hour") or CLINIC_CLOSE_HOUR
    closed = not is_clinic_open(open_hour, close_hour)
    return {
        "clinic_closed": closed,
        # Reset any stale reply_message from the checkpoint
        "reply_message": "",
        "pipeline_log": [f"router: clinic {'closed — self-service on' if closed else 'open'}"],
    }


def after_hours_dispatch_node(state: BookingState) -> dict:
    """Queue a doctor-facing message for the next working day and send the closed ack."""
    result = after_hours_agent_graph.invoke({
        "from_number": state["from_number"],
        "incoming_message": state["incoming_message"],
        "clinic_id": state.get("clinic_id"),
        "clinic_twilio_number": state.get("clinic_twilio_number"),
        "clinic_open_hour": state.get("clinic_open_hour") or CLINIC_OPEN_HOUR,
        "clinic_close_hour": state.get("clinic_close_hour") or CLINIC_CLOSE_HOUR,
        "intent": state.get("intent", "general_query"),
        "confidence": state.get("confidence", 0.0),
        "extracted_entities": state.get("extracted_entities", EMPTY_ENTITIES.copy()),
        "bot_response": None,
        "session": state.get("session"),
        "is_new_session": False,
        "current_booking_state": state.get("current_booking_state", "GREETING"),
        "reply_message": "",
        "appointment_id": None,
        "is_off_topic": False,
        "pipeline_log": [],
    })
    return {
        "reply_message": result.get("reply_message", ""),
        "pipeline_log": ["router: after-hours — doctor-facing message queued and acked"],
    }


def intent_node(state: BookingState) -> dict:
    from app.services.store import get_session, update_last_active

    from_number = state["from_number"]
    message = state["incoming_message"]
    clinic_id = state.get("clinic_id")

    update_last_active(from_number)

    context_message = None
    session_dict = state.get("session")

    # last_bot_response is persisted to Redis after each reply but NOT written to
    # the LangGraph checkpoint, so always read from Redis to get fresh context.
    # This ensures the classifier knows what the bot last said (e.g. "Could you
    # share the patient's name?") so it can correctly extract short replies like "Amit".
    redis_session = get_session(from_number, clinic_id=clinic_id)

    if not session_dict:
        if redis_session:
            session_dict = redis_session.model_dump()

    if redis_session and redis_session.last_bot_response:
        context_message = redis_session.last_bot_response
    elif session_dict:
        context_message = session_dict.get("last_bot_response")

    initial = {
        "from_number": from_number,
        "raw_message": message,
        "context_message": context_message,
        "is_valid": False, "validation_error": None,
        "processed_message": "", "intent": "general_query",
        "confidence": 0.0, "entities": {}, "bot_response": None,
        "llm_error": None, "all_intents": [], "is_multi_intent": False,
        "is_injection": False, "injection_reason": None,
        "is_emergency": False, "pipeline_log": [],
        # Per-clinic LLM config forwarded from BookingState
        "llm_vendor":  state.get("llm_vendor", "groq"),
        "llm_model":   state.get("llm_model",  os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
        "llm_enc_key": state.get("llm_enc_key"),
    }
    result = classifier_graph.invoke(initial)

    return {
        "intent": result["intent"],
        "confidence": result["confidence"],
        "extracted_entities": result.get("entities", {}),
        "bot_response": result.get("bot_response"),
        "pipeline_log": [f"router/intent_node: intent={result['intent']} conf={result['confidence']:.2f}"],
    }


def session_node(state: BookingState) -> dict:
    from app.services.store import get_session, save_session

    clinic_id = state.get("clinic_id")

    # Prefer the graph checkpoint for booking flow state (keeps in-progress
    # bookings intact across messages). But always pull journey_state from Redis
    # because background jobs (scheduler) write there and bypass the checkpoint.
    existing = state.get("session")
    checkpoint_booking_state = state.get("current_booking_state")
    if not existing:
        # Don't fall back to the Redis custom session when the LangGraph checkpoint
        # has deliberately reset the session (checkpoint has session=None AND
        # current_booking_state="GREETING" — the fingerprint of a cancel/reject reset).
        # For a completely new user the checkpoint has no booking state (None), so the
        # Redis fallback is still used to restore any mid-booking session from other workers.
        if checkpoint_booking_state != "GREETING":
            redis_session = get_session(state["from_number"], clinic_id=clinic_id)
            if redis_session:
                existing = redis_session.model_dump()
    else:
        redis_session = get_session(state["from_number"], clinic_id=clinic_id)
        if redis_session and redis_session.journey_state != existing.get("journey_state"):
            existing = dict(existing)
            existing["journey_state"] = redis_session.journey_state

    if existing:
        try:
            save_session(BookingSession(**existing))
        except Exception:
            pass
        return {
            "session": existing,
            "is_new_session": False,
            "current_booking_state": existing.get("state", "GREETING"),
            "pipeline_log": [f"router/session_node: loaded state={existing.get('state')}"],
        }
    else:
        new_session = BookingSession(
            from_number=state["from_number"],
            clinic_id=clinic_id,
            clinic_twilio_number=state.get("clinic_twilio_number"),
        )
        save_session(new_session)
        return {
            "session": new_session.model_dump(),
            "is_new_session": True,
            "current_booking_state": "GREETING",
            "pipeline_log": ["router/session_node: new session created"],
        }


def _invoke_sub_agent(graph, state: BookingState) -> dict:
    """Invoke a sub-agent graph and merge its output into the router state."""
    sub_input = {
        "from_number": state["from_number"],
        "incoming_message": state["incoming_message"],
        "messages": state.get("messages") or [],
        "intent": state.get("intent", "general_query"),
        "confidence": state.get("confidence", 0.0),
        "extracted_entities": state.get("extracted_entities", {}),
        "bot_response": state.get("bot_response"),
        "session": state.get("session"),
        "is_new_session": state.get("is_new_session", False),
        "current_booking_state": state.get("current_booking_state", "GREETING"),
        "reply_message": "",
        "appointment_id": state.get("appointment_id"),
        "is_off_topic": False,
        "pipeline_log": [],
        # Clinic + LLM context — sub-agents need these to use clinic-specific keys
        "clinic_id":            state.get("clinic_id"),
        "clinic_twilio_number": state.get("clinic_twilio_number"),
        "llm_vendor":  state.get("llm_vendor", "groq"),
        "llm_model":   state.get("llm_model",  os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
        "llm_enc_key": state.get("llm_enc_key"),
        "stt_model":   state.get("stt_model"),
        "stt_enc_key": state.get("stt_enc_key"),
    }
    return graph.invoke(sub_input)


def booking_dispatch_node(state: BookingState) -> dict:
    result = _invoke_sub_agent(booking_agent_graph, state)
    return {
        "reply_message": result.get("reply_message", ""),
        "session": result.get("session", state.get("session")),
        "current_booking_state": result.get("current_booking_state", state.get("current_booking_state")),
        "appointment_id": result.get("appointment_id"),
        "is_off_topic": result.get("is_off_topic", False),
        "pipeline_log": result.get("pipeline_log", []),
    }


def consultation_dispatch_node(state: BookingState) -> dict:
    from app.graph.agents.consultation_agent import consultation_agent_graph
    result = _invoke_sub_agent(consultation_agent_graph, state)
    return {
        "reply_message": result.get("reply_message", ""),
        "session": result.get("session", state.get("session")),
        "pipeline_log": result.get("pipeline_log", []),
    }


def emergency_dispatch_node(state: BookingState) -> dict:
    result = _invoke_sub_agent(emergency_agent_graph, state)
    return {
        "reply_message": result.get("reply_message", ""),
        "session": None,
        "current_booking_state": "GREETING",
        "pipeline_log": result.get("pipeline_log", []),
    }


def lab_dispatch_node(state: BookingState) -> dict:
    result = _invoke_sub_agent(lab_agent_graph, state)
    return {
        "reply_message": result.get("reply_message", ""),
        "session": result.get("session", state.get("session")),
        "pipeline_log": result.get("pipeline_log", []),
    }


def followup_dispatch_node(state: BookingState) -> dict:
    result = _invoke_sub_agent(followup_agent_graph, state)
    return {
        "reply_message": result.get("reply_message", ""),
        "pipeline_log": result.get("pipeline_log", []),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def route_after_session(
    state: BookingState,
) -> Literal[
    "emergency_dispatch_node",
    "consultation_dispatch_node",
    "after_hours_dispatch_node",
    "lab_dispatch_node",
    "followup_dispatch_node",
    "booking_dispatch_node",
]:
    intent = state.get("intent", "general_query")
    session_dict = state.get("session") or {}
    journey_state = session_dict.get("journey_state", "NEW_PATIENT")

    if intent == "emergency":
        return "emergency_dispatch_node"

    # Guard consultation routing — only route to consultation_agent for genuinely active
    # sessions. POST_CONSULT and FOLLOW_UP_PENDING patients asking medical questions
    # belong in followup_agent (which handles LLM-answer-or-escalate), not a new session.
    needs_doctor = journey_state == "CONSULTATION_ACTIVE" or (
        intent == "consultation_message"
        and journey_state not in (
            "NEW_PATIENT", "BOOKING_IN_PROGRESS", "POST_CONSULT", "FOLLOW_UP_PENDING"
        )
    )

    # After hours, only doctor-facing consultation messages are deferred & queued.
    # Everything else (booking, status, lab, FAQ, emergency) stays self-service 24/7.
    if needs_doctor and state.get("clinic_closed"):
        return "after_hours_dispatch_node"

    if needs_doctor:
        return "consultation_dispatch_node"

    if intent == "lab_report_share":
        return "lab_dispatch_node"

    # If the patient is mid-way through the lab report collection flow, route
    # back to lab_dispatch_node even when the classifier returned a different
    # intent (e.g. "general_query" when the user replied with just a name or
    # "share with dr X" which can trip the injection guard).
    if session_dict.get("state") in ("LAB_COLLECTING", "LAB_PDF_REQUESTED"):
        return "lab_dispatch_node"

    # If the patient is mid-booking, followup/prescription intents must not hijack
    # the booking flow — route them back to booking_dispatch_node instead.
    if intent in ("followup_query", "prescription_request"):
        if session_dict.get("state") in (
            "COLLECTING_INFO", "COLLECT_DOCTOR_PREFERENCE", "CONFIRM_SLOT"
        ):
            return "booking_dispatch_node"
        return "followup_dispatch_node"

    # Bug 2: appointment management intents must reach booking_agent even for
    # POST_CONSULT / FOLLOW_UP_PENDING patients — explicit intent wins over journey state
    if intent in ("appointment_cancel", "appointment_reschedule",
                  "appointment_status", "appointment_book"):
        return "booking_dispatch_node"

    # Any other message from a POST_CONSULT or FOLLOW_UP_PENDING patient goes to followup
    if journey_state in ("POST_CONSULT", "FOLLOW_UP_PENDING"):
        return "followup_dispatch_node"

    return "booking_dispatch_node"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_router_graph(checkpointer=None):
    g = StateGraph(BookingState)

    g.add_node("after_hours_check_node", after_hours_check_node)
    g.add_node("intent_node", intent_node)
    g.add_node("session_node", session_node)
    g.add_node("booking_dispatch_node", booking_dispatch_node)
    g.add_node("consultation_dispatch_node", consultation_dispatch_node)
    g.add_node("emergency_dispatch_node", emergency_dispatch_node)
    g.add_node("lab_dispatch_node", lab_dispatch_node)
    g.add_node("followup_dispatch_node", followup_dispatch_node)
    g.add_node("after_hours_dispatch_node", after_hours_dispatch_node)

    g.add_edge(START, "after_hours_check_node")
    g.add_edge("after_hours_check_node", "intent_node")
    g.add_edge("intent_node", "session_node")
    g.add_conditional_edges(
        "session_node",
        route_after_session,
        {
            "emergency_dispatch_node": "emergency_dispatch_node",
            "consultation_dispatch_node": "consultation_dispatch_node",
            "after_hours_dispatch_node": "after_hours_dispatch_node",
            "lab_dispatch_node": "lab_dispatch_node",
            "followup_dispatch_node": "followup_dispatch_node",
            "booking_dispatch_node": "booking_dispatch_node",
        },
    )

    g.add_edge("emergency_dispatch_node", END)
    g.add_edge("consultation_dispatch_node", END)
    g.add_edge("after_hours_dispatch_node", END)
    g.add_edge("lab_dispatch_node", END)
    g.add_edge("followup_dispatch_node", END)
    g.add_edge("booking_dispatch_node", END)

    return g.compile(checkpointer=checkpointer)


_checkpointer = _build_checkpointer()
router_graph = build_router_graph(_checkpointer)
