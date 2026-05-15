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
from Parser.app.prompts import EXTRACT_ALL_SYSTEM, SUMMARY_AND_CRITICALS_SYSTEM

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
    Handles markdown code fences and conversational preambles.
    """
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        text = match.group(1)
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
            for page in pdf.pages:
                # Use layout=True to preserve spatial arrangement and avoid duplicate table text
                plain = page.extract_text(layout=True)
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
# Node 2: extract_all_node
# ---------------------------------------------------------------------------


def extract_all_node(state: ReportState) -> dict:
    """
    Single LLM call to extract both patient demographics and test values.
    """
    raw_text = state.get("raw_text", "")
    errors = list(state.get("errors", []))

    # Fallback if no text
    if not raw_text:
        errors.append("No raw text to extract from.")
        patient_info: PatientInfo = {
            "name": state.get("patient_name") or "",
            "age": state.get("patient_age") or "",
            "gender": state.get("patient_gender") or "",
            "dob": "", "patient_id": "", "lab_name": "",
            "report_date": "", "referring_doctor": "",
        }
        return {"patient_info": patient_info, "all_values": [], "errors": errors}

    try:
        llm = _llm()
        chunk = raw_text[:6000]
        messages = [
            SystemMessage(content=EXTRACT_ALL_SYSTEM),
            HumanMessage(content=f"--- BEGIN UNTRUSTED LAB REPORT ---\n{chunk}\n--- END UNTRUSTED LAB REPORT ---"),
        ]
        response = llm.invoke(messages)
        result: dict = _parse_json_response(response.content)

        # Parse patient info with hint merging
        pi = result.get("patient_info", {})
        patient_info: PatientInfo = {
            "name": pi.get("name") or state.get("patient_name") or "",
            "age": pi.get("age") or state.get("patient_age") or "",
            "gender": pi.get("gender") or state.get("patient_gender") or "",
            "dob": pi.get("dob") or "",
            "patient_id": pi.get("patient_id") or "",
            "lab_name": pi.get("lab_name") or "",
            "report_date": pi.get("report_date") or "",
            "referring_doctor": pi.get("referring_doctor") or "",
        }

        # Parse test values safely
        raw_values = result.get("test_values", [])
        if not isinstance(raw_values, list):
            raw_values = []
            
        all_values: list[TestValue] = []
        for row in raw_values:
            if not isinstance(row, dict):
                continue
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
            "name": state.get("patient_name") or "",
            "age": state.get("patient_age") or "",
            "gender": state.get("patient_gender") or "",
            "dob": "", "patient_id": "", "lab_name": "",
            "report_date": "", "referring_doctor": "",
        }
        return {"patient_info": patient_info, "all_values": [], "errors": errors}


# ---------------------------------------------------------------------------
# Node 3: flag_abnormals_node 
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
# Node 4: generate_summary_node
# ---------------------------------------------------------------------------

def generate_summary_node(state: ReportState) -> dict:
    """
    Single LLM call that classifies criticals AND generates the doctor summary.
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
            HumanMessage(content=f"--- BEGIN UNTRUSTED CONTEXT ---\n{context}\n--- END UNTRUSTED CONTEXT ---"),
        ]
        response = llm.invoke(messages)
        result: dict = _parse_json_response(response.content)

        # Extract criticals safely
        critical_params = result.get("criticals", [])
        if not isinstance(critical_params, list):
            critical_params = []
            
        critical_map = {}
        for c in critical_params:
            if isinstance(c, dict) and "parameter" in c:
                critical_map[c["parameter"]] = c.get("reason", "Critical value")

        # Upgrade values to CRITICAL safely using new lists
        new_all_values: list[TestValue] = []
        criticals: list[TestValue] = []
        
        for tv in all_values:
            updated_tv = dict(tv)
            if updated_tv["parameter"] in critical_map:
                updated_tv["status"] = "CRITICAL"
                updated_tv["critical_reason"] = critical_map[updated_tv["parameter"]]
                criticals.append(updated_tv)
            new_all_values.append(updated_tv)
            
        new_abnormals: list[TestValue] = []
        for ab in abnormals:
            updated_ab = dict(ab)
            if updated_ab["parameter"] in critical_map:
                updated_ab["status"] = "CRITICAL"
                updated_ab["critical_reason"] = critical_map[updated_ab["parameter"]]
            new_abnormals.append(updated_ab)

        summary = result.get("summary", "Summary unavailable.")

        logger.info(f"[summary] {len(criticals)} criticals. Summary: {summary[:80]}...")
        return {
            "all_values": new_all_values,
            "abnormals": new_abnormals,
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
