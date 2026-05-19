"""
app/api/parser_router.py — APIRouter for Lab Report Parser.

Endpoints:
  POST /parser/parse-report   — Main endpoint: PDF in, structured JSON out
  GET  /parser/health         — Health check
"""

import logging
import os
import tempfile
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load .env before anything else
load_dotenv()

from app.graph.parser.pipeline import lab_report_pipeline
from app.graph.parser.state import ReportState

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------
router = APIRouter(tags=["Parser"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PatientInfoResponse(BaseModel):
    name: str = ""
    age: str = ""
    gender: str = ""
    dob: str = ""
    patient_id: str = ""
    lab_name: str = ""
    report_date: str = ""
    referring_doctor: str = ""


class TestValueResponse(BaseModel):
    parameter: str
    value: str
    unit: str
    reference_range: str
    status: str  # NORMAL | HIGH | LOW | CRITICAL


class ParseReportResponse(BaseModel):
    patient_info: PatientInfoResponse
    all_values: list[TestValueResponse]
    abnormals: list[TestValueResponse]
    criticals: list[TestValueResponse]
    doctor_summary: str
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/parser/health")
def parser_health():
    api_key_set = bool(os.getenv("GROQ_API_KEY"))
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return {
        "status": "ok",
        "groq_api_key_configured": api_key_set,
        "model": model,
    }


@router.post("/parser/parse-report", response_model=ParseReportResponse)
async def parse_report(
    pdf_file: UploadFile = File(..., description="Lab report PDF file"),
    patient_name: Optional[str] = Form(None, description="Patient name (optional override)"),
    patient_age: Optional[str] = Form(None, description="Patient age (optional override)"),
    patient_gender: Optional[str] = Form(None, description="Patient gender (optional override)"),
):
    """
    Parse a lab report PDF and return structured extraction results.

    - Extracts patient demographics (name, age, gender, DOB, patient ID, lab name, report date, referring doctor)
    - Extracts all test values with reference ranges
    - Flags abnormals (HIGH/LOW) and criticals
    - Generates a plain-English doctor summary (3-5 sentences)
    """
    # Validate file type
    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not set. Please configure it in .env",
        )

    tmp_path = None
    # Save uploaded file to a temp path (LangGraph node reads from disk)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await pdf_file.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    try:
        logger.info(
            f"Processing report: {pdf_file.filename} "
            f"(name: {patient_name}, age: {patient_age}, gender: {patient_gender})"
        )

        # Build initial state
        initial_state: ReportState = {
            "pdf_path": tmp_path,
            "patient_name": patient_name,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "errors": [],
        }

        # Run the LangGraph pipeline
        result: ReportState = lab_report_pipeline.invoke(initial_state)

        # Build response
        patient_info = result.get("patient_info", {})
        all_values = result.get("all_values", [])
        abnormals = result.get("abnormals", [])
        criticals = result.get("criticals", [])
        doctor_summary = result.get("doctor_summary", "Summary unavailable.")
        warnings = result.get("errors", [])

        logger.info(
            f"Completed: {len(all_values)} values, "
            f"{len(abnormals)} abnormals, {len(criticals)} criticals"
        )

        return ParseReportResponse(
            patient_info=PatientInfoResponse(**patient_info),
            all_values=[TestValueResponse(**v) for v in all_values],
            abnormals=[TestValueResponse(**v) for v in abnormals],
            criticals=[TestValueResponse(**v) for v in criticals],
            doctor_summary=doctor_summary,
            warnings=warnings,
        )

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    finally:
        # Always clean up temp file
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
