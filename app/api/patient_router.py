"""
Patient management API router.

Prefix : /api/clinics/{clinic_id}/patients
Tag    : patients

Endpoints
---------
GET    /                         list patients (paginated, optional search)
GET    /{patient_id}             full patient detail
PUT    /{patient_id}             partial update of patient profile
GET    /{patient_id}/records     medical records timeline (optional type filter)
GET    /by-phone/{phone_number}  look up patient by phone number
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin, get_db
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.user import ClinicUser

router = APIRouter(
    prefix="/api/clinics/{clinic_id}/patients",
    tags=["patients"],
)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class PatientSummary(BaseModel):
    id: str
    phone_number: str
    name: Optional[str]
    age: Optional[int]
    gender: Optional[str]
    blood_group: Optional[str]
    last_visit_at: Optional[datetime]
    record_count: int

    model_config = {"from_attributes": True}


class PatientDetail(PatientSummary):
    allergies: Optional[List[str]]
    chronic_conditions: Optional[List[str]]
    current_medications: Optional[List[str]]
    doctor_notes: Optional[str]
    created_at: datetime


class MedicalRecordOut(BaseModel):
    id: str
    visit_date: datetime
    record_type: str
    chief_complaint: Optional[str]
    soap_subjective: Optional[str]
    soap_objective: Optional[str]
    soap_assessment: Optional[str]
    soap_plan: Optional[str]
    soap_confidence: Optional[float]
    diagnoses: Optional[List[Any]]
    medications: Optional[List[Any]]
    symptoms: Optional[List[Any]]
    lab_panel_type: Optional[str]
    lab_results: Optional[Dict[str, Any]]
    pdf_url: Optional[str]
    doctor_name: Optional[str]

    model_config = {"from_attributes": True}


class PatientUpdateRequest(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[List[str]] = None
    chronic_conditions: Optional[List[str]] = None
    current_medications: Optional[List[str]] = None
    doctor_notes: Optional[str] = None


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


async def _get_patient_or_404(patient_id: str, clinic_id: str, db: AsyncSession) -> Patient:
    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
        )
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


async def _record_count_for_patient(patient_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(MedicalRecord.patient_id == patient_id)
    )
    return result.scalar_one()


def _build_patient_summary(patient: Patient, record_count: int) -> PatientSummary:
    return PatientSummary(
        id=patient.id,
        phone_number=patient.phone_number,
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        blood_group=patient.blood_group,
        last_visit_at=patient.last_visit_at,
        record_count=record_count,
    )


def _build_patient_detail(patient: Patient, record_count: int) -> PatientDetail:
    return PatientDetail(
        id=patient.id,
        phone_number=patient.phone_number,
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        blood_group=patient.blood_group,
        last_visit_at=patient.last_visit_at,
        record_count=record_count,
        allergies=patient.allergies,
        chronic_conditions=patient.chronic_conditions,
        current_medications=patient.current_medications,
        doctor_notes=patient.doctor_notes,
        created_at=patient.created_at,
    )


# ---------------------------------------------------------------------------
# GET /  — list patients (paginated, optional search)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[PatientSummary])
async def list_patients(
    clinic_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, description="Filter by patient name or phone number"),
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_admin),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)

    query = select(Patient).where(
        Patient.clinic_id == clinic_id,
        Patient.is_active.is_(True),
    )

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Patient.name.ilike(term),
                Patient.phone_number.ilike(term),
            )
        )

    query = query.order_by(Patient.last_visit_at.desc().nullslast()).offset(skip).limit(limit)
    result = await db.execute(query)
    patients = result.scalars().all()

    # Fetch record counts in a single query
    if not patients:
        return []

    patient_ids = [p.id for p in patients]
    counts_result = await db.execute(
        select(MedicalRecord.patient_id, func.count().label("cnt"))
        .where(MedicalRecord.patient_id.in_(patient_ids))
        .group_by(MedicalRecord.patient_id)
    )
    count_map: Dict[str, int] = {row.patient_id: row.cnt for row in counts_result}

    return [
        _build_patient_summary(p, count_map.get(p.id, 0))
        for p in patients
    ]


# ---------------------------------------------------------------------------
# GET /by-phone/{phone_number}  — look up by phone (declared BEFORE /{patient_id})
# ---------------------------------------------------------------------------

@router.get("/by-phone/{phone_number}", response_model=PatientDetail)
async def get_patient_by_phone(
    clinic_id: str,
    phone_number: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_admin),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)

    result = await db.execute(
        select(Patient).where(
            Patient.clinic_id == clinic_id,
            Patient.phone_number == phone_number,
            Patient.is_active.is_(True),
        )
    )
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No patient with phone number {phone_number} found in this clinic",
        )

    count = await _record_count_for_patient(patient.id, db)
    return _build_patient_detail(patient, count)


# ---------------------------------------------------------------------------
# GET /{patient_id}  — full patient detail
# ---------------------------------------------------------------------------

@router.get("/{patient_id}", response_model=PatientDetail)
async def get_patient(
    clinic_id: str,
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_admin),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    patient = await _get_patient_or_404(patient_id, clinic_id, db)
    count = await _record_count_for_patient(patient.id, db)
    return _build_patient_detail(patient, count)


# ---------------------------------------------------------------------------
# PUT /{patient_id}  — partial update
# ---------------------------------------------------------------------------

@router.put("/{patient_id}", response_model=PatientDetail)
async def update_patient(
    clinic_id: str,
    patient_id: str,
    body: PatientUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_admin),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    patient = await _get_patient_or_404(patient_id, clinic_id, db)

    if body.name is not None:
        patient.name = body.name
    if body.age is not None:
        patient.age = body.age
    if body.gender is not None:
        patient.gender = body.gender
    if body.blood_group is not None:
        patient.blood_group = body.blood_group
    if body.allergies is not None:
        patient.allergies = body.allergies
    if body.chronic_conditions is not None:
        patient.chronic_conditions = body.chronic_conditions
    if body.current_medications is not None:
        patient.current_medications = body.current_medications
    if body.doctor_notes is not None:
        patient.doctor_notes = body.doctor_notes

    await db.commit()
    await db.refresh(patient)

    count = await _record_count_for_patient(patient.id, db)
    return _build_patient_detail(patient, count)


# ---------------------------------------------------------------------------
# GET /{patient_id}/records  — medical records timeline
# ---------------------------------------------------------------------------

@router.get("/{patient_id}/records", response_model=List[MedicalRecordOut])
async def list_patient_records(
    clinic_id: str,
    patient_id: str,
    type: Optional[str] = Query(None, description="Filter by record type: consultation | lab_report"),
    db: AsyncSession = Depends(get_db),
    current_user: ClinicUser = Depends(get_current_admin),
):
    clinic = await _get_clinic_or_404(clinic_id, db)
    _require_clinic_access(clinic, current_user)
    # Verify patient belongs to this clinic
    await _get_patient_or_404(patient_id, clinic_id, db)

    query = (
        select(MedicalRecord, Doctor.name.label("doctor_name"))
        .outerjoin(Doctor, MedicalRecord.doctor_id == Doctor.id)
        .where(
            MedicalRecord.patient_id == patient_id,
            MedicalRecord.clinic_id == clinic_id,
        )
    )

    if type is not None:
        query = query.where(MedicalRecord.record_type == type)

    query = query.order_by(MedicalRecord.visit_date.desc())
    result = await db.execute(query)
    rows = result.all()

    records: List[MedicalRecordOut] = []
    for row in rows:
        record: MedicalRecord = row[0]
        doctor_name: Optional[str] = row[1]
        records.append(
            MedicalRecordOut(
                id=record.id,
                visit_date=record.visit_date,
                record_type=record.record_type,
                chief_complaint=record.chief_complaint,
                soap_subjective=record.soap_subjective,
                soap_objective=record.soap_objective,
                soap_assessment=record.soap_assessment,
                soap_plan=record.soap_plan,
                soap_confidence=record.soap_confidence,
                diagnoses=record.diagnoses,
                medications=record.medications,
                symptoms=record.symptoms,
                lab_panel_type=record.lab_panel_type,
                lab_results=record.lab_results,
                pdf_url=record.pdf_url,
                doctor_name=doctor_name,
            )
        )

    return records
