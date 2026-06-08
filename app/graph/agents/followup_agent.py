import json
import os
import re as _re

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from app.schemas import BookingState

load_dotenv()


def _strip_dr(name: str) -> str:
    return _re.sub(r"(?i)^dr\.?\s*", "", name).strip()


_REPORT_KEYWORDS = {
    "report", "pdf", "result", "send", "bhej", "bhejna", "bhejunga",
    "share", "attach", "upload", "test", "lab",
}

# Simple acknowledgment phrases — patient is just saying "OK/thanks/done".
# When detected in FOLLOW_UP_PENDING, do NOT forward to doctor; auto-close session.
_ACK_KEYWORDS = {
    "ok", "okay", "k", "thik", "thik hai", "theek", "theek hai",
    "thanks", "thank you", "shukriya", "dhanyawad",
    "acha", "accha", "achha", "acha hai", "accha hai",
    "bye", "goodbye", "done", "noted", "got it", "understood",
    "haan", "han", "ji", "ji haan", "ji han",
    "bilkul", "zaroor", "sure", "fine", "alright",
}

_FOLLOWUP_ANALYSIS_SYSTEM = """You are a clinical follow-up assistant for a doctor's clinic.
A patient has sent a message after their recent consultation. Decide whether you can answer it
directly from the consultation records, or whether it needs the doctor's attention.

ANSWER DIRECTLY only if the question is about:
- Prescribed medications (dose, timing, how to take them, common side effects)
- The documented diagnosis or condition
- The treatment plan or care instructions already written in the consultation
- Routine follow-up questions clearly addressed in the SOAP plan

ESCALATE TO DOCTOR if:
- Patient reports new, worsening, or unexpected symptoms
- Needs a new prescription or change in medication
- The question cannot be confidently answered from the records
- The query involves fresh medical judgment
- You are uncertain

CRITICAL RULES:
- Always respond in the SAME LANGUAGE as the patient's message (Hindi, Urdu, English, etc.)
- Keep answers concise, warm, and jargon-free — patient-friendly tone
- Never invent information not present in the consultation records
- When in doubt, ALWAYS escalate — patient safety is paramount

Return ONLY valid JSON with no markdown or extra text:
{
  "can_answer": true or false,
  "answer": "Your warm, direct response to the patient (empty string if escalating)",
  "confidence": 0.0 to 1.0,
  "escalate_reason": "One-line reason for escalation (empty string if answering directly)"
}"""


def _is_simple_ack(message: str) -> bool:
    return message.strip().lower() in _ACK_KEYWORDS


def _mentions_report(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _REPORT_KEYWORDS)


def _fetch_consultation_sync(clinic_id: str | None, patient_phone: str) -> dict | None:
    """Fetch the patient's latest consultation record synchronously.

    Creates a fresh async engine in a worker thread to avoid the "Future attached
    to a different loop" error that occurs when reusing the shared FastAPI engine pool.
    """
    if not clinic_id:
        return None
    import asyncio
    import concurrent.futures

    async def _do_fetch():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker as _sm
        from sqlalchemy import select
        from sqlalchemy import desc as _desc
        from app.models.patient import Patient
        from app.models.medical_record import MedicalRecord

        db_url = os.getenv("DATABASE_URL", "")
        engine = create_async_engine(db_url, echo=False, pool_size=1, max_overflow=0)
        Session = _sm(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with Session() as db:
                p = await db.execute(
                    select(Patient).where(
                        Patient.clinic_id == clinic_id,
                        Patient.phone_number == patient_phone,
                    )
                )
                patient = p.scalar_one_or_none()
                if not patient:
                    return None
                r = await db.execute(
                    select(MedicalRecord)
                    .where(
                        MedicalRecord.patient_id == patient.id,
                        MedicalRecord.record_type == "consultation",
                    )
                    .order_by(_desc(MedicalRecord.visit_date))
                    .limit(1)
                )
                record = r.scalar_one_or_none()
                if not record:
                    return None
                return {
                    "chief_complaint": record.chief_complaint,
                    "soap_subjective": record.soap_subjective,
                    "soap_assessment": record.soap_assessment,
                    "soap_plan": record.soap_plan,
                    "diagnoses": record.diagnoses or [],
                    "medications": record.medications or [],
                    "symptoms": record.symptoms or [],
                    "visit_date": str(record.visit_date) if record.visit_date else None,
                }
        finally:
            await engine.dispose()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _do_fetch()).result(timeout=15)
    except Exception as exc:
        print(f"[followup_agent] _fetch_consultation_sync failed: {exc}")
        return None


def _build_consultation_context(record: dict) -> str:
    """Format a consultation record dict into a readable context block for the LLM."""
    parts = []
    if record.get("chief_complaint"):
        parts.append(f"Chief Complaint: {record['chief_complaint']}")
    if record.get("diagnoses"):
        diag_list = ", ".join(
            (d.get("name") or str(d)) if isinstance(d, dict) else str(d)
            for d in record["diagnoses"][:5]
        )
        parts.append(f"Diagnoses: {diag_list}")
    if record.get("medications"):
        med_list = "\n".join(
            f"  - {m.get('name', '')} {m.get('frequency', '')}".strip() if isinstance(m, dict) else f"  - {m}"
            for m in record["medications"][:6]
        )
        parts.append(f"Prescribed Medications:\n{med_list}")
    if record.get("soap_assessment"):
        parts.append(f"Assessment: {record['soap_assessment'][:500]}")
    if record.get("soap_plan"):
        parts.append(f"Treatment Plan: {record['soap_plan'][:500]}")
    if record.get("visit_date"):
        parts.append(f"Visit Date: {record['visit_date']}")
    return "\n\n".join(parts) if parts else ""


def _analyze_followup_query(incoming: str, record: dict) -> dict:
    """Call the LLM to decide: answer directly or escalate to doctor.

    Returns dict with keys: can_answer (bool), answer (str), confidence (float).
    Falls back to escalate=True on any error.
    """
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=0,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
        context = _build_consultation_context(record)
        human_content = (
            f"CONSULTATION RECORDS:\n{context}\n\n"
            f"PATIENT MESSAGE: {incoming}"
        )
        response = llm.invoke([
            SystemMessage(content=_FOLLOWUP_ANALYSIS_SYSTEM),
            HumanMessage(content=human_content),
        ])
        raw = response.content.strip()
        # Strip markdown code fences if present
        raw = _re.sub(r"^```(?:json)?\s*", "", raw, flags=_re.MULTILINE)
        raw = _re.sub(r"\s*```$", "", raw, flags=_re.MULTILINE)
        result = json.loads(raw)
        return {
            "can_answer": bool(result.get("can_answer", False)),
            "answer": str(result.get("answer", "")),
            "confidence": float(result.get("confidence", 0.0)),
            "escalate_reason": str(result.get("escalate_reason", "")),
        }
    except Exception as exc:
        print(f"[followup_agent] LLM analysis failed, defaulting to escalate: {exc}")
        return {"can_answer": False, "answer": "", "confidence": 0.0, "escalate_reason": "LLM error"}


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
        import os as _os
        from app.services.store import reset_session

        # If the patient is just acknowledging (ok/thik hai/thanks/bye),
        # close the session quietly — do NOT forward to doctor.
        if _is_simple_ack(incoming):
            reset_session(from_number, session_dict.get("clinic_id"))
            clinic_name = _os.getenv("CLINIC_NAME", "ClinicAI")
            return {
                "reply_message": (
                    f"Thank you! 😊 We're glad to hear from you.\n\n"
                    f"Your consultation records have been saved. Feel free to reach out "
                    f"anytime if you need to book a new appointment. Take care! 🙏\n"
                    f"— {clinic_name}"
                ),
                "pipeline_log": ["followup_agent: FOLLOW_UP_PENDING — simple ack, session reset to NEW_PATIENT"],
            }

        # Genuine follow-up message — try to answer from consultation records first
        record = _fetch_consultation_sync(session_dict.get("clinic_id"), from_number)

        if record and not _mentions_report(incoming):
            analysis = _analyze_followup_query(incoming, record)
            if analysis["can_answer"] and analysis["confidence"] >= 0.75 and analysis["answer"]:
                return {
                    "reply_message": analysis["answer"],
                    "pipeline_log": [
                        f"followup_agent: FOLLOW_UP_PENDING — LLM answered directly "
                        f"(confidence={analysis['confidence']:.2f})"
                    ],
                }

        # Could not answer from records — escalate to doctor
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
            "pipeline_log": ["followup_agent: FOLLOW_UP_PENDING — escalated to doctor"],
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
