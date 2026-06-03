"""
ClinicAI — Auth Router
Handles signup, login, and current-user retrieval.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.clinic import Clinic
from app.models.model_config import ModelConfig
from app.models.user import ClinicUser
from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    clinic_name: str
    twilio_number: str
    timezone: str = "Asia/Kolkata"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    clinic_id: str
    user_id: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    clinic_id: Optional[str]
    clinic_name: Optional[str]
    clinic_twilio_number: Optional[str]
    clinic_timezone: Optional[str]
    clinic_open_hour: Optional[int]
    clinic_close_hour: Optional[int]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    # 1. Check for duplicate email
    existing_user = await db.execute(
        select(ClinicUser).where(ClinicUser.email == body.email)
    )
    if existing_user.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # 2. Check for duplicate twilio_number
    existing_clinic = await db.execute(
        select(Clinic).where(Clinic.twilio_number == body.twilio_number)
    )
    if existing_clinic.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A clinic with this Twilio number already exists.",
        )

    # 3. Create Clinic row
    clinic = Clinic(
        name=body.clinic_name,
        twilio_number=body.twilio_number,
        timezone=body.timezone,
    )
    db.add(clinic)
    await db.flush()  # populate clinic.id before referencing it

    # 4. Create ModelConfig row for clinic (defaults: groq + llama-3.3-70b-versatile)
    model_config = ModelConfig(
        clinic_id=clinic.id,
        llm_vendor="groq",
        llm_model="llama-3.3-70b-versatile",
    )
    db.add(model_config)

    # 5. Create ClinicUser row
    user = ClinicUser(
        email=body.email,
        hashed_password=get_password_hash(body.password),
        full_name=body.full_name,
        role="admin",
        clinic_id=clinic.id,
    )
    db.add(user)

    # 6. Commit everything atomically
    await db.commit()

    # 7. Return token + identifiers
    access_token = create_access_token(data={"sub": user.id})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        clinic_id=clinic.id,
        user_id=user.id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ClinicUser).where(ClinicUser.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.id})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        clinic_id=user.clinic_id or "",
        user_id=user.id,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: ClinicUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Eager-load the associated clinic
    clinic: Optional[Clinic] = None
    if current_user.clinic_id is not None:
        result = await db.execute(
            select(Clinic).where(Clinic.id == current_user.clinic_id)
        )
        clinic = result.scalar_one_or_none()

    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        clinic_id=current_user.clinic_id,
        clinic_name=clinic.name if clinic else None,
        clinic_twilio_number=clinic.twilio_number if clinic else None,
        clinic_timezone=clinic.timezone if clinic else None,
        clinic_open_hour=clinic.open_hour if clinic else None,
        clinic_close_hour=clinic.close_hour if clinic else None,
    )
