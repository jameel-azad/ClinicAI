"""
Appointment management API router.

Prefix : /api/clinics/{clinic_id}/appointments
Tag    : appointments

Endpoints
---------
GET  /                           list appointments (filters: status, doctor_name, from_date, to_date)
GET  /{appointment_id}           get single appointment detail
PUT  /{appointment_id}           update appointment status (admin cancel/complete)
GET  /patient/{patient_id}       all appointments for a specific patient
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin, get_db
from app.models.appointment import Appointment
from app.models.patient import Patient

router = APIRouter(
    prefix="/api/clinics/{clinic_id}/appointments",
    tags=["appointments"],
)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class AppointmentOut(BaseModel):
    id: str
    clinic_id: str
    patient_id: Optional[str]
    doctor_id: Optional[str]
    from_number: str
    patient_name: Optional[str]
    doctor_name: str
    date_str: str
    time_str: str
    appointment_datetime: Optional[datetime]
    symptoms: Optional[list]
    status: str
    confirmed_at: datetime
    reminder_sent: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AppointmentUpdateRequest(BaseModel):
    status: Optional[Literal["active", "cancelled", "completed"]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/patient/{patient_id}", response_model=List[AppointmentOut])
async def list_appointments_for_patient(
    clinic_id: str,
    patient_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """All appointments for a specific patient, newest first."""
    stmt = (
        select(Appointment)
        .where(
            Appointment.clinic_id == clinic_id,
            Appointment.patient_id == patient_id,
        )
        .order_by(Appointment.appointment_datetime.desc().nullslast())
    )
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment_detail(
    clinic_id: str,
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.clinic_id == clinic_id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appt


@router.put("/{appointment_id}", response_model=AppointmentOut)
async def update_appointment(
    clinic_id: str,
    appointment_id: str,
    body: AppointmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """Update appointment status from the dashboard (admin cancel/complete)."""
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.clinic_id == clinic_id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if body.status:
        appt.status = body.status
        appt.updated_at = datetime.utcnow()
        # Keep Redis in sync
        try:
            from app.services.store import get_appointment, save_appointment
            redis_appt = get_appointment(appointment_id)
            if redis_appt:
                redis_appt.status = body.status
                save_appointment(redis_appt)
        except Exception:
            pass

    await db.commit()
    await db.refresh(appt)
    return appt


@router.get("/", response_model=List[AppointmentOut])
async def list_appointments(
    clinic_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    doctor_name: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    """List appointments for the clinic with optional filters."""
    stmt = (
        select(Appointment)
        .where(Appointment.clinic_id == clinic_id)
        .order_by(Appointment.appointment_datetime.desc().nullslast())
        .offset(skip)
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    if doctor_name:
        stmt = stmt.where(Appointment.doctor_name.ilike(f"%{doctor_name}%"))
    if from_date:
        stmt = stmt.where(Appointment.appointment_datetime >= from_date)
    if to_date:
        stmt = stmt.where(Appointment.appointment_datetime <= to_date)

    result = await db.execute(stmt)
    return result.scalars().all()
