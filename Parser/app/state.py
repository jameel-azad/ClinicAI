"""
app/state.py — Shared state schema for the LangGraph lab report pipeline.

Each node reads from and writes to this TypedDict. LangGraph threads
the state object through the graph automatically.
"""

from typing import Optional
from typing_extensions import TypedDict


class PatientInfo(TypedDict, total=False):
    """Demographic information extracted from the lab report header."""
    name: str
    age: str
    gender: str
    dob: str               # Date of birth if present
    patient_id: str        # Lab / hospital patient ID
    lab_name: str          # Name of the diagnostic lab
    report_date: str       # Date the report was generated
    referring_doctor: str  # Referring / ordering physician


class TestValue(TypedDict):
    """A single lab test result row."""
    parameter: str         # e.g. "Haemoglobin"
    value: str             # e.g. "9.2"
    unit: str              # e.g. "g/dL"
    reference_range: str   # e.g. "13.0-17.0"
    status: str            # "NORMAL" | "HIGH" | "LOW" | "CRITICAL"


class ReportState(TypedDict, total=False):
    """
    Full state object passed through the LangGraph pipeline.

    Nodes add their outputs here; downstream nodes read upstream outputs.
    """
    # --- Inputs ---
    pdf_path: str                        # Path to the uploaded PDF
    patient_name_hint: Optional[str]    # Optional override from API caller
    patient_age_hint: Optional[str]
    patient_gender_hint: Optional[str]

    # --- Node outputs ---
    raw_text: str                        # Raw text extracted from PDF pages
    patient_info: PatientInfo            # Demographics extracted by LLM

    all_values: list[TestValue]          # All test rows
    abnormals: list[TestValue]           # Subset: HIGH or LOW
    criticals: list[TestValue]           # Subset: CRITICAL flags

    doctor_summary: str                  # Plain-English 3-5 sentence summary

    # --- Error tracking ---
    errors: list[str]                    # Non-fatal warnings accumulated
