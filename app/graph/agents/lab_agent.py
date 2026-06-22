import os
import re

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState, BookingSession

load_dotenv()

# Keywords that indicate the doctor prescribed lab tests in the SOAP plan
_LAB_KEYWORDS = frozenset([
    "blood test", "cbc", "complete blood count", "urine test", "urinalysis",
    "urine analysis", "urine culture", "x-ray", "xray", "ultrasound", "mri",
    "ct scan", "ecg", "echo", "echocardiogram", "thyroid", "lipid profile",
    "hba1c", "sugar test", "hemoglobin", "haemoglobin", "creatinine",
    "liver function", "kidney function", "cholesterol", "covid test",
    "dengue", "malaria", "biopsy", "pathology", "lab", "laboratory",
    "diagnostic", "investigations", "blood work", "test ordered",
    "tests ordered", "refer for", "send for", "get tested", "get a test",
    "follow-up test", "repeat test", "blood count", "serum", "culture",
])

# Tokens that are never a patient name (dates, commands, report keywords, etc.)
_NO_NAME_TOKENS = {
    "today", "tomorrow", "kal", "parso", "aaj",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "am", "pm", "yes", "no", "ok", "okay", "haan", "nahi", "nhi",
    "hi", "hello", "namaste",
    "share", "report", "xray", "x-ray", "blood", "urine", "ecg", "scan",
    "lab", "test", "result", "with", "send", "forward",
    "doctor", "dr", "appointment", "book", "cancel", "reschedule",
}

_ALREADY_SENT_PHRASES = frozenset({
    "already sent", "already send", "sent already", "done sent",
    "bhej diya", "bhej diya hai", "send kar diya", "de diya",
    "already forwarded", "forwarded already", "send kiya", "bheja",
})


def _is_already_sent(message: str) -> bool:
    """Return True when the user confirms they have already sent the PDF."""
    msg = message.strip().lower()
    if any(p in msg for p in _ALREADY_SENT_PHRASES):
        return True
    words = msg.split()
    return len(words) <= 4 and "sent" in words


_REPORT_TYPE_RE = re.compile(
    r"\b(x-?ray|blood\s*(?:test|report)?|urine(?:\s*test)?|ecg|ultrasound|"
    r"mri|ct\s*scan|sonography|echo|biopsy|pathology|thyroid|sugar|lipid|"
    r"cbc|haemoglobin|hemoglobin|hba1c|liver\s*(?:function)?|kidney\s*(?:function)?|"
    r"creatinine|cholesterol|covid|dengue|malaria)\b",
    re.IGNORECASE,
)

_DOCTOR_FROM_MSG_RE = re.compile(
    r"(?:share\s+with|send\s+to|forward\s+to|with\s+dr\.?\s*|to\s+dr\.?\s*|doctor\s+)"
    r"(\w+)",
    re.IGNORECASE,
)


def _extract_report_type(message: str) -> str | None:
    m = _REPORT_TYPE_RE.search(message)
    return m.group(0).strip().lower() if m else None


def _extract_doctor_from_msg(message: str) -> str | None:
    m = _DOCTOR_FROM_MSG_RE.search(message)
    if m:
        name = m.group(1).strip()
        if len(name) >= 2 and name.lower() not in _NO_NAME_TOKENS:
            return name.title()
    return None


def _looks_like_name(text: str) -> bool:
    """Return True when text is plausibly a patient name and nothing else."""
    words = text.lower().split()
    return (
        bool(text)
        and 2 <= len(text) <= 50
        and 1 <= len(words) <= 4
        and not re.search(r'[^\w\s.\-\',]', text, flags=re.UNICODE)
        and not any(re.search(r'\d', w) for w in words)
        and not any(w in _NO_NAME_TOKENS for w in words)
    )


def _prescription_has_lab_tests(clinic_id: str | None, from_number: str) -> bool:
    """Return True if the latest consultation SOAP plan contains lab-test keywords.

    Fails open (returns True) when the DB is unreachable — avoids blocking patients
    on infrastructure issues.
    """
    if not clinic_id or not from_number:
        return True  # can't verify → fail open
    try:
        from app.services.patient_service import get_latest_consultation_record
        from app.services.async_runner import run_async
        record = run_async(get_latest_consultation_record(clinic_id, from_number), timeout=5)
        if not record:
            return False
        text = " ".join(filter(None, [
            record.get("soap_plan") or "",
            record.get("soap_assessment") or "",
        ])).lower()
        return any(kw in text for kw in _LAB_KEYWORDS)
    except Exception:
        return True  # fail open on infrastructure errors


def lab_node(state: BookingState) -> dict:
    """
    Stateful lab report info-collection node.

    Persists patient_name, doctor_name, and lab_report_type to the BookingSession
    across turns (state = "LAB_COLLECTING") so the user doesn't have to repeat
    themselves if the classifier misses something in one turn.
    """
    session_dict = state.get("session") or {}
    try:
        session = BookingSession(**session_dict)
    except Exception:
        session = None

    entities = state.get("extracted_entities") or {}
    incoming = (state.get("incoming_message") or "").strip()
    booking_state = session.state if session else "GREETING"

    # ── Validation (first-entry only — skip when already mid-collection) ─────
    if booking_state not in ("LAB_COLLECTING", "LAB_PDF_REQUESTED"):
        from_number = state.get("from_number", "")
        clinic_id = state.get("clinic_id")
        journey_state = session.journey_state if session else "NEW_PATIENT"

        # Req 1: Appointment dependency — must have had at least one non-cancelled appointment
        if journey_state not in ("POST_CONSULT", "FOLLOW_UP_PENDING"):
            from app.services.store import get_appointments_by_number
            appts = get_appointments_by_number(from_number)
            has_appointment = any(getattr(a, "status", "active") != "cancelled" for a in appts)
            if not has_appointment:
                return {
                    "reply_message": (
                        "Lab reports can only be shared *after* a completed appointment with the doctor. 📅\n\n"
                        "Please *book an appointment* first and visit the clinic before sharing any lab reports."
                    ),
                    "session": session.model_dump() if session else session_dict,
                    "pipeline_log": ["lab_agent: blocked — no completed appointment on record"],
                }

        # Req 2: Prescription authorization — doctor must have ordered lab tests
        if not _prescription_has_lab_tests(clinic_id, from_number):
            return {
                "reply_message": (
                    "You can only share lab reports if the doctor *prescribed diagnostic tests* "
                    "during your consultation. 🔬\n\n"
                    "If you believe tests were ordered, please contact the clinic directly."
                ),
                "session": session.model_dump() if session else session_dict,
                "pipeline_log": ["lab_agent: blocked — no lab tests found in prescription"],
            }

    # ── 0. Handle LAB_PDF_REQUESTED: user replied after being asked to forward PDF ──
    if booking_state == "LAB_PDF_REQUESTED":
        if _is_already_sent(incoming):
            # User confirmed they already sent the PDF — acknowledge and clear
            if session:
                session.state = "GREETING"
                session.patient_name = None
                session.doctor_name = None
                session.lab_report_type = None
            return {
                "reply_message": (
                    "Got it! Our team will process your report shortly. 🙏 "
                    "Let us know if you need anything else."
                ),
                "session": session.model_dump() if session else session_dict,
                "pipeline_log": ["lab_agent: user confirmed PDF already sent, acknowledged"],
            }
        else:
            # User is starting a new lab request — reset and fall through to collection
            if session:
                session.state = "LAB_COLLECTING"
                session.patient_name = None
                session.doctor_name = None
                session.lab_report_type = None
            booking_state = "LAB_COLLECTING"

    # ── 1. Apply structured entities from classifier ─────────────────────────
    if session:
        if entities.get("patient_name"):
            session.patient_name = entities["patient_name"]
        if entities.get("doctor_name"):
            session.doctor_name = entities["doctor_name"]

    # ── 2. Message-level fallbacks ───────────────────────────────────────────
    if session:
        # Report type from keyword scan
        if not session.lab_report_type:
            rtype = _extract_report_type(incoming)
            if rtype:
                session.lab_report_type = rtype

        # Doctor name from "share with X" / "send to Dr X" pattern.
        # This catches replies that trip the classifier's injection guard.
        if not session.doctor_name:
            dr = _extract_doctor_from_msg(incoming)
            if dr:
                session.doctor_name = dr

        # Bare-name fallback: when we are collecting and the message looks like
        # a name but the classifier returned nothing (e.g. user replied "Alok").
        if (
            booking_state == "LAB_COLLECTING"
            and not session.patient_name
            and not entities.get("patient_name")
            and not _extract_doctor_from_msg(incoming)
        ):
            if _looks_like_name(incoming):
                session.patient_name = incoming

    # ── 3. Decide what is still missing and build the reply ──────────────────
    needs_name = not (session and session.patient_name)
    needs_doctor = not (session and session.doctor_name)

    if needs_name and needs_doctor:
        reply = (
            "Sure! To share a lab report, I need two things:\n\n"
            "1️⃣ *Patient's full name* _(e.g. Rahul Sharma)_\n"
            "2️⃣ *Doctor's name* _(e.g. Dr. Anjali or just Anjali)_\n\n"
            "Please share both and I'll get it across right away."
        )
        if session:
            session.state = "LAB_COLLECTING"

    elif needs_name:
        reply = (
            "What is the *patient's full name* for this report?\n"
            "_(e.g. Rahul Sharma)_"
        )
        if session:
            session.state = "LAB_COLLECTING"

    elif needs_doctor:
        patient_display = session.patient_name if session else "the patient"
        reply = (
            f"Got it — which *doctor* should receive *{patient_display}*'s report?\n"
            f"_(e.g. Dr. Anjali — just the name is fine)_"
        )
        if session:
            session.state = "LAB_COLLECTING"

    else:
        # All info collected — ask patient to forward the PDF
        patient_display = session.patient_name if session else "the patient"
        raw_dr = (session.doctor_name if session else None) or "the doctor"
        doctor_display = (
            raw_dr if raw_dr.lower().startswith("dr") else f"Dr. {raw_dr}"
        )
        rtype = (session.lab_report_type if session else None) or "report"
        reply = (
            f"Perfect! Please *send the {rtype} PDF* in this chat now 📎\n\n"
            f"*For:* {patient_display}\n"
            f"*Doctor:* {doctor_display}\n\n"
            f"_How to send:_ Tap the 📎 attachment icon → *Document* → select your PDF file.\n\n"
            f"Once received, we'll process it and forward it to {doctor_display} for review. 🙏\n\n"
            f"_Already sent the PDF? Just reply *sent* and we'll confirm._"
        )
        if session:
            # Await the PDF forward; keep state so "already sent" is handled cleanly
            session.state = "LAB_PDF_REQUESTED"
            session.patient_name = None
            session.doctor_name = None
            session.lab_report_type = None

    updated_session = session.model_dump() if session else session_dict
    return {
        "reply_message": reply,
        "session": updated_session,
        "pipeline_log": [
            f"lab_agent: patient={getattr(session, 'patient_name', None)} "
            f"doctor={getattr(session, 'doctor_name', None)} "
            f"report={getattr(session, 'lab_report_type', None)}"
        ],
    }


def build_lab_graph():
    g = StateGraph(BookingState)
    g.add_node("lab_node", lab_node)
    g.add_edge(START, "lab_node")
    g.add_edge("lab_node", END)
    return g.compile()


lab_agent_graph = build_lab_graph()
