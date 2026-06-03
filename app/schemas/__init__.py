from __future__ import annotations
from typing import Optional, Annotated, Literal
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
    intent: str
    confidence: float
    entities: Entities
    bot_response: Optional[str] = None

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
    context_message: Optional[str]      # Previous bot response (for context-aware classification)

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

# Booking sub-flow states (granular steps within a booking interaction)
BOOKING_FLOW_STATES = [
    "GREETING",
    "COLLECTING_INFO",
    "COLLECT_DATE_TIME",
    "COLLECT_DOCTOR_PREFERENCE",
    "CONFIRM_SLOT",
    "WAITING_DOCTOR_APPROVAL",
    "BOOKED",
    "CANCEL_CONFIRM",
    "RESCHEDULE_COLLECTING",
    "RESCHEDULE_CONFIRM",
]

# Patient journey states (high-level lifecycle — used by ConsultationAgent in Sprint 2)
PATIENT_JOURNEY_STATES = [
    "NEW_PATIENT",           # First contact, no appointment yet
    "BOOKING_IN_PROGRESS",  # Actively booking an appointment
    "AWAITING_CONFIRMATION", # Waiting for doctor to approve the slot
    "BOOKED",               # Appointment confirmed and scheduled
    "CONSULTATION_ACTIVE",  # Doctor and patient exchanging clinical messages
    "POST_CONSULT",         # Consultation ended, SOAP generated
    "FOLLOW_UP_PENDING",    # 24h after POST_CONSULT, follow-up questions due
]

# Full 10-intent set
ALL_INTENTS = [
    "appointment_book",
    "appointment_cancel",
    "appointment_reschedule",
    "appointment_status",       # check status of existing booking
    "followup_query",
    "lab_report_share",
    "prescription_request",
    "general_query",
    "emergency",
    "consultation_message",     # message during active clinical consultation
]


class BookingSession(BaseModel):
    """Per-patient session — persisted to Redis, keyed by from_number."""
    from_number: str
    state: str = "GREETING"
    journey_state: str = "NEW_PATIENT"       # high-level patient lifecycle state
    patient_name: Optional[str] = None
    requested_date: Optional[str] = None
    requested_time: Optional[str] = None
    doctor_name: Optional[str] = None
    symptoms: Optional[list[str]] = None
    doctor_shortlist: Optional[list[str]] = None  # ordered names shown in COLLECT_DOCTOR_PREFERENCE
    new_requested_date: Optional[str] = None   # used during RESCHEDULE_COLLECTING
    new_requested_time: Optional[str] = None   # used during RESCHEDULE_COLLECTING
    last_bot_response: Optional[str] = None    # for context-aware classification
    clinic_id: Optional[str] = None            # resolved from the Twilio "to" number
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
    # Clinic context — resolved from Twilio "To" number in webhook
    clinic_id: Optional[str]
    clinic_open_hour: int
    clinic_close_hour: int


# ── Consultation Models (Sprint 2) ────────────────────────────────────────────

class ConsultationMessage(BaseModel):
    sender_role: Literal["doctor", "patient"]
    text: Optional[str] = None
    audio_url: Optional[str] = None
    duration_secs: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ConsultationSession(BaseModel):
    consultation_id: str                    # "CONS" + 6-char uuid
    patient_number: str
    doctor_number: str
    doctor_name: str
    clinic_id: Optional[str] = None         # isolates sessions per clinic (multi-tenant)
    appointment_id: Optional[str] = None
    messages: list[ConsultationMessage] = Field(default_factory=list)
    audio_files: list[dict] = Field(default_factory=list)   # {url, duration_secs} for Jameel bundle
    started_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)
    is_active: bool = True
    ended_reason: Optional[str] = None      # "closing_phrase" | "inactivity"
