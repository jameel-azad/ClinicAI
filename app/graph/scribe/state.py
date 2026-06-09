from typing import Optional
from typing_extensions import TypedDict


class SOAPSection(TypedDict, total=False):
    content: str
    confidence: float
    is_missing: bool
    clarifying_question: str


class GroundingEntry(TypedDict):
    sentence: str
    transcript_segment: str
    is_grounded: bool


class ScribeState(TypedDict, total=False):
    audio_path: str
    doctor_name: Optional[str]
    patient_name: Optional[str]
    clinic_name: Optional[str]
    # Per-clinic API keys (encrypted); None → fall back to env vars
    llm_enc_key: Optional[str]
    stt_enc_key: Optional[str]
    transcript: str
    language_detected: str
    soap_note: dict
    missing_sections: list[str]
    ungrounded_flags: list[str]
    grounding_report: list[GroundingEntry]
    follow_up_questions: list[str]     # 2-3 patient-appropriate follow-up questions
    follow_up_days: Optional[int]      # days until follow-up (None = not mentioned by doctor)
    summary_for_whatsapp: Optional[str]  # <300 chars for WhatsApp delivery to doctor
    clinical_entities: Optional[dict]   # {symptoms:[...], medications:[...], diagnoses:[...]}
    fhir_bundle: Optional[dict]         # HL7 FHIR R4 Bundle resource (collection)
    snomed_mappings: Optional[list]     # [{clinical_term, snomed_concept_id, snomed_fsn, fhir_resource_type}]
    fhir_validation_errors: list[str]  # structural FHIR validation failures (non-blocking)
    pdf_path: str
    errors: list[str]
