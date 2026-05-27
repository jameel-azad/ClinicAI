"""
app/nodes.py — LangGraph nodes for the Clinical Scribe pipeline.

Node 1: transcribe_node        — Audio file → transcript (Whisper API)
Node 2: soap_generator_node   — Transcript → SOAP JSON (LLM, few-shot)
Node 3: grounding_check_node  — Verify every sentence maps to transcript
Node 4: pdf_output_node       — SOAP JSON + grounding → PDF
"""

import json
import logging
import os
import re
import tempfile
import time
from typing import Any

from dotenv import load_dotenv
from groq import Groq
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from app.graph.scribe.state import ScribeState, GroundingEntry

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _groq_client() -> Groq:
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


def _llm() -> ChatGroq:
    return ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


def _parse_json(raw: Any) -> Any:
    # Normalise: langchain may return a list of content blocks instead of a string
    if isinstance(raw, list):
        raw = " ".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in raw
        )
    text = str(raw)

    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    # Try direct parse first (clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # LLM added preamble/postamble — extract JSON object or array from within
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


# ---------------------------------------------------------------------------
# Node 1: transcribe_node
# ---------------------------------------------------------------------------

def transcribe_node(state: ScribeState) -> dict:
    """
    Transcribe the audio file using Groq Whisper API.

    Accepts mp3, mp4, mpeg, mpga, m4a, wav, webm, ogg (WhatsApp voice note format).
    Returns the full transcript text and detected language.
    """
    audio_path = state["audio_path"]
    errors = list(state.get("errors", []))

    try:
        client = _groq_client()
        model = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")

        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=(os.path.basename(audio_path), audio_file.read()),
                response_format="verbose_json",   # gives us language detection too
                # prompt helps Whisper handle medical terms and Hindi
                prompt=(
                    "This is a doctor's voice note from a clinic consultation in India. "
                    "The doctor may speak in English, Hindi, or a mix (Hinglish). "
                    "Medical terms, drug names, and abbreviations are common: "
                    "BP, SpO2, Hb, OD, BD, TDS, SOAP, CBC, ECG, IHD, DM, HTN."
                ),
            )

        transcript = response.text.strip()
        language = getattr(response, "language", "unknown")

        logger.info(f"[transcribe] Language: {language}, Length: {len(transcript)} chars")
        logger.info(f"[transcribe] Transcript preview: {transcript[:200]}...")

        return {
            "transcript": transcript,
            "language_detected": language,
            "errors": errors,
        }

    except Exception as e:
        msg = f"Transcription failed: {e}"
        logger.error(f"[transcribe] {msg}")
        errors.append(msg)
        return {"transcript": "", "language_detected": "unknown", "errors": errors}


# ---------------------------------------------------------------------------
# Node 2: soap_generator_node
# ---------------------------------------------------------------------------

SOAP_SYSTEM = """You are a clinical documentation assistant for Indian doctors. Your job is to convert a doctor's spoken voice note into a structured SOAP note.

RULES:
1. NEVER invent clinical details — every fact must be traceable to the transcript.
2. Insufficient section info → confidence < 0.5 + clarifying_question, never invent content.
3. Hinglish: 'BP thoda high hai' → 'Blood pressure mildly elevated.'
4. Abbreviations: OD=once daily, BD=twice daily, TDS=three times daily, SOS=as needed, HTN=hypertension, DM=diabetes mellitus, IHD=ischaemic heart disease.

Return ONLY valid JSON (no markdown, no preamble) matching this schema:
{
  "patient_name": "<patient name if mentioned, else empty string>",
  "doctor_name": "<doctor name if mentioned, else empty string>",
  "date": "<date of consultation if mentioned, else empty string>",
  "follow_up_days": <integer days until follow-up if doctor mentioned it (e.g. "2 weeks" → 14, "1 month" → 30, "3 days" → 3), or null if not mentioned>,
  "subjective": {
    "content": "<Chief complaint and history of presenting illness in patient's words / as reported by doctor>",
    "confidence": <0.0 to 1.0>,
    "is_missing": <true if transcript has no subjective info>,
    "clarifying_question": "<question if confidence < 0.5, else empty string>"
  },
  "objective": {
    "content": "<Vitals, physical examination findings, investigation results>",
    "confidence": <0.0 to 1.0>,
    "is_missing": <true if transcript has no objective info>,
    "clarifying_question": "<question if confidence < 0.5, else empty string>"
  },
  "assessment": {
    "content": "<Diagnosis or differential diagnosis>",
    "confidence": <0.0 to 1.0>,
    "is_missing": <true if transcript has no assessment info>,
    "clarifying_question": "<question if confidence < 0.5, else empty string>"
  },
  "plan": {
    "content": "<Medications prescribed, investigations ordered, referrals, follow-up instructions>",
    "confidence": <0.0 to 1.0>,
    "is_missing": <true if transcript has no plan info>,
    "clarifying_question": "<question if confidence < 0.5, else empty string>"
  }
}

FEW-SHOT EXAMPLE:

Example transcript (Hinglish):
"Patient ka naam Suresh hai, 45 saal ka. BP 140/90 hai, BP thoda high hai. Chest mein dard nahi. Amlodipine 5mg OD start karte hain, 2 hafte baad follow-up."

Expected output:
{
  "patient_name": "Suresh",
  "doctor_name": "",
  "date": "",
  "follow_up_days": 14,
  "subjective": {
    "content": "Patient: Suresh, 45 years. Presenting complaint not explicitly described beyond blood pressure evaluation. No chest pain.",
    "confidence": 0.55,
    "is_missing": false,
    "clarifying_question": "What was the patient's chief complaint bringing them to the clinic today?"
  },
  "objective": {
    "content": "Blood pressure: 140/90 mmHg (mildly elevated).",
    "confidence": 0.9,
    "is_missing": false,
    "clarifying_question": ""
  },
  "assessment": {
    "content": "Hypertension (stage 1).",
    "confidence": 0.8,
    "is_missing": false,
    "clarifying_question": ""
  },
  "plan": {
    "content": "1. Amlodipine 5mg once daily. 2. Follow-up in 2 weeks.",
    "confidence": 0.95,
    "is_missing": false,
    "clarifying_question": ""
  }
}
"""


def soap_generator_node(state: ScribeState) -> dict:
    transcript = state.get("transcript", "")
    errors = list(state.get("errors", []))

    if not transcript:
        msg = "No transcript available for SOAP generation."
        print(f"[soap_gen] {msg}")
        errors.append(msg)
        return {
            "soap_note": _empty_soap(),
            "missing_sections": ["subjective", "objective", "assessment", "plan"],
            "errors": errors,
        }

    last_error = None
    for attempt in range(2):
        try:
            if attempt > 0:
                print(f"[soap_gen] Retry attempt {attempt + 1} after delay...")
                time.sleep(3)

            llm = _llm()
            messages = [
                SystemMessage(content=SOAP_SYSTEM),
                HumanMessage(content=f"Doctor's voice note transcript:\n\n{transcript}"),
            ]
            response = llm.invoke(messages)
            print(f"[soap_gen] LLM response received, length={len(str(response.content))}")

            soap_raw = _parse_json(response.content)

            missing = []
            for section in ["subjective", "objective", "assessment", "plan"]:
                sec = soap_raw.get(section, {})
                if sec.get("is_missing") or sec.get("confidence", 1.0) < 0.5:
                    missing.append(section)

            follow_up_days = soap_raw.get("follow_up_days")
            print(f"[soap_gen] Success — missing={missing}, follow_up_days={follow_up_days}")
            logger.info(f"[soap_gen] Success — missing sections: {missing}")
            return {
                "soap_note": soap_raw,
                "missing_sections": missing,
                "follow_up_days": follow_up_days,
                "errors": errors,
            }

        except Exception as e:
            last_error = e
            print(f"[soap_gen] Attempt {attempt + 1} FAILED — {type(e).__name__}: {e}")
            logger.error(f"[soap_gen] Attempt {attempt + 1} failed: {e}")

    msg = f"SOAP generation failed after retries: {last_error}"
    print(f"[soap_gen] FINAL FAILURE: {msg}")
    errors.append(msg)
    return {
        "soap_note": _empty_soap(),
        "missing_sections": ["subjective", "objective", "assessment", "plan"],
        "errors": errors,
    }


def _empty_soap() -> dict:
    empty_section = {
        "content": "",
        "confidence": 0.0,
        "is_missing": True,
        "clarifying_question": "Please provide details for this section.",
    }
    return {
        "patient_name": "",
        "doctor_name": "",
        "date": "",
        "subjective": dict(empty_section),
        "objective": dict(empty_section),
        "assessment": dict(empty_section),
        "plan": dict(empty_section),
    }


# ---------------------------------------------------------------------------
# Node 3: grounding_check_node
# ---------------------------------------------------------------------------

GROUNDING_SYSTEM = """You are a medical safety auditor. Your job is to check whether each sentence in a SOAP note is grounded in (supported by) the original transcript.

For each sentence in the SOAP note:
- Find the transcript segment that supports it (copy the relevant 5-15 words from the transcript)
- If no transcript segment supports the sentence, mark it as ungrounded

Return ONLY valid JSON list (no markdown):
[
  {
    "sentence": "<exact sentence from SOAP note>",
    "transcript_segment": "<supporting text from transcript, or empty string if none>",
    "is_grounded": <true or false>
  },
  ...
]

IMPORTANT: Be strict. If a sentence contains a specific clinical claim (drug name, dosage, diagnosis, vital sign) that is not clearly in the transcript, mark it ungrounded even if it seems plausible.
"""


def grounding_check_node(state: ScribeState) -> dict:
    """
    Verify that every sentence in the SOAP note maps back to the transcript.
    Flags any ungrounded sentences as potential hallucinations.
    """
    soap_note = state.get("soap_note", {})
    transcript = state.get("transcript", "")
    errors = list(state.get("errors", []))

    if not transcript or not soap_note:
        return {"grounding_report": [], "ungrounded_flags": [], "errors": errors}

    # Collect all SOAP sentences
    soap_text_parts = []
    for section in ["subjective", "objective", "assessment", "plan"]:
        content = soap_note.get(section, {}).get("content", "")
        if content:
            soap_text_parts.append(content)

    all_soap_text = "\n".join(soap_text_parts)

    if not all_soap_text.strip():
        return {"grounding_report": [], "ungrounded_flags": [], "errors": errors}

    try:
        llm = _llm()
        messages = [
            SystemMessage(content=GROUNDING_SYSTEM),
            HumanMessage(content=(
                f"TRANSCRIPT:\n{transcript}\n\n"
                f"SOAP NOTE (to verify):\n{all_soap_text}"
            )),
        ]
        response = llm.invoke(messages)
        grounding_report: list[GroundingEntry] = _parse_json(response.content)

        ungrounded = [
            entry["sentence"]
            for entry in grounding_report
            if not entry.get("is_grounded", True)
        ]

        logger.info(
            f"[grounding] {len(grounding_report)} sentences checked, "
            f"{len(ungrounded)} ungrounded"
        )

        return {
            "grounding_report": grounding_report,
            "ungrounded_flags": ungrounded,
            "errors": errors,
        }

    except Exception as e:
        msg = f"Grounding check failed: {type(e).__name__}: {e}"
        print(f"[grounding] {msg}")
        logger.error(f"[grounding] {msg}")
        errors.append(msg)
        return {"grounding_report": [], "ungrounded_flags": [], "errors": errors}


# ---------------------------------------------------------------------------
# Node 4: followup_generator_node
# ---------------------------------------------------------------------------

FOLLOWUP_SYSTEM = """You are a clinical assistant helping Indian doctors communicate with patients.

Given a SOAP note's Assessment and Plan sections, generate 2-3 follow-up questions for the patient.

Rules:
1. Questions must be in simple, non-clinical language a patient can understand.
2. No medical jargon — say "blood pressure" not "hypertension", "sugar level" not "HbA1c".
3. Questions should help the doctor check if the patient is recovering/following instructions.
4. Tone: warm, friendly, caring — like a helpful clinic staff member.
5. Mix Hindi and English naturally if appropriate (Hinglish is fine).
6. Return ONLY a JSON array of question strings.

Example output for a hypertension + headache case:
["How are you feeling today? Has the headache reduced after starting the new medicine?",
 "Have you been taking your blood pressure tablet every day as prescribed?",
 "Have you checked your blood pressure at home? If yes, what was the reading?"]

Return ONLY valid JSON array, no markdown, no explanation.
"""


def followup_generator_node(state: ScribeState) -> dict:
    """
    Generate 2-3 patient-appropriate follow-up questions from SOAP Assessment + Plan.
    Also generates a <300-char WhatsApp summary for the doctor.
    """
    soap_note = state.get("soap_note", {})
    errors = list(state.get("errors", []))

    assessment = soap_note.get("assessment", {}).get("content", "")
    plan = soap_note.get("plan", {}).get("content", "")
    patient_name = state.get("patient_name") or soap_note.get("patient_name", "")

    # Generate WhatsApp summary for doctor (≤300 chars)
    subjective = soap_note.get("subjective", {}).get("content", "")
    summary_parts = []
    if patient_name:
        summary_parts.append(f"Patient: {patient_name}")
    if assessment:
        assessment_short = assessment[:80].split(".")[0]
        summary_parts.append(f"Dx: {assessment_short}")
    if plan:
        plan_short = plan[:80].split(".")[0]
        summary_parts.append(f"Rx: {plan_short}")
    summary_for_whatsapp = " | ".join(summary_parts)[:295]

    if not assessment and not plan:
        logger.warning("[followup] No assessment/plan — skipping follow-up generation")
        return {
            "follow_up_questions": [],
            "summary_for_whatsapp": summary_for_whatsapp,
            "errors": errors,
        }

    try:
        llm = _llm()
        prompt = f"Assessment:\n{assessment}\n\nPlan:\n{plan}"
        messages = [
            SystemMessage(content=FOLLOWUP_SYSTEM),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        questions = _parse_json(response.content)

        if not isinstance(questions, list):
            questions = []
        questions = [str(q) for q in questions[:3]]

        logger.info(f"[followup] Generated {len(questions)} follow-up questions")
        return {
            "follow_up_questions": questions,
            "summary_for_whatsapp": summary_for_whatsapp,
            "errors": errors,
        }

    except Exception as e:
        msg = f"Follow-up generation failed: {e}"
        logger.warning(f"[followup] {msg}")
        errors.append(msg)
        return {
            "follow_up_questions": [],
            "summary_for_whatsapp": summary_for_whatsapp,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Node 5: pdf_output_node
# ---------------------------------------------------------------------------

def pdf_output_node(state: ScribeState) -> dict:
    """
    Generate a clean, printable PDF SOAP note using reportlab.
    Returns the path to the generated PDF.
    """
    from app.graph.scribe.pdf_builder import build_soap_pdf

    soap_note = state.get("soap_note", {})
    grounding_report = state.get("grounding_report", [])
    ungrounded_flags = state.get("ungrounded_flags", [])
    missing_sections = state.get("missing_sections", [])
    transcript = state.get("transcript", "")
    doctor_name = state.get("doctor_name") or soap_note.get("doctor_name", "")
    patient_name = state.get("patient_name") or soap_note.get("patient_name", "")
    clinic_name = state.get("clinic_name", "")
    errors = list(state.get("errors", []))

    try:
        # Write to a temp file in the system temp dir
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf_path = tmp.name

        build_soap_pdf(
            output_path=pdf_path,
            soap_note=soap_note,
            transcript=transcript,
            grounding_report=grounding_report,
            ungrounded_flags=ungrounded_flags,
            missing_sections=missing_sections,
            doctor_name=doctor_name,
            patient_name=patient_name,
            clinic_name=clinic_name,
        )

        logger.info(f"[pdf] Generated SOAP PDF: {pdf_path}")
        return {"pdf_path": pdf_path, "errors": errors}

    except Exception as e:
        msg = f"PDF generation failed: {e}"
        logger.error(f"[pdf] {msg}")
        errors.append(msg)
        return {"pdf_path": "", "errors": errors}

