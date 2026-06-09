from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, DateTime, JSON, ForeignKey, Float, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.doctor import Doctor

class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id: Mapped[str] = mapped_column(String, ForeignKey("clinics.id"), nullable=False, index=True)
    doctor_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("doctors.id"), nullable=True, index=True)

    visit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # record_type values: "consultation", "lab_report", "booking"

    chief_complaint: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # SOAP note sections (text)
    soap_subjective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    soap_objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    soap_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    soap_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    soap_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Structured clinical entities (from SOAP extraction)
    diagnoses: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # [{"name": "Hypertension", "snomed_code": "38341003", "severity": "mild"}]
    medications: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # [{"name": "Metformin 500mg", "rxnorm_code": "860975", "frequency": "BID"}]
    symptoms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # [{"name": "fever", "severity": "mild", "duration": "2 days"}]

    # Lab results (from lab report pipeline)
    lab_panel_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    lab_results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {all_values: [...], abnormals: [...], criticals: [...]}

    # FHIR bundle (JSON)
    fhir_bundle: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Doctor name stored as text so it shows even when doctor_id FK lookup fails
    # (e.g. env-only doctors not registered in the DB yet)
    doctor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # PDF link
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="records")
    doctor: Mapped[Optional["Doctor"]] = relationship()
