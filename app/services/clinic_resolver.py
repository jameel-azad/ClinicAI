import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
# Import Clinic model — use TYPE_CHECKING to avoid circular if needed

async def resolve_clinic_by_twilio_number(to_number: str, db: AsyncSession):
    """
    Given the Twilio "To" field (e.g. "whatsapp:+911234567890"),
    return the matching Clinic or None.
    Falls back to None gracefully — agents use default env-var LLM config.
    """
    from app.models.clinic import Clinic
    result = await db.execute(select(Clinic).where(Clinic.twilio_number == to_number, Clinic.is_active == True))
    return result.scalar_one_or_none()

async def resolve_model_config_for_clinic(clinic_id: str | None, db: AsyncSession):
    """Return ModelConfig for a clinic, or None if no clinic/config found."""
    if not clinic_id:
        return None
    from app.models.model_config import ModelConfig
    result = await db.execute(select(ModelConfig).where(ModelConfig.clinic_id == clinic_id))
    return result.scalar_one_or_none()
