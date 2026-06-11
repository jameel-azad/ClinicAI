import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

_log = logging.getLogger(__name__)

_DEFAULT_SECRET = "CHANGE_ME_IN_PRODUCTION_USE_32_CHARS_MIN"
SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# ── Startup key-security check ─────────────────────────────────────────────────
# A missing, default, or short key means ALL JWT tokens and encrypted API keys
# stored in the database are trivially recoverable by anyone who reads the code.
_key_insecure = (
    not SECRET_KEY
    or SECRET_KEY == _DEFAULT_SECRET
    or len(SECRET_KEY) < 32
)
if _key_insecure:
    _msg = (
        "SECRET_KEY is missing, too short, or set to the insecure default value. "
        "All JWT tokens and encrypted API keys are exposed. "
        "Set a random SECRET_KEY of at least 32 characters in your .env file."
    )
    if os.getenv("ENVIRONMENT", "").lower() in ("production", "prod"):
        raise RuntimeError(f"FATAL SECURITY ERROR: {_msg}")
    _log.critical("SECURITY WARNING: %s", _msg)
# ──────────────────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
