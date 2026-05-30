from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    clinic_id: Mapped[str] = mapped_column(
        String, ForeignKey("clinics.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    whatsapp_number: Mapped[str] = mapped_column(String(30), nullable=False)
    working_hours_start: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    working_hours_end: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    appointment_duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="doctors")
