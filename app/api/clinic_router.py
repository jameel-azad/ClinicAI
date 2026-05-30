"""
Clinic management API router.

Prefix : /api/clinics
Tag    : clinics

Endpoints
---------
GET  /              list all clinics             (superadmin only)
GET  /{clinic_id}   get clinic detail            (admin of that clinic OR superadmin)
PUT  /{clinic_id}   update clinic fields         (admin of that clinic OR superadmin)
DELETE /{clinic_id} soft-delete (is_active=False) (superadmin only)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user, get_current_superadmin
from app.models.clinic import Clinic
from app.models.user import ClinicUser

router = APIRouter(prefix="/api/clinics", tags=["clinics"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ClinicSummary(BaseModel):
    id: str
    name: str
    timezone: str
    open_hour: int
    close_hour: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClinicDetail(ClinicSummary):
    twilio_number: str


class ClinicUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    timezone: Optional[str] = Field(None, max_length=50)
    open_hour: Optional[int] = Field(None, ge=0, le=23)
    close_hour: Optional[int] = Field(None, ge=0, le=23)


# ---------------------------------------------------------------------------
# Helper — verify caller is either admin of this clinic OR superadmin
# ---------------------------------------------------------------------------

def _require_clinic_access(clinic: Clinic, current_user: ClinicUser) -> None:
    if current_user.role == "superadmin":
        return
    if current_user.role == "admin" and current_user.clinic_id == clinic.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this clinic",
    )


# ---------------------------------------------------------------------------
# GET /  — list all clinics (superadmin only)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[ClinicSummary])
async def list_clinics(
    db: AsyncSession = Depends(get_db),
    _: ClinicUser = Depends(get_current_superadmin),
):
    result = await db.execute(select(Clinic).order_by(Clinic.created_at.desc()))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# GET /{clinic_id}  — get clinic detail
# ---------------------------------------------------------------------------

@router.get("/{clinic_id}", response_model=ClinicDetail)
async def get_clinic(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = result.scalar_one_or_none()
    if clinic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
    _require_clinic_access(clinic, current_user)
    return clinic


# ---------------------------------------------------------------------------
# PUT /{clinic_id}  — update clinic
# ---------------------------------------------------------------------------

@router.put("/{clinic_id}", response_model=ClinicDetail)
async def update_clinic(
    clinic_id: str,
    body: ClinicUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = result.scalar_one_or_none()
    if clinic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
    _require_clinic_access(clinic, current_user)

    if body.name is not None:
        clinic.name = body.name
    if body.timezone is not None:
        clinic.timezone = body.timezone
    if body.open_hour is not None:
        clinic.open_hour = body.open_hour
    if body.close_hour is not None:
        clinic.close_hour = body.close_hour

    await db.commit()
    await db.refresh(clinic)
    return clinic


# ---------------------------------------------------------------------------
# DELETE /{clinic_id}  — soft delete (superadmin only)
# ---------------------------------------------------------------------------

@router.delete("/{clinic_id}", status_code=status.HTTP_200_OK)
async def delete_clinic(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
    _: ClinicUser = Depends(get_current_superadmin),
):
    result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = result.scalar_one_or_none()
    if clinic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
    clinic.is_active = False
    await db.commit()
    return {"detail": f"Clinic {clinic_id} deactivated"}
