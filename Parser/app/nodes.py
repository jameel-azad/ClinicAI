"""
app/nodes.py — Individual LangGraph node functions for the lab report pipeline.

Each function takes the current ReportState and returns a dict of updates.
LangGraph merges these updates into the shared state automatically.

Node order:
  1. extract_text_node    — PDF → raw text (pdfplumber)
  2. extract_all_node     — raw text → patient info + test values (single LLM call)
  3. flag_abnormals_node  — rule-based HIGH/LOW flagging (no LLM)
  4. generate_summary_node — abnormals → critical classification + summary (single LLM call)
"""

import json
import logging
import re
from typing import Any

import pdfplumber
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from Parser.app.state import ReportState, PatientInfo, TestValue

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm(model: str = None) -> ChatGroq:
    """Return a ChatGroq instance. Model is pulled from env if not given."""
    import os
    m = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return ChatGroq(
        model=m,
        temperature=0,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


def _parse_json_response(text: str) -> Any:
    """
    Safely parse JSON from an LLM response.
    Handles markdown code fences (```json ... ```) the model sometimes adds.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = text.rstrip("`").strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Node 1: extract_text_node
# ---------------------------------------------------------------------------

def extract_text_node(state: ReportState) -> dict:
    """
    Use pdfplumber to extract all text from the PDF.

    Returns raw concatenated text from all pages.
    If extraction fails, stores an error and returns empty string
    so downstream nodes degrade gracefully instead of crashing.
    """
    pdf_path = state["pdf_path"]
    errors = list(state.get("errors", []))

    try:
        pages_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Try table extraction first (structured reports)
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if row:
                                pages_text.append(" | ".join(
                                    cell.strip() if cell else ""
                                    for cell in row
                                ))
                # Always also get plain text (catches header/footer info)
                plain = page.extract_text()
                if plain:
                    pages_text.append(plain)

        raw_text = "\n".join(pages_text)
        logger.info(f"[extract_text] Extracted {len(raw_text)} chars from {pdf_path}")
        return {"raw_text": raw_text, "errors": errors}

    except Exception as e:
        msg = f"PDF extraction failed: {e}"
        logger.error(f"[extract_text] {msg}")
        errors.append(msg)
        return {"raw_text": "", "errors": errors}


# ---------------------------------------------------------------------------
# Node 2: extract_all_node  (MERGED — patient info + test values in 1 call)
# ---------------------------------------------------------------------------

EXTRACT_ALL_SYSTEM = """You are a medical document parser specialised in lab reports.

From the raw text of a lab report, extract TWO things in a single JSON response:
1. Patient demographic information
2. All test parameters with their values

Return ONLY valid JSON (no markdown, no preamble) matching this schema:
{
  "patient_info": {
    "name": "<full patient name or empty string>",
    "age": "<age as string, e.g. '34' or '34 years' or empty>",
    "gender": "<Male | Female | Other | empty>",
    "dob": "<date of birth if present, else empty>",
    "patient_id": "<patient/lab/sample ID if present, else empty>",
    "lab_name": "<diagnostic laboratory name if present, else empty>",
    "report_date": "<report generation date if present, else empty>",
    "referring_doctor": "<referring doctor name if present, else empty>"
  },
  "test_values": [
    {
      "parameter": "<test name>",
      "value": "<numeric or text result>",
      "unit": "<unit of measurement>",
      "reference_range": "<normal range as shown in report>"
    }
  ]
}

Rules:
- If a patient field cannot be found, return empty string.
- Do NOT invent or hallucinate values.
- Gender: normalise to 'Male', 'Female', or 'Other'.
- Include EVERY test row, even if value is 'Not Done' or '-'.
- If reference range is missing, use empty string.
- Handle both tabular and free-text formats.
"""


def extract_all_node(state: ReportState) -> dict:
    """
    Single LLM call to extract both patient demographics and test values.
    Replaces the old separate extract_patient_info + extract_test_values nodes.
    """
    raw_text = state.get("raw_text", "")
    errors = list(state.get("errors", []))

    # Fallback if no text
    if not raw_text:
        errors.append("No raw text to extract from.")
        patient_info: PatientInfo = {
            "name": state.get("patient_name_hint") or "",
            "age": state.get("patient_age_hint") or "",
            "gender": state.get("patient_gender_hint") or "",
            "dob": "", "patient_id": "", "lab_name": "",
            "report_date": "", "referring_doctor": "",
        }
        return {"patient_info": patient_info, "all_values": [], "errors": errors}

    try:
        llm = _llm()
        chunk = raw_text[:6000]
        messages = [
            SystemMessage(content=EXTRACT_ALL_SYSTEM),
            HumanMessage(content=f"Lab report text:\n\n{chunk}"),
        ]
        response = llm.invoke(messages)
        result: dict = _parse_json_response(response.content)

        # Parse patient info with hint merging
        pi = result.get("patient_info", {})
        patient_info: PatientInfo = {
            "name": pi.get("name") or state.get("patient_name_hint") or "",
            "age": pi.get("age") or state.get("patient_age_hint") or "",
            "gender": pi.get("gender") or state.get("patient_gender_hint") or "",
            "dob": pi.get("dob") or "",
            "patient_id": pi.get("patient_id") or "",
            "lab_name": pi.get("lab_name") or "",
            "report_date": pi.get("report_date") or "",
            "referring_doctor": pi.get("referring_doctor") or "",
        }

        # Parse test values
        raw_values = result.get("test_values", [])
        all_values: list[TestValue] = []
        for row in raw_values:
            all_values.append({
                "parameter": str(row.get("parameter", "")),
                "value": str(row.get("value", "")),
                "unit": str(row.get("unit", "")),
                "reference_range": str(row.get("reference_range", "")),
                "status": "PENDING",
            })

        logger.info(
            f"[extract_all] Patient: {patient_info.get('name')}, "
            f"{len(all_values)} test values extracted"
        )
        return {"patient_info": patient_info, "all_values": all_values, "errors": errors}

    except Exception as e:
        msg = f"Combined extraction failed: {e}"
        logger.error(f"[extract_all] {msg}")
        errors.append(msg)
        patient_info = {
            "name": state.get("patient_name_hint") or "",
            "age": state.get("patient_age_hint") or "",
            "gender": state.get("patient_gender_hint") or "",
            "dob": "", "patient_id": "", "lab_name": "",
            "report_date": "", "referring_doctor": "",
        }
        return {"patient_info": patient_info, "all_values": [], "errors": errors}


# ---------------------------------------------------------------------------
# Node 3: flag_abnormals_node  (pure Python — no LLM)
# ---------------------------------------------------------------------------

def _parse_range(reference_range: str) -> tuple[float | None, float | None]:
    """
    Parse a reference range string into (low, high) floats.

    Handles formats like:
      '13.0-17.0', '< 5.0', '> 3.5', '3.5 - 5.0', 'Up to 40'
    Returns (None, None) if unparseable.
    """
    if not reference_range:
        return None, None

    ref = reference_range.strip()

    # Pattern: low-high (e.g. 13.0-17.0)
    m = re.match(r"^([\d.]+)\s*[-–]\s*([\d.]+)$", ref)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Pattern: < X or up to X
    m = re.match(r"^(?:<|up to|upto)\s*([\d.]+)$", ref, re.I)
    if m:
        return None, float(m.group(1))

    # Pattern: > X
    m = re.match(r"^>\s*([\d.]+)$", ref)
    if m:
        return float(m.group(1)), None

    return None, None


def _flag_value(value_str: str, reference_range: str) -> str:
    """
    Determine status for a single test value based on reference range.

    Returns: NORMAL | HIGH | LOW
    """
    try:
        val = float(re.sub(r"[^\d.]", "", value_str))
    except (ValueError, TypeError):
        return "NORMAL"  # can't compare non-numeric

    low, high = _parse_range(reference_range)

    if low is not None and val < low:
        return "LOW"
    if high is not None and val > high:
        return "HIGH"

    return "NORMAL"


def flag_abnormals_node(state: ReportState) -> dict:
    """
    Pure rule-based flagging — no LLM call.
    Compares each value against its reference range → NORMAL / HIGH / LOW.
    Builds the abnormals subset. Criticals are classified in the summary node.
    """
    all_values: list[TestValue] = list(state.get("all_values", []))
    errors = list(state.get("errors", []))

    flagged: list[TestValue] = []
    abnormals: list[TestValue] = []

    for tv in all_values:
        status = _flag_value(tv["value"], tv["reference_range"])
        updated = dict(tv)
        updated["status"] = status
        flagged.append(updated)
        if status in ("HIGH", "LOW"):
            abnormals.append(updated)

    logger.info(
        f"[flag_abnormals] {len(abnormals)} abnormals out of {len(flagged)} values"
    )

    return {
        "all_values": flagged,
        "abnormals": abnormals,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Node 4: generate_summary_node  (MERGED — criticals + summary in 1 call)
# ---------------------------------------------------------------------------

SUMMARY_AND_CRITICALS_SYSTEM = """You are a clinical assistant. You will receive patient info and a list of abnormal lab values.

Do TWO things and return as JSON (no markdown, no preamble):

1. Identify which abnormal values are CRITICAL — panic values posing immediate clinical danger.
2. Write a brief doctor summary (3-5 sentences).

Return ONLY this JSON:
{
  "criticals": [
    {"parameter": "<exact parameter name>", "reason": "<brief clinical reason>"}
  ],
  "summary": "<3-5 sentence plain-English summary for a doctor>"
}

Critical rules:
- CRITICAL = immediate clinical danger (like severe anaemia, life-threatening electrolyte imbalance, organ failure).
- Mildly abnormal values are NOT critical. Be conservative.
- If no criticals, return empty list.

Summary rules:
- Lead with: 'Patient [name], [age][gender].'
- Mention important abnormals with actual numbers along with reference ranges.
- Call out critical values explicitly if any.
- End with 'No critical values.' if none.
- No bullet points, no markdown. Plain English only.
"""


def generate_summary_node(state: ReportState) -> dict:
    """
    Single LLM call that classifies criticals AND generates the doctor summary.
    Replaces the old separate critical assessment + summary nodes.
    """
    patient_info = state.get("patient_info", {})
    abnormals = state.get("abnormals", [])
    all_values = state.get("all_values", [])
    errors = list(state.get("errors", []))

    name = patient_info.get("name") or "Unknown patient"
    age = patient_info.get("age") or "?"
    gender = patient_info.get("gender") or ""
    gender_abbr = "M" if gender.lower().startswith("m") else ("F" if gender.lower().startswith("f") else gender)

    # Build concise context
    context_lines = [
        f"Patient: {name}, {age}{gender_abbr}",
        f"Lab: {patient_info.get('lab_name', 'Unknown')}",
        f"Report date: {patient_info.get('report_date', 'Unknown')}",
        f"Total tests: {len(all_values)}",
    ]

    if abnormals:
        context_lines.append(f"Abnormal values ({len(abnormals)}):")
        for ab in abnormals:
            context_lines.append(
                f"  - {ab['parameter']}: {ab['value']} {ab['unit']} "
                f"(ref: {ab['reference_range']}) [{ab['status']}]"
            )
    else:
        context_lines.append("All values within reference range.")

    context = "\n".join(context_lines)

    try:
        llm = _llm()
        messages = [
            SystemMessage(content=SUMMARY_AND_CRITICALS_SYSTEM),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        result: dict = _parse_json_response(response.content)

        # Extract criticals
        critical_params = result.get("criticals", [])
        critical_map = {c["parameter"]: c.get("reason", "Critical value") for c in critical_params}

        # Upgrade abnormals to CRITICAL where applicable
        criticals: list[TestValue] = []
        for tv in all_values:
            if tv["parameter"] in critical_map:
                tv["status"] = "CRITICAL"
        for tv in abnormals:
            if tv["parameter"] in critical_map:
                tv["status"] = "CRITICAL"
                tv["critical_reason"] = critical_map[tv["parameter"]]
                criticals.append(tv)

        summary = result.get("summary", "Summary unavailable.")

        logger.info(f"[summary] {len(criticals)} criticals. Summary: {summary[:80]}...")
        return {
            "all_values": all_values,
            "criticals": criticals,
            "doctor_summary": summary,
            "errors": errors,
        }

    except Exception as e:
        msg = f"Summary generation failed: {e}"
        logger.error(f"[summary] {msg}")
        errors.append(msg)
        fallback = f"Patient {name}, {age}{gender_abbr}. "
        if abnormals:
            fallback += f"{len(abnormals)} abnormal value(s) found. "
        else:
            fallback += "All values within reference range. "
        return {
            "all_values": all_values,
            "criticals": [],
            "doctor_summary": fallback,
            "errors": errors,
        }
