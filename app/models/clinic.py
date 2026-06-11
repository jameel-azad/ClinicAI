from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.appointment import Appointment


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    twilio_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata", nullable=False)
    open_hour: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    close_hour: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    users: Mapped[List["ClinicUser"]] = relationship("ClinicUser", back_populates="clinic")
    doctors: Mapped[List["Doctor"]] = relationship("Doctor", back_populates="clinic")
    model_config: Mapped[Optional["ModelConfig"]] = relationship(
        "ModelConfig", back_populates="clinic", uselist=False
    )
    patients: Mapped[List["Patient"]] = relationship(back_populates="clinic")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="clinic")
