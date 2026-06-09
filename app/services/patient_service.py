"""
Patient service — upsert patient profiles and persist medical records to PostgreSQL.

Called automatically from consultation and lab flows so medical history
accumulates without any manual effort.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def upsert_patient(
    clinic_id: str,
    phone_number: str,
    name: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """
    Find or create a Patient row for (clinic_id, phone_number).
    Updates name if provided and not already set.
    Returns the patient.id.
    If db is None, opens its own session.
    """
    from app.models.patient import Patient

    close_session = db is None
    if db is None:
        db = AsyncSessionLocal()

    try:
        result = await db.execute(
            select(Patient).where(
                Patient.clinic_id == clinic_id,
                Patient.phone_number == phone_number,
            )
        )
        patient = result.scalar_one_or_none()

        if patient is None:
            patient = Patient(
                clinic_id=clinic_id,
                phone_number=phone_number,
                name=name,
            )
            db.add(patient)
            try:
                await db.flush()
                logger.info("[patient_service] Created patient %s for clinic %s", phone_number, clinic_id)
            except IntegrityError:
                # Concurrent insert won the race — roll back the failed insert and
                # fetch the row that was committed by the other request.
                await db.rollback()
                result = await db.execute(
                    select(Patient).where(
                        Patient.clinic_id == clinic_id,
                        Patient.phone_number == phone_number,
                    )
                )
                patient = result.scalar_one()
                logger.info("[patient_service] Concurrent upsert resolved for %s", phone_number)
        if name and not patient.name:
            patient.name = name
        patient.last_visit_at = datetime.utcnow()

        if close_session:
            await db.commit()

        return patient.id
    except Exception as exc:
        logger.error("[patient_service] upsert_patient failed: %s", exc)
        if close_session:
            await db.rollback()
        raise
    finally:
        if close_session:
            await db.close()


async def save_consultation_record(
    clinic_id: str,
    patient_phone: str,
    patient_name: Optional[str],
    doctor_phone: Optional[str],
    chief_complaint: Optional[str],
    soap_result: dict,  # output from scribe_service / process_consultation_bundle
    doctor_name_hint: Optional[str] = None,
) -> Optional[str]:
    """
    Persist a MedicalRecord of type "consultation" after a SOAP note is generated.
    Returns the record id, or None on failure.
    soap_result keys: soap_note, clinical_entities, fhir_bundle, soap_note_pdf_url
    """
    import re as _re
    from sqlalchemy import or_
    from app.models.medical_record import MedicalRecord
    from app.models.doctor import Doctor

    try:
        async with AsyncSessionLocal() as db:
            # Resolve patient
            patient_id = await upsert_patient(clinic_id, patient_phone, patient_name, db=db)

            # Resolve doctor_id from phone — try both +<digits> and digits-only formats
            # because dashboard users may enter the number with or without the leading +.
            doctor_id: Optional[str] = None
            resolved_doctor_name: Optional[str] = doctor_name_hint
            if doctor_phone:
                digits = _re.sub(r"\D", "", doctor_phone)
                dr = await db.execute(
                    select(Doctor).where(
                        Doctor.clinic_id == clinic_id,
                        Doctor.is_active == True,
                        or_(
                            Doctor.whatsapp_number == f"+{digits}",
                            Doctor.whatsapp_number == digits,
                        ),
                    )
                )
                dr_row = dr.scalar_one_or_none()
                if dr_row:
                    doctor_id = dr_row.id
                    resolved_doctor_name = dr_row.name

            # Parse SOAP note
            soap = soap_result.get("soap_note") or {}
            entities = soap_result.get("clinical_entities") or {}

            def _section(key: str) -> Optional[str]:
                s = soap.get(key) or {}
                return s.get("content") if isinstance(s, dict) else str(s) if s else None

            record = MedicalRecord(
                patient_id=patient_id,
                clinic_id=clinic_id,
                doctor_id=doctor_id,
                doctor_name=resolved_doctor_name,
                visit_date=datetime.utcnow(),
                record_type="consultation",
                chief_complaint=chief_complaint,
                soap_subjective=_section("subjective"),
                soap_objective=_section("objective"),
                soap_assessment=_section("assessment"),
                soap_plan=_section("plan"),
                soap_confidence=soap_result.get("overall_confidence"),
                diagnoses=entities.get("diagnoses"),
                medications=entities.get("medications"),
                symptoms=entities.get("symptoms"),
                fhir_bundle=soap_result.get("fhir_bundle"),
                pdf_url=soap_result.get("soap_note_pdf_url"),
            )
            db.add(record)
            await db.commit()
            logger.info("[patient_service] Saved consultation record for %s", patient_phone)
            return record.id
    except Exception as exc:
        logger.error("[patient_service] save_consultation_record failed: %s", exc)
        return None


async def get_latest_consultation_record(
    clinic_id: str,
    patient_phone: str,
) -> Optional[dict]:
    """Return the patient's most recent consultation record as a plain dict.

    Used by the follow-up agent to provide consultation context when deciding
    whether a patient query can be answered automatically or must be escalated.
    Returns None if no record exists or on DB error.
    """
    from app.models.patient import Patient
    from app.models.medical_record import MedicalRecord
    from sqlalchemy import desc

    try:
        async with AsyncSessionLocal() as db:
            patient_result = await db.execute(
                select(Patient).where(
                    Patient.clinic_id == clinic_id,
                    Patient.phone_number == patient_phone,
                )
            )
            patient = patient_result.scalar_one_or_none()
            if not patient:
                return None

            record_result = await db.execute(
                select(MedicalRecord)
                .where(
                    MedicalRecord.patient_id == patient.id,
                    MedicalRecord.record_type == "consultation",
                )
                .order_by(desc(MedicalRecord.visit_date))
                .limit(1)
            )
            record = record_result.scalar_one_or_none()
            if not record:
                return None

            return {
                "chief_complaint": record.chief_complaint,
                "soap_subjective": record.soap_subjective,
                "soap_assessment": record.soap_assessment,
                "soap_plan": record.soap_plan,
                "diagnoses": record.diagnoses or [],
                "medications": record.medications or [],
                "symptoms": record.symptoms or [],
                "visit_date": str(record.visit_date) if record.visit_date else None,
            }
    except Exception as exc:
        logger.error("[patient_service] get_latest_consultation_record failed: %s", exc)
        return None


async def save_lab_record(
    clinic_id: str,
    patient_phone: str,
    patient_name: Optional[str],
    lab_result: dict,  # output from lab pipeline
    pdf_url: Optional[str] = None,
) -> Optional[str]:
    """Persist a MedicalRecord of type lab_report."""
    from app.models.medical_record import MedicalRecord

    try:
        async with AsyncSessionLocal() as db:
            patient_id = await upsert_patient(clinic_id, patient_phone, patient_name, db=db)

            record = MedicalRecord(
                patient_id=patient_id,
                clinic_id=clinic_id,
                visit_date=datetime.utcnow(),
                record_type="lab_report",
                lab_panel_type=lab_result.get("panel_type"),
                lab_results={
                    "all_values": lab_result.get("all_values", []),
                    "abnormals": lab_result.get("abnormals", []),
                    "criticals": lab_result.get("criticals", []),
                },
                pdf_url=pdf_url,
            )
            db.add(record)
            await db.commit()
            logger.info("[patient_service] Saved lab record for %s", patient_phone)
            return record.id
    except Exception as exc:
        logger.error("[patient_service] save_lab_record failed: %s", exc)
        return None
