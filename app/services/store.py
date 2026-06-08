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
import threading
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from app.schemas import AppointmentRecord, BookingSession, ConsultationMessage, ConsultationSession

load_dotenv()
logger = logging.getLogger(__name__)

_PREFIX = "clinicai:"
_TTL_SESSION = 86_400        # 24 h
_TTL_SETUP = 3_600           # 1 h
_TTL_GREETED = 2_592_000     # 30 days
_TTL_SLOTS = 86_400          # 24 h
_TTL_PENDING = 604_800       # 7 days
_TTL_LAST_ACTIVE = 604_800   # 7 days
_TTL_CONSULTATION = 14_400   # 4 h
_TTL_AFTERHOURS = 129_600    # 36 h


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
_consultations: dict[str, ConsultationSession] = {}
_after_hours_queues: dict[str, list[dict]] = {}
_doctor_reply_contexts: dict[str, list[dict]] = {}  # doctor_number → queue (most-recent-first)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STORE
# ══════════════════════════════════════════════════════════════════════════════

def get_session(from_number: str, clinic_id: str | None = None) -> Optional[BookingSession]:
    # Prefer clinic-scoped key (multi-tenant isolation) when clinic_id is known
    if clinic_id:
        data = _rget(_key(f"session:{clinic_id}:{from_number}"))
        if data:
            return BookingSession.model_validate(data)
    # Fall back to legacy unscoped key (background jobs without clinic context)
    data = _rget(_key(f"session:{from_number}"))
    if data:
        return BookingSession.model_validate(data)
    return _sessions.get(from_number)


def save_session(session: BookingSession) -> None:
    session.updated_at = datetime.now()
    data = session.model_dump()
    if session.clinic_id:
        # Write clinic-scoped key — primary for webhook path (isolated per clinic)
        _rset(_key(f"session:{session.clinic_id}:{session.from_number}"), data, _TTL_SESSION)
    # Also write legacy key so background jobs (scheduler, follow-ups) can find the session
    _rset(_key(f"session:{session.from_number}"), data, _TTL_SESSION)
    _sessions[session.from_number] = session


def delete_session(from_number: str, clinic_id: str | None = None) -> None:
    if clinic_id:
        _rdel(_key(f"session:{clinic_id}:{from_number}"))
    _rdel(_key(f"session:{from_number}"))
    _sessions.pop(from_number, None)


def reset_session(from_number: str, clinic_id: str | None = None) -> None:
    """Reset a patient session to NEW_PATIENT while preserving identity fields.

    Clears all booking/consultation state so the patient starts fresh, but keeps
    from_number, clinic_id, and patient_name so returning patients are recognised.
    """
    session = get_session(from_number, clinic_id) or BookingSession(
        from_number=from_number, clinic_id=clinic_id
    )
    session.journey_state = "NEW_PATIENT"
    session.state = "GREETING"
    session.symptoms = None
    session.requested_date = None
    session.requested_time = None
    session.new_requested_date = None
    session.new_requested_time = None
    session.doctor_name = None
    session.doctor_shortlist = None
    session.last_bot_response = None
    save_session(session)


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


def _parse_appt_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """Best-effort parse of appointment date + time strings into a naive datetime.
    Used to sort appointments by scheduled time rather than booking-confirmation time.
    """
    import re as _re
    _M = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    d = (date_str or "").lower().strip()
    now = datetime.now()
    try:
        if d in {"today", "aaj"}:
            base = now.date()
        elif d in {"tomorrow", "kal"}:
            from datetime import timedelta as _td
            base = (now + _td(days=1)).date()
        else:
            day_m = _re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", d)
            mon_m = _re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", d)
            if not day_m or not mon_m:
                return None
            yr_m = _re.search(r"\b(20\d{2})\b", d)
            year = int(yr_m.group(1)) if yr_m else now.year
            from datetime import date as _date
            base = _date(year, _M[mon_m.group(1)[:3]], int(day_m.group(1)))
        t = (time_str or "").lower()
        tm = _re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
        if not tm:
            return None
        hr, mn = int(tm.group(1)), int(tm.group(2) or "0")
        mer = tm.group(3)
        if mer == "pm" and hr != 12:
            hr += 12
        elif mer == "am" and hr == 12:
            hr = 0
        return datetime(base.year, base.month, base.day, hr, mn)
    except Exception:
        return None


def get_latest_appointment_for_patient(from_number: str) -> Optional[AppointmentRecord]:
    appts = get_appointments_by_number(from_number)
    if not appts:
        return None
    def _key_fn(a):
        dt = _parse_appt_datetime(a.date_str, a.time_str)
        # Use appointment datetime when parseable; fall back to confirmation time
        return dt if dt is not None else a.confirmed_at.replace(tzinfo=None)
    try:
        return max(appts, key=_key_fn)
    except TypeError:
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


def _lab_review_belongs_to_doctor(data: dict, doctor_number: str) -> bool:
    """Check single doctor_number field OR multi-doctor doctor_numbers list."""
    if data.get("doctor_number") == doctor_number:
        return True
    return doctor_number in (data.get("doctor_numbers") or [])


def get_latest_lab_review_for_doctor(doctor_number: str) -> Optional[dict]:
    if _r is not None:
        try:
            matches = []
            for key in _r.scan_iter(f"{_PREFIX}lab:*"):
                data = _rget(key)
                if data and _lab_review_belongs_to_doctor(data, doctor_number):
                    matches.append(data)
            if matches:
                return max(matches, key=lambda r: r.get("created_at", ""))
        except Exception:
            pass
    matches = [r for r in _pending_lab_reviews.values() if _lab_review_belongs_to_doctor(r, doctor_number)]
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


# ══════════════════════════════════════════════════════════════════════════════
# ATOMIC CONSULTATION-MESSAGE APPEND
#
# Redis path  — Lua script executes atomically (Redis is single-threaded).
#               No read-modify-write race between concurrent patient messages.
# Fallback    — per-patient threading.Lock guards the in-memory dict.
# ══════════════════════════════════════════════════════════════════════════════

_APPEND_MSG_LUA = """
local key    = KEYS[1]
local msg_j  = ARGV[1]
local ts     = ARGV[2]
local ttl    = tonumber(ARGV[3])
local raw    = redis.call('GET', key)
if not raw then return 0 end
local ok, data = pcall(cjson.decode, raw)
if not ok then return -1 end
if type(data['messages']) ~= 'table' then data['messages'] = {} end
local ok2, m = pcall(cjson.decode, msg_j)
if not ok2 then return -2 end
table.insert(data['messages'], m)
data['last_activity'] = ts
local ok3, serialized = pcall(cjson.encode, data)
if not ok3 then return -3 end
if ttl > 0 then
    redis.call('SETEX', key, ttl, serialized)
else
    redis.call('SET', key, serialized)
end
return #data['messages']
"""

_lua_append_msg = _r.register_script(_APPEND_MSG_LUA) if _r is not None else None

_consult_append_locks: dict[str, threading.Lock] = {}
_consult_append_locks_guard = threading.Lock()


def _get_consult_lock(patient_number: str) -> threading.Lock:
    with _consult_append_locks_guard:
        if patient_number not in _consult_append_locks:
            _consult_append_locks[patient_number] = threading.Lock()
        return _consult_append_locks[patient_number]


# ══════════════════════════════════════════════════════════════════════════════
# CONSULTATION SESSIONS  (Sprint 2)
# Key: clinicai:consult:{patient_number}   TTL 4h
# ══════════════════════════════════════════════════════════════════════════════

def save_consultation(patient_number: str, session: ConsultationSession) -> None:
    session.last_activity = datetime.now()
    data = session.model_dump()
    if session.clinic_id:
        _rset(_key(f"consult:{session.clinic_id}:{patient_number}"), data, _TTL_CONSULTATION)
    # Legacy key kept so scheduler timeout jobs (which don't carry clinic_id) can find sessions
    _rset(_key(f"consult:{patient_number}"), data, _TTL_CONSULTATION)
    _consultations[patient_number] = session


def get_consultation(patient_number: str, clinic_id: str | None = None) -> Optional[ConsultationSession]:
    if clinic_id:
        data = _rget(_key(f"consult:{clinic_id}:{patient_number}"))
        if data:
            return ConsultationSession.model_validate(data)
    data = _rget(_key(f"consult:{patient_number}"))
    if data:
        return ConsultationSession.model_validate(data)
    return _consultations.get(patient_number)


def delete_consultation(patient_number: str, clinic_id: str | None = None) -> None:
    if clinic_id:
        _rdel(_key(f"consult:{clinic_id}:{patient_number}"))
    _rdel(_key(f"consult:{patient_number}"))
    _consultations.pop(patient_number, None)


def append_consultation_message(patient_number: str, msg: ConsultationMessage) -> None:
    """Atomically append a message to the active ConsultationSession.

    Redis path:  Lua script — single atomic operation, no race condition.
    Memory path: per-patient threading.Lock — prevents lost-update race.
    """
    msg_json = json.dumps(msg.model_dump(), default=str)
    now_str = datetime.now().isoformat()

    # Derive the correct key: prefer clinic-scoped if the in-memory session has clinic_id
    cs = _consultations.get(patient_number)
    _cid = cs.clinic_id if cs else None
    redis_key = _key(f"consult:{_cid}:{patient_number}") if _cid else _key(f"consult:{patient_number}")

    if _lua_append_msg is not None:
        try:
            result = _lua_append_msg(
                keys=[redis_key],
                args=[msg_json, now_str, str(_TTL_CONSULTATION)],
            )
            if isinstance(result, int) and result > 0:
                return  # Redis updated atomically; in-memory is an acceptable stale cache
        except Exception as exc:
            logger.warning("[store] Lua append failed for %s, falling back: %s", patient_number, exc)
        # Lua unavailable or failed — best-effort read-modify-write via Redis
        session = get_consultation(patient_number, clinic_id=_cid)
        if session:
            session.messages.append(msg)
            save_consultation(patient_number, session)
        return

    # Pure in-memory fallback: lock prevents concurrent lost-update
    with _get_consult_lock(patient_number):
        session = _consultations.get(patient_number)
        if session:
            session.messages.append(msg)
            session.last_activity = datetime.now()


def all_consultations() -> dict:
    if _r is not None:
        result = {}
        try:
            for key in _r.scan_iter(f"{_PREFIX}consult:*"):
                phone = key.removeprefix(f"{_PREFIX}consult:")
                data = _rget(key)
                if data:
                    result[phone] = data
            return result
        except Exception:
            pass
    return {k: v.model_dump() for k, v in _consultations.items()}


# ══════════════════════════════════════════════════════════════════════════════
# AFTER-HOURS QUEUE  (Sprint 2)
# Key: clinicai:afterhours:{doctor_number}   TTL 36h  (JSON list)
# ══════════════════════════════════════════════════════════════════════════════

def queue_after_hours_message(
    doctor_number: str,
    from_number: str,
    body: str,
    metadata: dict | None = None,
) -> None:
    """Queue a message for delivery when the clinic re-opens.
    Pass *metadata* with clinic_id / clinic_open_hour / clinic_close_hour so the
    flush job can re-inject each message with its original clinic context.
    """
    entry = {
        "from_number": from_number,
        "body": body,
        "queued_at": datetime.now().isoformat(),
        **(metadata or {}),
    }
    existing = get_after_hours_queue(doctor_number)
    existing.append(entry)
    _rset(_key(f"afterhours:{doctor_number}"), existing, _TTL_AFTERHOURS)
    _after_hours_queues.setdefault(doctor_number, []).append(entry)


def get_after_hours_queue(doctor_number: str) -> list[dict]:
    data = _rget(_key(f"afterhours:{doctor_number}"))
    if data and isinstance(data, list):
        return data
    return list(_after_hours_queues.get(doctor_number, []))


def clear_after_hours_queue(doctor_number: str) -> None:
    _rdel(_key(f"afterhours:{doctor_number}"))
    _after_hours_queues.pop(doctor_number, None)


# ══════════════════════════════════════════════════════════════════════════════
# DOCTOR REPLY CONTEXT  — queue of patients who have messaged the doctor
#
# Stored as a JSON list (most-recent-first, max 10 entries) so multiple
# concurrent patient messages do not silently drop earlier conversations.
# The doctor's next free-text reply goes to the most-recent patient; after
# the reply that entry is popped so the next patient becomes the default.
#
# Key: clinicai:doctor_reply_ctx:{doctor_number}   TTL 7200s (2h)
# ══════════════════════════════════════════════════════════════════════════════

_TTL_REPLY_CTX = 7_200  # 2 hours
_MAX_REPLY_CTX = 10     # maximum pending patients per doctor


def _get_ctx_list(doctor_number: str) -> list[dict]:
    """Load the reply-context as a list, handling both old (dict) and new (list) formats."""
    data = _rget(_key(f"doctor_reply_ctx:{doctor_number}"))
    if data is None:
        mem = _doctor_reply_contexts.get(doctor_number)
        if mem is None:
            return []
        # mem is always a list now, but guard against stale dict in-memory
        return list(mem) if isinstance(mem, list) else ([mem] if isinstance(mem, dict) else [])
    if isinstance(data, dict):
        return [data]   # backward-compat: single-patient old Redis format
    if isinstance(data, list):
        return data
    return []


def save_doctor_reply_context(doctor_number: str, patient_number: str, patient_name: str) -> None:
    """Push a patient to the front of the doctor's reply-context queue (dedup by patient)."""
    entry = {
        "patient_number": patient_number,
        "patient_name": patient_name,
        "saved_at": datetime.now().isoformat(),
    }
    queue = [e for e in _get_ctx_list(doctor_number) if e.get("patient_number") != patient_number]
    queue.insert(0, entry)
    queue = queue[:_MAX_REPLY_CTX]
    _rset(_key(f"doctor_reply_ctx:{doctor_number}"), queue, _TTL_REPLY_CTX)
    _doctor_reply_contexts[doctor_number] = queue   # store full list, not just first item


def get_doctor_reply_context(doctor_number: str) -> Optional[dict]:
    """Return the most-recent patient context, or None if the queue is empty."""
    queue = _get_ctx_list(doctor_number)
    return queue[0] if queue else None


def pop_doctor_reply_context(doctor_number: str, patient_number: str) -> None:
    """Remove a specific patient from the reply-context queue after the doctor has replied."""
    queue = [e for e in _get_ctx_list(doctor_number) if e.get("patient_number") != patient_number]
    if queue:
        _rset(_key(f"doctor_reply_ctx:{doctor_number}"), queue, _TTL_REPLY_CTX)
        _doctor_reply_contexts[doctor_number] = queue   # keep the remaining list
    else:
        _rdel(_key(f"doctor_reply_ctx:{doctor_number}"))
        _doctor_reply_contexts.pop(doctor_number, None)


def clear_doctor_reply_context(doctor_number: str) -> None:
    _rdel(_key(f"doctor_reply_ctx:{doctor_number}"))
    _doctor_reply_contexts.pop(doctor_number, None)


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-WORKER PDF PATH REGISTRY  (MED-7)
# In-process dicts are per-worker; a PDF stored by Worker A is invisible to
# Worker B.  Registering in Redis lets any worker serve a PDF by document_id.
# Key: clinicai:pdf:{namespace}:{document_id}   TTL 7 days
# ══════════════════════════════════════════════════════════════════════════════

_TTL_PDF_REG = 86_400 * 7  # 7 days


def register_pdf(namespace: str, document_id: str, file_path: str) -> None:
    """Store document_id → file_path in Redis so any worker can find the file."""
    _rset(_key(f"pdf:{namespace}:{document_id}"), {"path": file_path}, _TTL_PDF_REG)


def lookup_pdf(namespace: str, document_id: str) -> Optional[str]:
    """Return the stored file path for a document_id, or None if not in Redis."""
    data = _rget(_key(f"pdf:{namespace}:{document_id}"))
    if data and isinstance(data, dict):
        return data.get("path")
    return None


# ── Internal helper ────────────────────────────────────────────────────────────

def _profile_key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())
