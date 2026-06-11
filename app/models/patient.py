from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, UniqueConstraint, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
if TYPE_CHECKING:
    from app.models.clinic import Clinic
    from app.models.medical_record import MedicalRecord
    from app.models.appointment import Appointment

class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("clinic_id", "phone_number", name="uq_patient_clinic_phone"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    clinic_id: Mapped[str] = mapped_column(String, ForeignKey("clinics.id"), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # male/female/other
    blood_group: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # A+, B-, O+, etc.

    # JSON arrays stored as text — allergies and chronic conditions
    allergies: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    chronic_conditions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    current_medications: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)

    # Doctor's free-text notes about this patient
    doctor_notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_visit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    clinic: Mapped["Clinic"] = relationship(back_populates="patients")
    records: Mapped[list["MedicalRecord"]] = relationship(back_populates="patient", order_by="desc(MedicalRecord.visit_date)")
    appointments: Mapped[list["Appointment"]] = relationship("Appointment", back_populates="patient")
