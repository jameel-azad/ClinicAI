"""
Persistent store — Redis primary, in-memory fallback.

Every public function has identical signatures to the old in-memory version so
callers need no changes.  If Redis is unavailable (dev without Docker, etc.) the
process falls back silently to dicts and prints a one-time warning.

Key schema (all prefixed  clinicai:):
  session:{phone}                → BookingSession JSON           TTL 86400s
  appt:{id}                      → AppointmentRecord JSON        no TTL
  appts_by_phone:{phone}         → Redis SET of appointment_ids  no TTL
  approval:{id}                  → dict JSON                     no TTL
  approvals_waiting:{doctor}     → Redis SET of approval_ids     no TTL
  doctor_profile:{phone}         → dict JSON                     no TTL
  doctor_setup:{phone}           → dict JSON                     TTL 3600s
  greeted:{phone}                → "1"                           TTL 2592000s
  slot_suggestions:{phone}       → JSON list                     TTL 86400s
  soap:{id}                      → dict JSON                     TTL 604800s
  lab:{id}                       → dict JSON                     TTL 604800s
  last_active:{phone}            → ISO timestamp                 TTL 604800s
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from app.schemas import AppointmentRecord, BookingSession

load_dotenv()
logger = logging.getLogger(__name__)

_PREFIX = "clinicai:"
_TTL_SESSION = 86_400        # 24 h
_TTL_SETUP = 3_600           # 1 h
_TTL_GREETED = 2_592_000     # 30 days
_TTL_SLOTS = 86_400          # 24 h
_TTL_PENDING = 604_800       # 7 days
_TTL_LAST_ACTIVE = 604_800   # 7 days


# ── Redis connection ───────────────────────────────────────────────────────────

def _connect_redis():
    try:
        import redis as redis_lib
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        client = redis_lib.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        logger.info("[store] Redis connected: %s", url)
        return client
    except Exception as exc:
        logger.warning(
            "[store] Redis unavailable (%s) — falling back to in-memory store. "
            "Set REDIS_URL to enable persistence across restarts.",
            exc,
        )
        return None


_r = _connect_redis()


def _key(suffix: str) -> str:
    return f"{_PREFIX}{suffix}"


def _rset(key: str, value: dict | list, ttl: int | None = None) -> None:
    if _r is None:
        return
    try:
        serialized = json.dumps(value, default=str)
        if ttl:
            _r.setex(key, ttl, serialized)
        else:
            _r.set(key, serialized)
    except Exception as exc:
        logger.warning("[store] Redis write error for %s: %s", key, exc)


def _rget(key: str) -> Optional[dict | list]:
    if _r is None:
        return None
    try:
        raw = _r.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("[store] Redis read error for %s: %s", key, exc)
        return None


def _rdel(key: str) -> None:
    if _r is None:
        return
    try:
        _r.delete(key)
    except Exception as exc:
        logger.warning("[store] Redis delete error for %s: %s", key, exc)


def _sadd(key: str, *members: str) -> None:
    if _r is None:
        return
    try:
        _r.sadd(key, *members)
    except Exception:
        pass


def _srem(key: str, *members: str) -> None:
    if _r is None:
        return
    try:
        _r.srem(key, *members)
    except Exception:
        pass


def _smembers(key: str) -> set:
    if _r is None:
        return set()
    try:
        return _r.smembers(key) or set()
    except Exception:
        return set()


# ── In-memory fallback stores ──────────────────────────────────────────────────

_sessions: dict[str, BookingSession] = {}
_appointments: dict[str, AppointmentRecord] = {}
_pending_approvals: dict[str, dict] = {}
_greeted_numbers: set[str] = set()
_doctor_profiles: dict[str, dict] = {}
_doctor_setup_sessions: dict[str, dict] = {}
_slot_suggestions: dict[str, list[dict]] = {}
_pending_soaps: dict[str, dict] = {}
_pending_lab_reviews: dict[str, dict] = {}


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STORE
# ══════════════════════════════════════════════════════════════════════════════

def get_session(from_number: str) -> Optional[BookingSession]:
    data = _rget(_key(f"session:{from_number}"))
    if data:
        return BookingSession.model_validate(data)
    return _sessions.get(from_number)


def save_session(session: BookingSession) -> None:
    session.updated_at = datetime.now()
    _rset(_key(f"session:{session.from_number}"), session.model_dump(), _TTL_SESSION)
    _sessions[session.from_number] = session


def delete_session(from_number: str) -> None:
    _rdel(_key(f"session:{from_number}"))
    _sessions.pop(from_number, None)


def all_sessions() -> dict:
    if _r is not None:
        result = {}
        try:
            for key in _r.scan_iter(f"{_PREFIX}session:*"):
                phone = key.removeprefix(f"{_PREFIX}session:")
                data = _rget(key)
                if data:
                    result[phone] = data
            return result
        except Exception:
            pass
    return {k: v.model_dump() for k, v in _sessions.items()}


# ══════════════════════════════════════════════════════════════════════════════
# APPOINTMENT STORE
# ══════════════════════════════════════════════════════════════════════════════

def save_appointment(appt: AppointmentRecord) -> None:
    _rset(_key(f"appt:{appt.appointment_id}"), appt.model_dump())
    _sadd(_key(f"appts_by_phone:{appt.from_number}"), appt.appointment_id)
    _appointments[appt.appointment_id] = appt


def get_appointment(appointment_id: str) -> Optional[AppointmentRecord]:
    data = _rget(_key(f"appt:{appointment_id}"))
    if data:
        return AppointmentRecord.model_validate(data)
    return _appointments.get(appointment_id)


def get_appointments_by_number(from_number: str) -> list[AppointmentRecord]:
    ids = _smembers(_key(f"appts_by_phone:{from_number}"))
    if ids:
        appts = []
        for aid in ids:
            a = get_appointment(aid)
            if a:
                appts.append(a)
        return appts
    return [a for a in _appointments.values() if a.from_number == from_number]


def get_latest_appointment_for_patient(from_number: str) -> Optional[AppointmentRecord]:
    appts = get_appointments_by_number(from_number)
    if not appts:
        return None
    return max(appts, key=lambda a: a.confirmed_at)


def cancel_appointment(appointment_id: str) -> bool:
    appt = get_appointment(appointment_id)
    if appt:
        _rdel(_key(f"appt:{appointment_id}"))
        _srem(_key(f"appts_by_phone:{appt.from_number}"), appointment_id)
        _appointments.pop(appointment_id, None)
        return True
    if appointment_id in _appointments:
        del _appointments[appointment_id]
        return True
    return False


def mark_reminder_sent(appointment_id: str) -> None:
    appt = get_appointment(appointment_id)
    if appt:
        appt.reminder_sent = True
        save_appointment(appt)


def all_appointments() -> dict:
    if _r is not None:
        result = {}
        try:
            for key in _r.scan_iter(f"{_PREFIX}appt:*"):
                if "appts_by_phone" in key:
                    continue
                appt_id = key.removeprefix(f"{_PREFIX}appt:")
                data = _rget(key)
                if data:
                    result[appt_id] = data
            return result
        except Exception:
            pass
    return {k: v.model_dump() for k, v in _appointments.items()}


# ══════════════════════════════════════════════════════════════════════════════
# PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════════════

def save_pending_approval(approval: dict) -> None:
    approval["updated_at"] = datetime.now().isoformat()
    aid = approval["approval_id"]
    _rset(_key(f"approval:{aid}"), approval)
    if approval.get("status") == "waiting_doctor" and approval.get("doctor_number"):
        _sadd(_key(f"approvals_waiting:{approval['doctor_number']}"), aid)
    _pending_approvals[aid] = approval


def get_pending_approval(approval_id: str) -> Optional[dict]:
    data = _rget(_key(f"approval:{approval_id.upper()}"))
    if data:
        return data
    return _pending_approvals.get(approval_id.upper())


def update_pending_approval(approval_id: str, **updates) -> Optional[dict]:
    approval = get_pending_approval(approval_id)
    if not approval:
        return None
    old_status = approval.get("status")
    approval.update(updates)
    approval["updated_at"] = datetime.now().isoformat()
    _rset(_key(f"approval:{approval_id.upper()}"), approval)
    new_status = approval.get("status", "")
    doctor_number = approval.get("doctor_number")
    if doctor_number and old_status == "waiting_doctor" and new_status != "waiting_doctor":
        _srem(_key(f"approvals_waiting:{doctor_number}"), approval_id.upper())
    _pending_approvals[approval_id.upper()] = approval
    return approval


def get_waiting_approvals_for_doctor(doctor_number: str) -> list[dict]:
    ids = _smembers(_key(f"approvals_waiting:{doctor_number}"))
    if ids:
        result = []
        for aid in ids:
            a = get_pending_approval(aid)
            if a and a.get("status") == "waiting_doctor":
                result.append(a)
        return result
    return [
        a for a in _pending_approvals.values()
        if a.get("doctor_number") == doctor_number and a.get("status") == "waiting_doctor"
    ]


def get_latest_approval_for_patient(patient_number: str) -> Optional[dict]:
    if _r is not None:
        try:
            matches = []
            for key in _r.scan_iter(f"{_PREFIX}approval:*"):
                data = _rget(key)
                if data and data.get("patient_number") == patient_number:
                    matches.append(data)
            if matches:
                matches.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                return matches[0]
        except Exception:
            pass
    matches = [a for a in _pending_approvals.values() if a.get("patient_number") == patient_number]
    if not matches:
        return None
    matches.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return matches[0]


def all_pending_approvals() -> dict:
    if _r is not None:
        result = {}
        try:
            for key in _r.scan_iter(f"{_PREFIX}approval:*"):
                aid = key.removeprefix(f"{_PREFIX}approval:")
                data = _rget(key)
                if data:
                    result[aid] = data
            return result
        except Exception:
            pass
    return _pending_approvals.copy()


# ══════════════════════════════════════════════════════════════════════════════
# GREETING TRACKER
# ══════════════════════════════════════════════════════════════════════════════

def has_been_greeted(number: str) -> bool:
    if _r is not None:
        try:
            return bool(_r.get(_key(f"greeted:{number}")))
        except Exception:
            pass
    return number in _greeted_numbers


def mark_as_greeted(number: str) -> None:
    if _r is not None:
        try:
            _r.setex(_key(f"greeted:{number}"), _TTL_GREETED, "1")
        except Exception:
            pass
    _greeted_numbers.add(number)


# ══════════════════════════════════════════════════════════════════════════════
# DOCTOR PROFILES & SETUP
# ══════════════════════════════════════════════════════════════════════════════

def save_doctor_profile(doctor_number: str, profile: dict) -> None:
    profile["doctor_number"] = doctor_number
    profile["updated_at"] = datetime.now().isoformat()
    _rset(_key(f"doctor_profile:{doctor_number}"), profile)
    _doctor_profiles[doctor_number] = profile


def get_doctor_profile(doctor_number: str) -> Optional[dict]:
    data = _rget(_key(f"doctor_profile:{doctor_number}"))
    if data:
        return data
    return _doctor_profiles.get(doctor_number)


def find_doctor_profile_by_name(doctor_name: str | None) -> Optional[dict]:
    if not doctor_name:
        return None
    wanted = _profile_key(doctor_name)
    if _r is not None:
        try:
            for key in _r.scan_iter(f"{_PREFIX}doctor_profile:*"):
                data = _rget(key)
                if data and _profile_key(data.get("name")) == wanted:
                    return data
        except Exception:
            pass
    for profile in _doctor_profiles.values():
        if _profile_key(profile.get("name")) == wanted:
            return profile
    return None


def all_doctor_profiles() -> dict:
    if _r is not None:
        result = {}
        try:
            for key in _r.scan_iter(f"{_PREFIX}doctor_profile:*"):
                phone = key.removeprefix(f"{_PREFIX}doctor_profile:")
                data = _rget(key)
                if data:
                    result[phone] = data
            return result
        except Exception:
            pass
    return _doctor_profiles.copy()


def save_doctor_setup_session(doctor_number: str, session: dict) -> None:
    session["updated_at"] = datetime.now().isoformat()
    _rset(_key(f"doctor_setup:{doctor_number}"), session, _TTL_SETUP)
    _doctor_setup_sessions[doctor_number] = session


def get_doctor_setup_session(doctor_number: str) -> Optional[dict]:
    data = _rget(_key(f"doctor_setup:{doctor_number}"))
    if data:
        return data
    return _doctor_setup_sessions.get(doctor_number)


def clear_doctor_setup_session(doctor_number: str) -> None:
    _rdel(_key(f"doctor_setup:{doctor_number}"))
    _doctor_setup_sessions.pop(doctor_number, None)


# ══════════════════════════════════════════════════════════════════════════════
# SLOT SUGGESTIONS
# ══════════════════════════════════════════════════════════════════════════════

def save_slot_suggestions(patient_number: str, suggestions: list[dict]) -> None:
    _rset(_key(f"slot_suggestions:{patient_number}"), suggestions, _TTL_SLOTS)
    _slot_suggestions[patient_number] = suggestions


def get_slot_suggestions(patient_number: str) -> list[dict]:
    data = _rget(_key(f"slot_suggestions:{patient_number}"))
    if data and isinstance(data, list):
        return data
    return _slot_suggestions.get(patient_number, [])


def clear_slot_suggestions(patient_number: str) -> None:
    _rdel(_key(f"slot_suggestions:{patient_number}"))
    _slot_suggestions.pop(patient_number, None)


# ══════════════════════════════════════════════════════════════════════════════
# PENDING SOAP APPROVALS
# ══════════════════════════════════════════════════════════════════════════════

def save_pending_soap(soap_id: str, data: dict) -> None:
    data["soap_id"] = soap_id.upper()
    data["created_at"] = datetime.now().isoformat()
    _rset(_key(f"soap:{soap_id.upper()}"), data, _TTL_PENDING)
    _pending_soaps[soap_id.upper()] = data


def get_pending_soap(soap_id: str) -> Optional[dict]:
    data = _rget(_key(f"soap:{soap_id.upper()}"))
    if data:
        return data
    return _pending_soaps.get(soap_id.upper())


def delete_pending_soap(soap_id: str) -> None:
    _rdel(_key(f"soap:{soap_id.upper()}"))
    _pending_soaps.pop(soap_id.upper(), None)


def get_latest_soap_for_doctor(doctor_number: str) -> Optional[dict]:
    if _r is not None:
        try:
            matches = []
            for key in _r.scan_iter(f"{_PREFIX}soap:*"):
                data = _rget(key)
                if data and data.get("doctor_number") == doctor_number:
                    matches.append(data)
            if matches:
                return max(matches, key=lambda s: s.get("created_at", ""))
        except Exception:
            pass
    matches = [s for s in _pending_soaps.values() if s.get("doctor_number") == doctor_number]
    return max(matches, key=lambda s: s.get("created_at", "")) if matches else None


# ══════════════════════════════════════════════════════════════════════════════
# PENDING LAB REPORT REVIEWS
# ══════════════════════════════════════════════════════════════════════════════

def save_pending_lab_review(lab_id: str, data: dict) -> None:
    data["lab_id"] = lab_id.upper()
    data["created_at"] = datetime.now().isoformat()
    _rset(_key(f"lab:{lab_id.upper()}"), data, _TTL_PENDING)
    _pending_lab_reviews[lab_id.upper()] = data


def get_pending_lab_review(lab_id: str) -> Optional[dict]:
    data = _rget(_key(f"lab:{lab_id.upper()}"))
    if data:
        return data
    return _pending_lab_reviews.get(lab_id.upper())


def delete_pending_lab_review(lab_id: str) -> None:
    _rdel(_key(f"lab:{lab_id.upper()}"))
    _pending_lab_reviews.pop(lab_id.upper(), None)


def get_latest_lab_review_for_doctor(doctor_number: str) -> Optional[dict]:
    if _r is not None:
        try:
            matches = []
            for key in _r.scan_iter(f"{_PREFIX}lab:*"):
                data = _rget(key)
                if data and data.get("doctor_number") == doctor_number:
                    matches.append(data)
            if matches:
                return max(matches, key=lambda r: r.get("created_at", ""))
        except Exception:
            pass
    matches = [r for r in _pending_lab_reviews.values() if r.get("doctor_number") == doctor_number]
    return max(matches, key=lambda r: r.get("created_at", "")) if matches else None


# ══════════════════════════════════════════════════════════════════════════════
# LAST ACTIVE TRACKER  (used by no-show recovery)
# ══════════════════════════════════════════════════════════════════════════════

def update_last_active(phone: str) -> None:
    ts = datetime.now().isoformat()
    if _r is not None:
        try:
            _r.setex(_key(f"last_active:{phone}"), _TTL_LAST_ACTIVE, ts)
            return
        except Exception:
            pass


def get_last_active(phone: str) -> Optional[datetime]:
    if _r is not None:
        try:
            raw = _r.get(_key(f"last_active:{phone}"))
            if raw:
                return datetime.fromisoformat(raw)
        except Exception:
            pass
    return None


# ── Internal helper ────────────────────────────────────────────────────────────

def _profile_key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())
