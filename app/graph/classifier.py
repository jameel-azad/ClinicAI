import json
import os
import re
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

from app.schemas import ClassifierState
from app.prompts import CLASSIFIER_SYSTEM_PROMPT, CLASSIFIER_FEW_SHOT

load_dotenv()

# ── LLM clients ───────────────────────────────────────────────────────────────

def _get_groq_llm() -> ChatGroq:
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0.1,
        max_tokens=512,
    )


def _get_gemini_llm():
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=key,
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=0.1,
            max_tokens=512,
            max_retries=1,
        )
    except ImportError:
        return None


# ── Shared helpers ─────────────────────────────────────────────────────────────

VALID_INTENTS = {
    "appointment_book",
    "appointment_cancel",
    "appointment_reschedule",
    "appointment_status",
    "followup_query",
    "lab_report_share",
    "prescription_request",
    "general_query",
    "emergency",
    "consultation_message",
}

EMPTY_ENTITIES = {
    "patient_name": None,
    "doctor_name": None,
    "requested_date": None,
    "requested_time": None,
    "symptoms_mentioned": None,
    "medication_mentioned": None,
}




def _parse_llm_output(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Cannot parse JSON from: {raw[:300]}")


def _sanitise_single_intent(result: dict) -> dict:
    intent = result.get("intent", "general_query")
    if intent not in VALID_INTENTS:
        intent = "general_query"

    confidence = float(result.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    raw_entities = result.get("entities") or {}
    entities = {
        "patient_name": raw_entities.get("patient_name"),
        "doctor_name": raw_entities.get("doctor_name"),
        "requested_date": raw_entities.get("requested_date"),
        "requested_time": raw_entities.get("requested_time"),
        "symptoms_mentioned": raw_entities.get("symptoms_mentioned"),
        "medication_mentioned": raw_entities.get("medication_mentioned"),
    }

    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "bot_response": result.get("bot_response"),
    }


def _sanitise_multi_result(parsed: dict) -> list[dict]:
    # New format: {"intents": [...]}
    if "intents" in parsed and isinstance(parsed["intents"], list):
        intents = [_sanitise_single_intent(i) for i in parsed["intents"]]
    # Legacy fallback: {"intent": "...", "confidence": ...}
    elif "intent" in parsed:
        intents = [_sanitise_single_intent(parsed)]
    else:
        intents = [_sanitise_single_intent({})]

    # Sort by confidence descending (primary = highest)
    intents.sort(key=lambda x: x["confidence"], reverse=True)
    return intents


def _call_llm(llm, messages_history: list, context_message: str | None = None) -> list[dict]:
    """Calls any LangChain-compatible LLM and returns a list of sanitised intent dicts."""
    system_content = CLASSIFIER_SYSTEM_PROMPT
    if context_message:
        system_content += f'\n\nPrevious bot message: "{context_message[:300]}"'
    system_content += "\n\n" + CLASSIFIER_FEW_SHOT

    system_msg = SystemMessage(content=system_content)
    llm_messages = [system_msg] + messages_history

    response = llm.invoke(llm_messages)
    raw = response.content
    parsed = _parse_llm_output(raw)
    return _sanitise_multi_result(parsed)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH NODES
# Each node is a plain Python function.
# Signature: (state: ClassifierState) -> dict
# Return only the keys you're updating — LangGraph merges the rest.
# ══════════════════════════════════════════════════════════════════════════════

def validate_node(state: ClassifierState) -> dict:
    """
    NODE 1 — Validate
    Checks the incoming message is non-empty and meaningful.
    Sets is_valid=True/False and validation_error if applicable.
    """
    message = state.get("raw_message", "").strip()

    if not message:
        return {
            "is_valid": False,
            "validation_error": "Message cannot be empty",
            "processed_message": "",
            "pipeline_log": ["validate_node: FAILED — empty message"],
        }

    if len(message) > 2000:
        return {
            "is_valid": False,
            "validation_error": "Message exceeds 2000 character limit",
            "processed_message": "",
            "pipeline_log": ["validate_node: FAILED — message too long"],
        }

    return {
        "is_valid": True,
        "validation_error": None,
        "processed_message": message,
        "pipeline_log": ["validate_node: OK"],
    }


def preprocess_node(state: ClassifierState) -> dict:
    msg = state["processed_message"]

    # Collapse multiple whitespace
    msg = re.sub(r"\s+", " ", msg).strip()

    # Normalise unicode quotes
    msg = msg.replace("\u201c", '"').replace("\u201d", '"')
    msg = msg.replace("\u2018", "'").replace("\u2019", "'")

    return {
        "processed_message": msg,
        "pipeline_log": [f"preprocess_node: OK — cleaned to '{msg[:60]}...'"],
    }





def classify_node(state: ClassifierState) -> dict:
    messages_history = state.get("messages", [])
    if not messages_history:
        messages_history = [HumanMessage(content=state["processed_message"])]

    context_message = state.get("context_message")

    try:
        llm = _get_groq_llm()
        intents = _call_llm(llm, messages_history, context_message=context_message)
        result = intents[0]

        is_injection = False
        if result["intent"] == "general_query" and result["confidence"] == 0.0:
            is_injection = True

        return {
            "intent": result["intent"],
            "confidence": result["confidence"],
            "entities": result["entities"],
            "bot_response": result["bot_response"],
            "all_intents": intents,
            "is_multi_intent": len(intents) > 1,
            "is_injection": is_injection,
            "llm_error": None,
            "pipeline_log": [
                f"classify_node: OK — intent={result['intent']} "
                f"conf={result['confidence']:.2f} via Groq"
            ],
        }

    except Exception as e:
        print(f"[WARN] classify_node Groq error: {e}")
        return {
            "llm_error": str(e),
            "pipeline_log": [f"classify_node: FAILED — {str(e)[:80]}"],
        }


def fallback_node(state: ClassifierState) -> dict:
    messages_history = state.get("messages", [])
    if not messages_history:
        messages_history = [HumanMessage(content=state["processed_message"])]

    context_message = state.get("context_message")
    llm = _get_gemini_llm()

    if llm is None:
        # No Gemini key/package — return error response
        result = {
            "intent": "general_query",
            "confidence": 0.0,
            "entities": EMPTY_ENTITIES.copy(),
            "bot_response": "I'm having trouble connecting to my servers right now. Please try again later.",
        }
        return {
            **result,
            "all_intents": [result],
            "is_multi_intent": False,
            "is_injection": False,
            "llm_error": "No Gemini API key available",
            "pipeline_log": ["fallback_node: FAILED — no Gemini key/package available"],
        }

    try:
        intents = _call_llm(llm, messages_history, context_message=context_message)
        result = intents[0]

        is_injection = False
        if result["intent"] == "general_query" and result["confidence"] == 0.0:
            is_injection = True

        return {
            "intent": result["intent"],
            "confidence": result["confidence"],
            "entities": result["entities"],
            "bot_response": result["bot_response"],
            "all_intents": intents,
            "is_multi_intent": len(intents) > 1,
            "is_injection": is_injection,
            "llm_error": None,
            "pipeline_log": [
                f"fallback_node: OK — intent={result['intent']} via Gemini"
            ],
        }

    except Exception as e:
        print(f"[ERROR] fallback_node Gemini also failed: {e}")
        result = {
            "intent": "general_query",
            "confidence": 0.0,
            "entities": EMPTY_ENTITIES.copy(),
            "bot_response": "Sorry, our systems are currently down. Please call the clinic directly.",
        }
        return {
            **result,
            "all_intents": [result],
            "is_multi_intent": False,
            "is_injection": False,
            "llm_error": str(e),
            "pipeline_log": [f"fallback_node: FAILED — Gemini failure: {str(e)[:60]}"],
        }


def postprocess_node(state: ClassifierState) -> dict:
    intent = state.get("intent", "general_query")
    is_emergency = intent == "emergency"

    log_parts = [f"postprocess_node: OK — is_emergency={is_emergency}"]

    if is_emergency:
        log_parts.append("postprocess_node: ⚠ EMERGENCY INTENT DETECTED")

    return {
        "is_emergency": is_emergency,
        "pipeline_log": log_parts,
    }


def error_node(state: ClassifierState) -> dict:
    result = {
        "intent": "general_query",
        "confidence": 0.0,
        "entities": EMPTY_ENTITIES.copy(),
        "bot_response": None,
    }
    return {
        **result,
        "all_intents": [result],
        "is_multi_intent": False,
        "is_emergency": False,
        "pipeline_log": [f"error_node: returned validation error"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# CONDITIONAL EDGE FUNCTIONS
# These functions read the current state and return the NAME of the next node.
# ══════════════════════════════════════════════════════════════════════════════

def route_after_validation(
    state: ClassifierState,
) -> Literal["preprocess_node", "error_node"]:
    """Routes to preprocess if valid, error if not."""
    return "preprocess_node" if state.get("is_valid") else "error_node"


def route_after_classify(
    state: ClassifierState,
) -> Literal["postprocess_node", "fallback_node"]:
    """Routes to postprocess if Groq succeeded, fallback if it failed."""
    return "postprocess_node" if state.get("llm_error") is None else "fallback_node"





# ══════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_classifier_graph():
    graph = StateGraph(ClassifierState)

    # ── Register nodes ─────────────────────────────────────────────────────────
    graph.add_node("validate_node", validate_node)
    graph.add_node("preprocess_node", preprocess_node)
    graph.add_node("classify_node", classify_node)
    graph.add_node("fallback_node", fallback_node)
    graph.add_node("postprocess_node", postprocess_node)
    graph.add_node("error_node", error_node)

    # ── Wire edges ─────────────────────────────────────────────────────────────
    # START → validate
    graph.add_edge(START, "validate_node")

    # validate → preprocess OR error (conditional)
    graph.add_conditional_edges(
        "validate_node",
        route_after_validation,
        {
            "preprocess_node": "preprocess_node",
            "error_node": "error_node",
        },
    )

    # preprocess → classify (always)
    graph.add_edge("preprocess_node", "classify_node")

    # classify → postprocess OR fallback (conditional)
    graph.add_conditional_edges(
        "classify_node",
        route_after_classify,
        {
            "postprocess_node": "postprocess_node",
            "fallback_node": "fallback_node",
        },
    )

    # fallback always goes to postprocess after it resolves
    graph.add_edge("fallback_node", "postprocess_node")

    # postprocess and error both go to END
    graph.add_edge("postprocess_node", END)
    graph.add_edge("error_node", END)

    return graph.compile()


# Compile once at import time — reused for every request
classifier_graph = build_classifier_graph()
