from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    clinic_id: Mapped[str] = mapped_column(
        String, ForeignKey("clinics.id"), unique=True, nullable=False
    )
    llm_vendor: Mapped[str] = mapped_column(String(20), default="groq", nullable=False)
    llm_model: Mapped[str] = mapped_column(
        String(100), default="llama-3.3-70b-versatile", nullable=False
    )
    stt_vendor: Mapped[str] = mapped_column(String(20), default="groq", nullable=False)
    stt_model: Mapped[str] = mapped_column(
        String(100), default="whisper-large-v3-turbo", nullable=False
    )
    groq_api_key_enc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    anthropic_api_key_enc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    openai_api_key_enc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    google_api_key_enc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationship
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="model_config")
