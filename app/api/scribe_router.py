"""
Jameel's scribe API — exposed as a proper HTTP endpoint.

POST /scribe/consult
  Accepts a consultation_bundle, runs the full SOAP pipeline,
  returns soap_note_pdf_url + follow_up_questions + summary.

This endpoint is what JAMEEL_SCRIBE_URL should point to once
this service is deployed independently. Internally, consultation_service.py
calls scribe_service.process_consultation_bundle() directly when both
services run in the same process (JAMEEL_SCRIBE_URL is empty).
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Clinical Scribe"])


# ── Request / Response schemas ────────────────────────────────────────────────

class BundleMessage(BaseModel):
    sender_role: str
    text: Optional[str] = None
    audio_url: Optional[str] = None
    duration_secs: Optional[float] = None
    timestamp: Optional[str] = None


class BundleAudioFile(BaseModel):
    url: str
    duration_secs: Optional[float] = None


class ConsultationBundleRequest(BaseModel):
    patient_id: str
    doctor_id: str
    messages: list[BundleMessage] = []
    audio_files: list[BundleAudioFile] = []


class ScribeResult(BaseModel):
    soap_note_pdf_url: Optional[str] = None
    follow_up_questions: list[str] = []
    missing_sections: list[str] = []
    summary_for_whatsapp: str = ""


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/scribe/consult", response_model=ScribeResult)
async def process_consultation(bundle: ConsultationBundleRequest):
    """
    Accept a consultation bundle and return the SOAP note result.

    This is the Jameel-side integration endpoint. Nabil's consultation_service
    POSTs here (or calls the underlying service directly) when a consultation ends.
    """
    from app.services.scribe_service import process_consultation_bundle
    result = await process_consultation_bundle(bundle.model_dump())
    return result
