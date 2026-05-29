"""
FollowUpAgent — handles:
  - followup_query / prescription_request intents
  - Any message from a patient in POST_CONSULT or FOLLOW_UP_PENDING state
"""

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()

import re as _re

def _strip_dr(name: str) -> str:
    return _re.sub(r"(?i)^dr\.?\s*", "", name).strip()


_REPORT_KEYWORDS = {
    "report", "pdf", "result", "send", "bhej", "bhejna", "bhejunga",
    "share", "attach", "upload", "test", "lab",
}


def _mentions_report(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _REPORT_KEYWORDS)


def followup_node(state: BookingState) -> dict:
    from app.services.store import get_latest_appointment_for_patient
    from app.services.identity import find_doctor_number
    from app.services.whatsapp import send_whatsapp_message_sync

    from_number = state["from_number"]
    incoming = state.get("incoming_message", "")
    intent = state.get("intent", "general_query")
    session_dict = state.get("session") or {}
    journey_state = session_dict.get("journey_state", "NEW_PATIENT")

    appt = get_latest_appointment_for_patient(from_number)
    raw_doctor = (
        appt.doctor_name if appt
        else session_dict.get("doctor_name")
        or ""
    )
    doctor_name = _strip_dr(raw_doctor) if raw_doctor else "the doctor"
    patient_name = (
        (appt.patient_name if appt else None)
        or session_dict.get("patient_name")
        or ""
    )

    # ── FOLLOW_UP_PENDING: patient replied to the check-in message ────────────
    if journey_state == "FOLLOW_UP_PENDING":
        # Forward the patient's reply to the doctor and save reply context
        try:
            doctor_number = find_doctor_number(raw_doctor) if appt else None
            if doctor_number:
                from app.services.store import save_doctor_reply_context
                name_label = f"*{patient_name}*" if patient_name else "your patient"
                doc_msg = (
                    f"📋 Follow-up from {name_label}:\n\n"
                    f"{incoming}\n\n"
                    f"_(Just reply here to send back to this patient)_"
                )
                send_whatsapp_message_sync(doctor_number, doc_msg)
                # Save context so the doctor can reply without any command
                save_doctor_reply_context(doctor_number, from_number, patient_name or "")
        except Exception as exc:
            print(f"[followup_agent] Could not notify doctor: {exc}")

        # Ack to patient — prompt to share report if they mentioned it
        if _mentions_report(incoming):
            reply = (
                f"Thank you for the update{', ' + patient_name if patient_name else ''}! 😊 "
                f"Glad to hear things are improving.\n\n"
                f"Please share the blood test PDF here when it's ready and "
                f"*Dr. {doctor_name}* will review it right away. 🏥"
            )
        else:
            reply = (
                f"Thank you for the update! 😊 "
                f"*Dr. {doctor_name}* has been notified of your response.\n\n"
                "If you need anything else or want to book a follow-up appointment, "
                "just say *book appointment*. 🙏"
            )

        return {
            "reply_message": reply,
            "pipeline_log": ["followup_agent: FOLLOW_UP_PENDING — ack sent, doctor notified"],
        }

    # ── POST_CONSULT ───────────────────────────────────────────────────────────
    if journey_state == "POST_CONSULT":
        if intent == "prescription_request":
            return {
                "reply_message": (
                    f"📋 Your consultation note from *Dr. {doctor_name}* has been sent to you as a PDF — "
                    "please check the file shared earlier for your prescription details.\n\n"
                    "For any questions or to book a follow-up appointment, just say *book appointment*. 🙏"
                ),
                "pipeline_log": ["followup_agent: POST_CONSULT prescription_request"],
            }

        return {
            "reply_message": (
                f"✅ Your consultation with *Dr. {doctor_name}* has been recorded and the note has been sent to you.\n\n"
                f"If *Dr. {doctor_name}* recommended a follow-up visit, they will reach out to you shortly. "
                "To book your next appointment now, just say *book appointment*. 😊"
            ),
            "pipeline_log": ["followup_agent: POST_CONSULT response sent"],
        }

    # ── prescription_request (no active post-consult session) ─────────────────
    if intent == "prescription_request":
        if appt:
            return {
                "reply_message": (
                    f"We'll note your prescription request for *Dr. {_strip_dr(appt.doctor_name)}*. "
                    "The doctor will review and send it to you shortly. 🙏\n\n"
                    "If urgent, please call the clinic directly."
                ),
                "pipeline_log": ["followup_agent: prescription request acknowledged"],
            }

    # ── Default ───────────────────────────────────────────────────────────────
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
