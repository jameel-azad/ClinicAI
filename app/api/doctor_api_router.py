"""
Doctor management API router.

Prefix : /api/clinics/{clinic_id}/doctors
Tag    : doctors

Endpoints
---------
GET    /              list active doctors for the clinic   (admin of clinic OR superadmin)
POST   /              create a doctor                      (admin of clinic OR superadmin)
GET    /{doctor_id}   get doctor detail                    (admin of clinic OR superadmin)
PUT    /{doctor_id}   update doctor fields                 (admin of clinic OR superadmin)
DELETE /{doctor_id}   soft-delete (is_active=False)        (admin of clinic OR superadmin)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.user import ClinicUser


async def _sync_doctor_caches(db: AsyncSession) -> None:
    """Refresh the identity cache and Redis store whenever any doctor changes."""
    try:
        result = await db.execute(select(Doctor).where(Doctor.is_active.is_(True)))
        all_active = result.scalars().all()
        from app.services.identity import refresh_db_doctors_cache
        from app.services.doctor_directory import sync_doctors_to_store
        refresh_db_doctors_cache(all_active)
        sync_doctors_to_store(all_active)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("[doctor_api] Cache sync failed: %s", exc)

router = APIRouter(
    prefix="/api/clinics/{clinic_id}/doctors",
    tags=["doctors"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class DoctorResponse(BaseModel):
    id: str
    clinic_id: str
    name: str
    specialty: str
    whatsapp_number: str
    working_hours_start: int
    working_hours_end: int
    appointment_duration_minutes: int
    buffer_minutes: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DoctorCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    specialty: str = Field(..., max_length=100)
    whatsapp_number: str = Field(..., max_length=30)
    working_hours_start: int = Field(9, ge=0, le=23)
    working_hours_end: int = Field(18, ge=0, le=23)
    appointment_duration_minutes: int = Field(30, ge=5, le=480)
    buffer_minutes: int = Field(5, ge=0, le=60)


class DoctorUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    specialty: Optional[str] = Field(None, max_length=100)
    whatsapp_number: Optional[str] = Field(None, max_length=30)
    working_hours_start: Optional[int] = Field(None, ge=0, le=23)
    working_hours_end: Optional[int] = Field(None, ge=0, le=23)
    appointment_duration_minutes: Optional[int] = Field(None, ge=5, le=480)
    buffer_minutes: Optional[int] = Field(None, ge=0, le=60)


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


async def _get_doctor_or_404(doctor_id: str, clinic_id: str, db: AsyncSession) -> Doctor:
    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id)
    )
    doctor = result.scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")
    return doctor


# ---------------------------------------------------------------------------
# GET /  — list active doctors
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[DoctorResponse])
async def list_doctors(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)

    result = await db.execute(
        select(Doctor)
        .where(Doctor.clinic_id == clinic_id, Doctor.is_active.is_(True))
        .order_by(Doctor.created_at)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# POST /  — create doctor
# ---------------------------------------------------------------------------

@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    clinic_id: str,
    body: DoctorCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)

    doctor = Doctor(
        id=str(uuid4()),
        clinic_id=clinic_id,
        name=body.name,
        specialty=body.specialty,
        whatsapp_number=body.whatsapp_number,
        working_hours_start=body.working_hours_start,
        working_hours_end=body.working_hours_end,
        appointment_duration_minutes=body.appointment_duration_minutes,
        buffer_minutes=body.buffer_minutes,
    )
    db.add(doctor)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A doctor with this WhatsApp number already exists in this clinic.",
        )
    await db.refresh(doctor)
    await _sync_doctor_caches(db)
    return doctor


# ---------------------------------------------------------------------------
# GET /{doctor_id}  — get doctor detail
# ---------------------------------------------------------------------------

@router.get("/{doctor_id}", response_model=DoctorResponse)
async def get_doctor(
    clinic_id: str,
    doctor_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    return await _get_doctor_or_404(doctor_id, clinic_id, db)


# ---------------------------------------------------------------------------
# PUT /{doctor_id}  — update doctor
# ---------------------------------------------------------------------------

@router.put("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    clinic_id: str,
    doctor_id: str,
    body: DoctorUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    doctor = await _get_doctor_or_404(doctor_id, clinic_id, db)

    if body.name is not None:
        doctor.name = body.name
    if body.specialty is not None:
        doctor.specialty = body.specialty
    if body.whatsapp_number is not None:
        doctor.whatsapp_number = body.whatsapp_number
    if body.working_hours_start is not None:
        doctor.working_hours_start = body.working_hours_start
    if body.working_hours_end is not None:
        doctor.working_hours_end = body.working_hours_end
    if body.appointment_duration_minutes is not None:
        doctor.appointment_duration_minutes = body.appointment_duration_minutes
    if body.buffer_minutes is not None:
        doctor.buffer_minutes = body.buffer_minutes

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A doctor with this WhatsApp number already exists in this clinic.",
        )
    await db.refresh(doctor)
    await _sync_doctor_caches(db)
    return doctor


# ---------------------------------------------------------------------------
# DELETE /{doctor_id}  — soft delete
# ---------------------------------------------------------------------------

@router.delete("/{doctor_id}", status_code=status.HTTP_200_OK)
async def delete_doctor(
    clinic_id: str,
    doctor_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_user),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    doctor = await _get_doctor_or_404(doctor_id, clinic_id, db)
    doctor.is_active = False
    await db.commit()
    await _sync_doctor_caches(db)
    return {"detail": f"Doctor {doctor_id} deactivated"}
