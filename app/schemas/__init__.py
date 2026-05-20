from __future__ import annotations
from typing import Optional, Annotated
from datetime import datetime
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
import operator

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# ── API Request / Response ─────────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    from_number: str = Field(..., description="Patient WhatsApp number e.g. +919876543210")
    message: str = Field(..., description="Raw WhatsApp message text from the patient")


class Entities(BaseModel):
    patient_name: Optional[str] = Field(None)
    doctor_name: Optional[str] = Field(None)
    requested_date: Optional[str] = Field(None)
    requested_time: Optional[str] = Field(None)
    symptoms_mentioned: Optional[list[str]] = Field(None)
    medication_mentioned: Optional[list[str]] = Field(None)


class IntentResult(BaseModel):
    """A single detected intent with its own confidence, entities, and bot response."""
    intent: str
    confidence: float
    entities: Entities
    bot_response: Optional[str] = None


class ClassifyResponse(BaseModel):
    # ── Primary intent (highest confidence) — backward compatible ──────────────
    intent: str
    confidence: float
    entities: Entities
    bot_response: Optional[str] = None

    # ── Multi-intent fields ───────────────────────────────────────────────────
    is_multi_intent: bool = Field(
        default=False,
        description="True if the message contains more than one intent"
    )
    all_intents: list[IntentResult] = Field(
        default_factory=list,
        description="All detected intents with individual entities and bot responses"
    )

    raw_message: str
    flagged_as_injection: bool = Field(
        default=False,
        description="True if the message was flagged as a potential prompt injection attempt"
    )
    # LangGraph-specific: shows which nodes ran for transparency
    pipeline_trace: list[str] = Field(
        default_factory=list,
        description="Ordered list of graph nodes that executed for this request"
    )


# ── LangGraph State ────────────────────────────────────────────────────────────
# This is the shared state object passed between every node in the graph.
# Each field is updated by the node responsible for it.
# Using Annotated[list, operator.add] on pipeline_log means each node
# APPENDS to the list rather than overwriting it — perfect for tracing.

class ClassifierState(TypedDict):
    # ── Input ──────────────────────────────────────────────────────────────────
    from_number: str                    # Patient phone number
    raw_message: str                    # Original message exactly as received
    messages: Annotated[list[AnyMessage], add_messages]  # Chat memory

    # ── Set by: validate_node ──────────────────────────────────────────────────
    is_valid: bool                      # False if message is empty/invalid
    validation_error: Optional[str]     # Error message if invalid

    # ── Set by: preprocess_node ───────────────────────────────────────────────
    processed_message: str              # Cleaned message (stripped, normalised)

    # ── Set by: classify_node ─────────────────────────────────────────────────
    intent: str                         # Primary intent (highest confidence)
    confidence: float
    entities: dict                      # Raw dict before Pydantic wrapping
    bot_response: Optional[str]
    llm_error: Optional[str]            # Set if LLM call failed
    all_intents: list[dict]             # All detected intents
    is_multi_intent: bool               # True if multiple intents detected

    # ── Set by: guard_node ─────────────────────────────────────────────────────
    is_injection: bool                  # True if message looks like prompt injection
    injection_reason: Optional[str]     # Why it was flagged

    # ── Set by: postprocess_node ──────────────────────────────────────────────
    is_emergency: bool                  # True if intent == "emergency"

    # ── Appended by every node ────────────────────────────────────────────────
    # operator.add means each node's returned list gets APPENDED, not replaced
    pipeline_log: Annotated[list[str], operator.add]


# ── Booking Bot Models / State ────────────────────────────────────────────────

BOOKING_FLOW_STATES = [
    "GREETING",
    "COLLECT_DATE_TIME",
    "COLLECT_DOCTOR_PREFERENCE",
    "CONFIRM_SLOT",
    "BOOKED",
    "CANCEL_CONFIRM",
    "RESCHEDULE_COLLECTING",
    "RESCHEDULE_CONFIRM",
]


class BookingSession(BaseModel):
    """Per-user session stored in memory keyed by from_number."""
    from_number: str
    state: str = "GREETING"
    patient_name: Optional[str] = None
    requested_date: Optional[str] = None
    requested_time: Optional[str] = None
    doctor_name: Optional[str] = None
    symptoms: Optional[list[str]] = None
    new_requested_date: Optional[str] = None   # used during RESCHEDULE_COLLECTING
    new_requested_time: Optional[str] = None   # used during RESCHEDULE_COLLECTING
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AppointmentRecord(BaseModel):
    """Confirmed appointment stored in the in-memory appointment store."""
    appointment_id: str
    from_number: str
    patient_name: Optional[str]
    doctor_name: str
    date_str: str
    time_str: str
    symptoms: Optional[list[str]]
    confirmed_at: datetime = Field(default_factory=datetime.now)
    reminder_sent: bool = False


class BookingState(TypedDict):
    from_number: str
    incoming_message: str
    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    confidence: float
    extracted_entities: dict
    bot_response: Optional[str]
    session: Optional[dict]
    is_new_session: bool
    current_booking_state: str
    reply_message: str
    appointment_id: Optional[str]
    is_off_topic: bool
    pipeline_log: Annotated[list[str], operator.add]
