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

from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingSession, BookingState
from app.graph.classifier import classifier_graph
from app.graph.agents.after_hours_agent import after_hours_agent_graph, is_clinic_open
from app.graph.agents.booking_agent import booking_agent_graph
from app.graph.agents.emergency_agent import emergency_agent_graph
from app.graph.agents.followup_agent import followup_agent_graph
from app.graph.agents.lab_agent import lab_agent_graph

load_dotenv()

EMPTY_ENTITIES = {
    "patient_name": None, "doctor_name": None, "requested_date": None,
    "requested_time": None, "symptoms_mentioned": None, "medication_mentioned": None,
}


# ══════════════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════════════

def after_hours_check_node(state: BookingState) -> dict:
    """Pre-check: if clinic is closed, queue message and return ack. Sets reply_message."""
    if is_clinic_open():
        return {"pipeline_log": ["router: clinic open — continuing"]}

    result = after_hours_agent_graph.invoke({
        "from_number": state["from_number"],
        "incoming_message": state["incoming_message"],
        "intent": "general_query",
        "confidence": 0.0,
        "extracted_entities": EMPTY_ENTITIES.copy(),
        "bot_response": None,
        "session": None,
        "is_new_session": False,
        "current_booking_state": "GREETING",
        "reply_message": "",
        "appointment_id": None,
        "is_off_topic": False,
        "pipeline_log": [],
    })
    return {
        "reply_message": result.get("reply_message", ""),
        "pipeline_log": ["router: after-hours — queued and acked"],
    }


def intent_node(state: BookingState) -> dict:
    from app.services.store import get_session, update_last_active

    from_number = state["from_number"]
    message = state["incoming_message"]

    update_last_active(from_number)

    context_message = None
    session_dict = state.get("session")
    if not session_dict:
        redis_session = get_session(from_number)
        if redis_session:
            session_dict = redis_session.model_dump()
    if session_dict:
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

    existing = state.get("session")
    if not existing:
        redis_session = get_session(state["from_number"])
        if redis_session:
            existing = redis_session.model_dump()

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
        new_session = BookingSession(from_number=state["from_number"])
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

def route_after_hours(state: BookingState) -> Literal["intent_node", "__end__"]:
    """If after_hours_check set a reply_message, we're done (after-hours ack sent)."""
    if state.get("reply_message"):
        return END
    return "intent_node"


def route_after_session(
    state: BookingState,
) -> Literal[
    "emergency_dispatch_node",
    "consultation_dispatch_node",
    "lab_dispatch_node",
    "followup_dispatch_node",
    "booking_dispatch_node",
]:
    intent = state.get("intent", "general_query")
    session_dict = state.get("session") or {}
    journey_state = session_dict.get("journey_state", "NEW_PATIENT")

    if intent == "emergency":
        return "emergency_dispatch_node"

    if journey_state == "CONSULTATION_ACTIVE" or intent == "consultation_message":
        return "consultation_dispatch_node"

    if intent == "lab_report_share":
        return "lab_dispatch_node"

    if intent in ("followup_query", "prescription_request"):
        return "followup_dispatch_node"

    return "booking_dispatch_node"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_router_graph():
    g = StateGraph(BookingState)

    g.add_node("after_hours_check_node", after_hours_check_node)
    g.add_node("intent_node", intent_node)
    g.add_node("session_node", session_node)
    g.add_node("booking_dispatch_node", booking_dispatch_node)
    g.add_node("consultation_dispatch_node", consultation_dispatch_node)
    g.add_node("emergency_dispatch_node", emergency_dispatch_node)
    g.add_node("lab_dispatch_node", lab_dispatch_node)
    g.add_node("followup_dispatch_node", followup_dispatch_node)

    g.add_edge(START, "after_hours_check_node")
    g.add_conditional_edges(
        "after_hours_check_node",
        route_after_hours,
        {"intent_node": "intent_node", END: END},
    )
    g.add_edge("intent_node", "session_node")
    g.add_conditional_edges(
        "session_node",
        route_after_session,
        {
            "emergency_dispatch_node": "emergency_dispatch_node",
            "consultation_dispatch_node": "consultation_dispatch_node",
            "lab_dispatch_node": "lab_dispatch_node",
            "followup_dispatch_node": "followup_dispatch_node",
            "booking_dispatch_node": "booking_dispatch_node",
        },
    )

    g.add_edge("emergency_dispatch_node", END)
    g.add_edge("consultation_dispatch_node", END)
    g.add_edge("lab_dispatch_node", END)
    g.add_edge("followup_dispatch_node", END)
    g.add_edge("booking_dispatch_node", END)

    memory = MemorySaver()
    return g.compile(checkpointer=memory)


router_graph = build_router_graph()
