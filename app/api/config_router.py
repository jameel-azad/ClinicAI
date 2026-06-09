"""
Model config management API router.

Prefix : /api/clinics/{clinic_id}/config
Tag    : config

Endpoints
---------
GET  /       get current model config — API keys masked as boolean flags
PUT  /       update model config; encrypts any provided API key values before storage
POST /test   test LLM connectivity with the saved configuration
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
from app.models.clinic import Clinic
from app.models.model_config import ModelConfig
from app.models.user import ClinicUser
from app.services.llm_factory import encrypt_api_key, test_llm_connection

_audit = logging.getLogger("audit.model_config")

router = APIRouter(
    prefix="/api/clinics/{clinic_id}/config",
    tags=["config"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ModelConfigResponse(BaseModel):
    """API keys are never returned — only a boolean indicating whether each is set."""
    id: str
    clinic_id: str
    llm_vendor: str
    llm_model: str
    stt_vendor: str
    stt_model: str
    groq_api_key_set: bool
    anthropic_api_key_set: bool
    openai_api_key_set: bool
    google_api_key_set: bool


class ModelConfigUpdateRequest(BaseModel):
    llm_vendor: Optional[str] = Field(None, max_length=20)
    llm_model: Optional[str] = Field(None, max_length=100)
    stt_vendor: Optional[str] = Field(None, max_length=20)
    stt_model: Optional[str] = Field(None, max_length=100)
    # API key fields — only stored when a non-empty value is provided.
    groq_api_key: Optional[str] = Field(None, description="Plain-text Groq API key; will be encrypted before storage")
    anthropic_api_key: Optional[str] = Field(None, description="Plain-text Anthropic API key; will be encrypted before storage")
    openai_api_key: Optional[str] = Field(None, description="Plain-text OpenAI API key; will be encrypted before storage")
    google_api_key: Optional[str] = Field(None, description="Plain-text Google/Gemini API key; will be encrypted before storage")


class LLMTestResponse(BaseModel):
    success: bool
    response: str
    latency_ms: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_clinic_or_404(clinic_id: str, db: AsyncSession) -> Clinic:
    result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = result.scalar_one_or_none()
    if clinic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
    return clinic


def _require_clinic_access(clinic: Clinic, current_user: ClinicUser) -> None:
    if current_user.role == "superadmin":
        return
    if current_user.role == "admin" and current_user.clinic_id == clinic.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this clinic",
    )


def _config_to_response(cfg: ModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        id=cfg.id,
        clinic_id=cfg.clinic_id,
        llm_vendor=cfg.llm_vendor,
        llm_model=cfg.llm_model,
        stt_vendor=cfg.stt_vendor,
        stt_model=cfg.stt_model,
        groq_api_key_set=bool(cfg.groq_api_key_enc),
        anthropic_api_key_set=bool(cfg.anthropic_api_key_enc),
        openai_api_key_set=bool(cfg.openai_api_key_enc),
        google_api_key_set=bool(cfg.google_api_key_enc),
    )


async def _get_or_create_config(clinic_id: str, db: AsyncSession) -> ModelConfig:
    result = await db.execute(select(ModelConfig).where(ModelConfig.clinic_id == clinic_id))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = ModelConfig(id=str(uuid4()), clinic_id=clinic_id)
        db.add(cfg)
        await db.flush()
    return cfg


# ---------------------------------------------------------------------------
# GET /  — get masked config
# ---------------------------------------------------------------------------

@router.get("/", response_model=ModelConfigResponse)
async def get_model_config(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    cfg = await _get_or_create_config(clinic_id, db)
    await db.commit()
    return _config_to_response(cfg)


# ---------------------------------------------------------------------------
# PUT /  — update config (encrypts API keys before storage)
# ---------------------------------------------------------------------------

@router.put("/", response_model=ModelConfigResponse)
async def update_model_config(
    clinic_id: str,
    body: ModelConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    cfg = await _get_or_create_config(clinic_id, db)

    if body.llm_vendor is not None:
        cfg.llm_vendor = body.llm_vendor
    if body.llm_model is not None:
        cfg.llm_model = body.llm_model
    if body.stt_vendor is not None:
        cfg.stt_vendor = body.stt_vendor
    if body.stt_model is not None:
        cfg.stt_model = body.stt_model

    # Only encrypt and update a key when a non-empty value is supplied.
    keys_updated: list[str] = []
    if body.groq_api_key and body.groq_api_key.strip():
        cfg.groq_api_key_enc = encrypt_api_key(body.groq_api_key.strip())
        keys_updated.append("groq")
    if body.anthropic_api_key and body.anthropic_api_key.strip():
        cfg.anthropic_api_key_enc = encrypt_api_key(body.anthropic_api_key.strip())
        keys_updated.append("anthropic")
    if body.openai_api_key and body.openai_api_key.strip():
        cfg.openai_api_key_enc = encrypt_api_key(body.openai_api_key.strip())
        keys_updated.append("openai")
    if body.google_api_key and body.google_api_key.strip():
        cfg.google_api_key_enc = encrypt_api_key(body.google_api_key.strip())
        keys_updated.append("google")

    await db.commit()
    await db.refresh(cfg)

    _audit.info(
        "model_config_updated clinic_id=%s user=%s vendor=%s model=%s keys_rotated=%s",
        clinic_id,
        current_user.email,
        cfg.llm_vendor,
        cfg.llm_model,
        keys_updated or "none",
    )

    return _config_to_response(cfg)


# ---------------------------------------------------------------------------
# POST /test  — test LLM connectivity
# ---------------------------------------------------------------------------

@router.post("/test", response_model=LLMTestResponse)
async def test_config(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)

    result = await db.execute(select(ModelConfig).where(ModelConfig.clinic_id == clinic_id))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model config found for this clinic. Create one via PUT /config first.",
        )

    result = await test_llm_connection(
        vendor=cfg.llm_vendor,
        model=cfg.llm_model,
        groq_api_key_enc=cfg.groq_api_key_enc,
        anthropic_api_key_enc=cfg.anthropic_api_key_enc,
        openai_api_key_enc=cfg.openai_api_key_enc,
        google_api_key_enc=cfg.google_api_key_enc,
    )
    return LLMTestResponse(**result)
