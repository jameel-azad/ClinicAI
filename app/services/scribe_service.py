"""
Jameel-side clinical scribe service.

Accepts a consultation_bundle from Nabil's ConsultationAgent, downloads and
transcribes all doctor audio files, combines them with text messages into a
unified consultation transcript, runs the SOAP pipeline, and returns the
structured result matching the integration contract.

Integration contract (input):
  {
    "patient_id": "+91...",
    "doctor_id": "+91...",
    "messages": [{"sender_role", "text", "audio_url", "timestamp"}, ...],
    "audio_files": [{"url", "duration_secs"}, ...]
  }

Integration contract (output):
  {
    "soap_note_pdf_url": "https://..." | null,
    "follow_up_questions": [...],
    "missing_sections": [...],
    "summary_for_whatsapp": "..."
  }
"""

import asyncio
import os
import tempfile

import httpx
from dotenv import load_dotenv

from app.graph.scribe.nodes import (
    extract_entities_node,
    soap_generator_node,
    grounding_check_node,
    followup_generator_node,
    pdf_output_node,
    overall_soap_confidence,
    low_confidence_section_names,
)
from app.graph.scribe.state import ScribeState

load_dotenv()

_AUDIO_SUFFIXES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "application/ogg": ".ogg",
}


async def process_consultation_bundle(bundle: dict) -> dict:
    """
    Full Jameel scribe pipeline for a consultation bundle.

    1. Download all audio files (Twilio auth)
    2. Transcribe each via Groq Whisper
    3. Build combined consultation transcript (text + transcriptions, in order)
    4. SOAP generation → grounding check → follow-up questions → PDF
    5. Store PDF, return public URL + structured result
    """
    messages = bundle.get("messages", [])
    audio_files = bundle.get("audio_files", [])
    doctor_id = bundle.get("doctor_id", "")

    # ── Step 1 & 2: Download and transcribe all audio files ───────────────────
    audio_transcripts: dict[str, str] = {}
    temp_paths: list[str] = []

    for entry in audio_files:
        url = entry.get("url", "")
        if not url:
            continue
        try:
            path = await _download_audio(url)
            temp_paths.append(path)
            transcript_text = await asyncio.to_thread(_transcribe_audio, path)
            audio_transcripts[url] = transcript_text
            print(f"[ScribeService] Transcribed audio ({len(transcript_text)} chars): {url[:60]}...")
        except Exception as exc:
            print(f"[ScribeService] Transcription failed for {url[:60]}: {exc}")
            audio_transcripts[url] = ""

    # ── Step 3: Build combined consultation transcript ────────────────────────
    combined_transcript = _build_combined_transcript(messages, audio_transcripts)
    print(f"[ScribeService] Combined transcript: {len(combined_transcript)} chars, {len(messages)} messages")

    if not combined_transcript.strip():
        print("[ScribeService] Empty transcript — returning minimal result")
        _cleanup(temp_paths)
        return _empty_result()

    # ── Step 4: Run SOAP pipeline nodes ──────────────────────────────────────
    doctor_name = _resolve_doctor_name(doctor_id)
    clinic_name = os.getenv("CLINIC_NAME", "ClinicAI")

    state: ScribeState = {
        "audio_path": "",
        "transcript": combined_transcript,
        "doctor_name": doctor_name,
        "patient_name": None,
        "clinic_name": clinic_name,
        "errors": [],
    }

    state = {**state, **soap_generator_node(state)}
    state = {**state, **extract_entities_node(state)}
    state = {**state, **grounding_check_node(state)}
    state = {**state, **followup_generator_node(state)}
    state = {**state, **pdf_output_node(state)}

    pipeline_errors = state.get("errors", [])
    for err in pipeline_errors:
        print(f"[ScribeService] Pipeline error: {err}")

    # ── Step 5: Store PDF and build public URL ────────────────────────────────
    soap_note_pdf_url = None
    pdf_path = state.get("pdf_path", "")
    if pdf_path and os.path.exists(pdf_path):
        try:
            from app.services.clinical_scribe import store_scribe_pdf
            document_id, _ = store_scribe_pdf(pdf_path)
            soap_note_pdf_url = _public_pdf_url(document_id)
            print(f"[ScribeService] PDF stored: {document_id} → {soap_note_pdf_url}")
        except Exception as exc:
            print(f"[ScribeService] PDF storage failed: {exc}")

    _cleanup(temp_paths)

    soap_note = state.get("soap_note", {})
    return {
        "soap_note_pdf_url": soap_note_pdf_url,
        "follow_up_questions": state.get("follow_up_questions", []),
        "missing_sections": state.get("missing_sections", []),
        "summary_for_whatsapp": (
            state.get("summary_for_whatsapp")
            or _build_fallback_summary(state)
        ),
        "clinical_entities": state.get("clinical_entities") or {"symptoms": [], "medications": [], "diagnoses": []},
        "overall_confidence": overall_soap_confidence(soap_note),
        "low_confidence_sections": low_confidence_section_names(soap_note),
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_combined_transcript(messages: list[dict], audio_transcripts: dict[str, str]) -> str:
    """
    Merge all consultation messages into one ordered transcript.

    Each line is prefixed with the sender role so the LLM understands who said what:
      PATIENT: <text>
      DOCTOR: <spoken words from transcribed audio>
    """
    lines = []
    for msg in messages:
        role = (msg.get("sender_role") or "unknown").upper()
        text = (msg.get("text") or "").strip()
        audio_url = (msg.get("audio_url") or "").strip()

        if text:
            lines.append(f"{role}: {text}")
        elif audio_url:
            transcription = (audio_transcripts.get(audio_url) or "").strip()
            if transcription:
                lines.append(f"{role}: {transcription}")
            else:
                lines.append(f"{role}: [voice note — could not transcribe]")

    return "\n".join(lines)


def _transcribe_audio(audio_path: str) -> str:
    """Transcribe a local audio file using Groq Whisper (synchronous)."""
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    model = os.getenv("WHISPER_MODEL", "whisper-large-v3")

    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model=model,
            file=(os.path.basename(audio_path), f.read()),
            response_format="verbose_json",
            prompt=(
                "This is from a clinic consultation in India. "
                "Doctor and patient may speak English, Hindi, or Hinglish. "
                "Medical abbreviations: BP, SpO2, OD, BD, TDS, SOS, HTN, DM, IHD, CBC, ECG."
            ),
        )
    return response.text.strip()


async def _download_audio(url: str) -> str:
    """Download a Twilio media URL to a temp file and return the file path."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    auth = (account_sid, auth_token) if account_sid and auth_token else None

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, auth=auth, follow_redirects=True)
        response.raise_for_status()

    content_type = (
        response.headers.get("content-type", "audio/ogg")
        .lower()
        .split(";")[0]
        .strip()
    )
    suffix = _AUDIO_SUFFIXES.get(content_type, ".ogg")

    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)
    return path


def _resolve_doctor_name(doctor_id: str) -> str:
    try:
        from app.services.identity import find_doctor_name
        return find_doctor_name(doctor_id) or doctor_id
    except Exception:
        return doctor_id


def _public_pdf_url(document_id: str) -> str | None:
    base = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if not base:
        return None
    return f"{base}/scribe/pdf/{document_id}"


def _build_fallback_summary(state: ScribeState) -> str:
    soap = state.get("soap_note", {})
    parts = []
    assessment = soap.get("assessment", {}).get("content", "")
    plan = soap.get("plan", {}).get("content", "")
    if assessment:
        parts.append(f"Dx: {assessment[:80].split('.')[0]}")
    if plan:
        parts.append(f"Rx: {plan[:80].split('.')[0]}")
    return " | ".join(parts)[:295] or "Consultation processed. Please review the attached PDF."


def _empty_result() -> dict:
    return {
        "soap_note_pdf_url": None,
        "follow_up_questions": [],
        "missing_sections": ["subjective", "objective", "assessment", "plan"],
        "summary_for_whatsapp": "Consultation recorded but no transcript was available. Please review manually.",
    }


def _cleanup(paths: list[str]) -> None:
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
