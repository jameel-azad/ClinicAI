from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.clinic import Clinic
    from app.models.patient import Patient
    from app.models.doctor import Doctor


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id", "from_number", "doctor_name", "appointment_datetime",
            name="uq_appointment_patient_doctor_time",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    clinic_id: Mapped[str] = mapped_column(
        String, ForeignKey("clinics.id"), nullable=False, index=True
    )
    patient_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("patients.id"), nullable=True, index=True
    )
    doctor_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("doctors.id"), nullable=True, index=True
    )

    from_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doctor_name: Mapped[str] = mapped_column(String(255), nullable=False)

    date_str: Mapped[str] = mapped_column(String(100), nullable=False)
    time_str: Mapped[str] = mapped_column(String(50), nullable=False)
    appointment_datetime: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )

    symptoms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)

    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reminder_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="appointments")
    patient: Mapped[Optional["Patient"]] = relationship("Patient", back_populates="appointments")
    doctor: Mapped[Optional["Doctor"]] = relationship("Doctor", back_populates="appointments")
