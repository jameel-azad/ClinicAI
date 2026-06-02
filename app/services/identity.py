import os
import re
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

UserRole = Literal["doctor", "patient"]


@dataclass(frozen=True)
class SenderIdentity:
    phone_number: str
    role: UserRole
    display_name: str | None = None


def normalize_whatsapp_number(raw_number: str) -> str:
    """Normalize Twilio WhatsApp numbers to a comparable E.164-like string."""
    number = raw_number.replace("whatsapp:", "").strip()
    if not number:
        return number

    has_plus = number.startswith("+")
    digits = re.sub(r"\D", "", number)
    if not digits:
        return number
    return f"+{digits}" if has_plus else digits


def _doctor_numbers_from_env() -> dict[str, str | None]:
    """
    Read doctor numbers from env.

    Supported forms:
    DOCTOR_WHATSAPP_NUMBERS=+91999,+91888
    DOCTOR_WHATSAPP_NUMBERS=Dr Mehta:+91999,Dr Sharma:+91888
    """
    raw = os.getenv("DOCTOR_WHATSAPP_NUMBERS", "")
    doctors: dict[str, str | None] = {}

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        if ":" in item and not item.lower().startswith("whatsapp:"):
            name, number = item.split(":", 1)
            doctors[normalize_whatsapp_number(number)] = name.strip() or None
        else:
            doctors[normalize_whatsapp_number(item)] = None

    return doctors


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("doctor", "dr"))


def identify_sender(raw_from: str) -> SenderIdentity:
    """
    Known doctor numbers route to doctor flow.
    Unknown numbers are treated as patients because patients can message first.
    """
    phone_number = normalize_whatsapp_number(raw_from)
    doctors = _doctor_numbers_from_env()

    if phone_number in doctors:
        return SenderIdentity(
            phone_number=phone_number,
            role="doctor",
            display_name=doctors[phone_number],
        )

    return SenderIdentity(phone_number=phone_number, role="patient")


def all_doctor_numbers() -> list[str]:
    return sorted(_doctor_numbers_from_env().keys())


def find_doctor_number(doctor_name: str | None = None) -> str | None:
    doctors = _doctor_numbers_from_env()
    if not doctors:
        return None

    requested = _normalize_name(doctor_name)
    if requested:
        for number, configured_name in doctors.items():
            if _normalize_name(configured_name) == requested:
                return number

    return next(iter(doctors.keys()))


def find_doctor_name(doctor_number: str) -> str | None:
    return _doctor_numbers_from_env().get(normalize_whatsapp_number(doctor_number))


async def is_doctor_from_db(phone_number: str) -> tuple[bool, str | None]:
    """
    Check if phone_number matches a Doctor row in any active clinic.
    Returns (is_doctor, doctor_name).
    Used as a fallback when the number is NOT in DOCTOR_WHATSAPP_NUMBERS env var.
    """
    try:
        from app.database import AsyncSessionLocal
        from app.models.doctor import Doctor
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            # Normalize the phone: strip "whatsapp:" prefix
            clean = phone_number.replace("whatsapp:", "").strip()
            # Try exact match and whatsapp: prefixed match
            result = await db.execute(
                select(Doctor).where(
                    Doctor.is_active == True,
                    Doctor.whatsapp_number.in_([phone_number, f"whatsapp:{clean}", clean])
                )
            )
            doctor = result.scalar_one_or_none()
            if doctor:
                return True, doctor.name
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("[identity] DB doctor lookup failed: %s", exc)
    return False, None


async def identify_sender_async(raw_from: str) -> SenderIdentity:
    """
    Async version of identify_sender — checks env var first, then DB.
    Use this in the webhook when possible.
    """
    phone_number = normalize_whatsapp_number(raw_from)
    doctors = _doctor_numbers_from_env()
    if phone_number in doctors:
        return SenderIdentity(phone_number=phone_number, role="doctor", display_name=doctors[phone_number])
    # Fallback: check database
    is_doc, name = await is_doctor_from_db(phone_number)
    if is_doc:
        return SenderIdentity(phone_number=phone_number, role="doctor", display_name=name)
    return SenderIdentity(phone_number=phone_number, role="patient")


async def all_doctor_numbers_async() -> list[str]:
    """
    Returns all doctor numbers: env var + active DB doctors.
    """
    env_numbers = set(_doctor_numbers_from_env().keys())
    try:
        from app.database import AsyncSessionLocal
        from app.models.doctor import Doctor
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Doctor.whatsapp_number).where(Doctor.is_active == True))
            db_numbers = {normalize_whatsapp_number(r[0]) for r in result.fetchall()}
            return sorted(env_numbers | db_numbers)
    except Exception:
        return sorted(env_numbers)
