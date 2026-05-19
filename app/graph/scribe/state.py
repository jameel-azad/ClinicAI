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
    transcript: str
    language_detected: str
    soap_note: dict
    missing_sections: list[str]
    ungrounded_flags: list[str]
    grounding_report: list[GroundingEntry]
    pdf_path: str
    errors: list[str]
