"""
Doctor directory service — multi-doctor hospital support.

Responsibilities:
- Match doctors to patient symptoms via specialty keywords (no LLM)
- Format a numbered doctor list for WhatsApp
- Resolve a patient's selection (number / name / specialty) back to a doctor name
- Seed demo doctors for development

The identity/auth system (DOCTOR_WHATSAPP_NUMBERS) is separate. This module
only reads doctor *profiles* from the store. A doctor can appear in the
directory without being in the env var (display-only), but must be in the env
var to receive WhatsApp approval messages.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Specialty → symptom keyword mapping
# All keys are the canonical specialty name stored in doctor profiles.
# ---------------------------------------------------------------------------
_SPECIALTY_KEYWORDS: dict[str, list[str]] = {
    "General Medicine": [
        "fever", "cold", "cough", "flu", "weakness", "fatigue", "tiredness",
        "general", "checkup", "routine", "body pain", "viral", "infection",
        "headache", "bukhar", "dard",
    ],
    "Cardiology": [
        "chest pain", "heart", "palpitations", "breathlessness", "shortness of breath",
        "hypertension", "high blood pressure", "bp", "cholesterol", "cardiac",
        "angina", "irregular heartbeat",
    ],
    "Orthopedics": [
        "joint pain", "back pain", "knee pain", "bone", "fracture", "spine",
        "arthritis", "shoulder pain", "neck pain", "muscle pain", "sports injury",
        "kamar dard", "ghutne", "hadi",
    ],
    "Diabetology / Endocrinology": [
        "diabetes", "sugar", "insulin", "thyroid", "weight gain", "weight loss",
        "blood sugar", "glucose", "hormones", "endocrine", "thyroxine",
    ],
    "Gastroenterology": [
        "stomach pain", "abdominal pain", "diarrhea", "vomiting", "nausea",
        "acid reflux", "acidity", "constipation", "loose motions", "liver",
        "indigestion", "bloating", "pet dard", "ulcer", "ibs",
    ],
    "Dermatology": [
        "skin", "rash", "itching", "acne", "eczema", "psoriasis", "hair loss",
        "allergy", "urticaria", "pigmentation", "wounds", "fungal",
    ],
    "ENT": [
        "ear pain", "earache", "sore throat", "runny nose", "nasal", "sinusitis",
        "hearing", "tonsils", "voice", "hoarseness", "sneezing", "blocked nose",
    ],
    "Gynecology": [
        "pregnancy", "periods", "menstrual", "pcod", "pcos", "fertility",
        "women", "uterus", "ovary", "discharge", "breast",
    ],
    "Pediatrics": [
        "child", "baby", "infant", "kids", "toddler", "vaccination", "growth",
        "bache", "bachcha",
    ],
    "Pulmonology": [
        "asthma", "breathing", "lung", "respiratory", "bronchitis", "copd",
        "oxygen", "inhaler", "wheezing",
    ],
    "Nephrology": [
        "kidney", "urine", "dialysis", "renal", "creatinine", "protein in urine",
        "urinary tract", "uti",
    ],
    "Ophthalmology": [
        "eye", "vision", "glasses", "cataract", "retina", "eye pain",
        "blurred vision", "eye infection", "conjunctivitis",
    ],
    "Neurology": [
        "migraine", "seizure", "paralysis", "numbness", "nerves", "tremor",
        "memory", "dizziness", "vertigo", "stroke",
    ],
    "Psychiatry": [
        "depression", "anxiety", "mental", "stress", "insomnia", "sleep",
        "panic", "mood", "psychological",
    ],
}

# Word equivalents for numeric selection
_NUMBER_WORDS = {
    "one": 1, "first": 1, "1st": 1,
    "two": 2, "second": 2, "2nd": 2,
    "three": 3, "third": 3, "3rd": 3,
    "four": 4, "fourth": 4, "4th": 4,
    "five": 5, "fifth": 5, "5th": 5,
}


# ---------------------------------------------------------------------------
# Core directory functions
# ---------------------------------------------------------------------------

def match_by_symptoms(symptoms: list[str]) -> list[dict]:
    """
    Return doctor profiles ranked by how well their specialty matches the symptoms.
    Falls back to all_doctors() if fewer than 2 doctors have any keyword match.
    Always returns a non-empty list if any profiles exist.
    """
    from app.services.store import all_doctor_profiles

    profiles = list(all_doctor_profiles().values())
    if not profiles:
        return []

    symptom_text = " ".join(s.lower() for s in symptoms)

    scored: list[tuple[int, dict]] = []
    for profile in profiles:
        specialty = (profile.get("specialty") or "").strip()
        keywords = _keywords_for_specialty(specialty)
        score = sum(1 for kw in keywords if kw in symptom_text)
        scored.append((score, profile))

    scored.sort(key=lambda t: (-t[0], (t[1].get("name") or "").lower()))
    matched = [p for s, p in scored if s > 0]

    if len(matched) >= 2:
        return matched
    # Fewer than 2 specialty matches — return everyone so patient always sees options
    return [p for _, p in scored]


def all_doctors() -> list[dict]:
    """Return all doctor profiles sorted alphabetically by name."""
    from app.services.store import all_doctor_profiles

    profiles = list(all_doctor_profiles().values())
    return sorted(profiles, key=lambda p: (p.get("name") or "").lower())


def format_for_whatsapp(doctors: list[dict]) -> str:
    """Build the numbered doctor list WhatsApp message."""
    if not doctors:
        return "No doctors are currently available. Please call the clinic directly."

    lines = ["*Available Doctors:*\n"]
    for i, doc in enumerate(doctors, start=1):
        name = doc.get("name") or "Doctor"
        specialty = doc.get("specialty") or "General"
        hours = doc.get("working_hours") or ""
        line = f"{i}. *{name}* — {specialty}"
        if hours:
            line += f"\n   \U0001f550 {hours}"
        lines.append(line)

    lines.append("\nReply with a number (e.g. *1*) or the doctor's name.")
    return "\n".join(lines)


def resolve_selection(reply: str, doctors: list[dict]) -> str | None:
    """
    Try to resolve a patient's reply to a doctor name from the given list.

    Tries in order:
    1. Digit (e.g. "1", "2")
    2. Number word (e.g. "one", "second")
    3. Doctor name fuzzy match against the list
    4. Specialty keyword match against the list
    Returns None if nothing resolves.
    """
    if not doctors:
        return None

    text = reply.strip()

    # 1. Pure digit
    if re.fullmatch(r"\d+", text):
        idx = int(text) - 1
        if 0 <= idx < len(doctors):
            return doctors[idx].get("name")
        return None

    lower = text.lower()

    # 2. Number word
    for word, num in _NUMBER_WORDS.items():
        if word in lower.split():
            idx = num - 1
            if 0 <= idx < len(doctors):
                return doctors[idx].get("name")

    # 3. Doctor name match (from the displayed list only)
    for doc in doctors:
        name = (doc.get("name") or "").lower()
        # Check if any significant part of the name appears in the reply
        name_parts = [p for p in name.split() if len(p) > 2 and p not in {"the", "dr.", "dr"}]
        if any(part in lower for part in name_parts):
            return doc.get("name")

    # 4. Specialty keyword match (returns first matching doctor in list)
    for doc in doctors:
        specialty = (doc.get("specialty") or "").lower()
        keywords = _keywords_for_specialty(specialty)
        if any(kw in lower for kw in keywords):
            return doc.get("name")
        # Also match the specialty name itself
        if specialty and specialty in lower:
            return doc.get("name")

    return None


# ---------------------------------------------------------------------------
# Specialty keyword lookup
# ---------------------------------------------------------------------------

def _keywords_for_specialty(specialty: str) -> list[str]:
    """Return keyword list for a specialty string (case-insensitive match)."""
    specialty_lower = specialty.lower()
    for key, keywords in _SPECIALTY_KEYWORDS.items():
        if key.lower() in specialty_lower or specialty_lower in key.lower():
            return keywords
    # Partial word match fallback
    for key, keywords in _SPECIALTY_KEYWORDS.items():
        key_words = key.lower().split()
        if any(w in specialty_lower for w in key_words if len(w) > 3):
            return keywords
    return []


# ---------------------------------------------------------------------------
# Demo doctor seeding
# ---------------------------------------------------------------------------

_DEMO_DOCTORS = [
    {
        "name": "Dr Aryan Mehta",
        "specialty": "Cardiology",
        "working_hours": "Mon-Sat 10 AM-2 PM, 5 PM-8 PM",
        "appointment_duration_minutes": 30,
        "buffer_minutes": 5,
        "doctor_number": "+919900000001",
        "google_email": "",
        "calendar_connected": False,
        "calendar_status": "Not configured",
    },
    {
        "name": "Dr Priya Patel",
        "specialty": "General Medicine",
        "working_hours": "Mon-Sun 9 AM-6 PM",
        "appointment_duration_minutes": 20,
        "buffer_minutes": 5,
        "doctor_number": "+919900000002",
        "google_email": "",
        "calendar_connected": False,
        "calendar_status": "Not configured",
    },
    {
        "name": "Dr Rohit Singh",
        "specialty": "Orthopedics",
        "working_hours": "Tue-Sat 11 AM-3 PM",
        "appointment_duration_minutes": 30,
        "buffer_minutes": 10,
        "doctor_number": "+919900000003",
        "google_email": "",
        "calendar_connected": False,
        "calendar_status": "Not configured",
    },
    {
        "name": "Dr Sneha Kumar",
        "specialty": "Diabetology / Endocrinology",
        "working_hours": "Mon-Fri 10 AM-4 PM",
        "appointment_duration_minutes": 30,
        "buffer_minutes": 5,
        "doctor_number": "+919900000004",
        "google_email": "",
        "calendar_connected": False,
        "calendar_status": "Not configured",
    },
    {
        "name": "Dr Kavita Rao",
        "specialty": "Gynecology",
        "working_hours": "Mon-Sat 9 AM-1 PM",
        "appointment_duration_minutes": 25,
        "buffer_minutes": 5,
        "doctor_number": "+919900000005",
        "google_email": "",
        "calendar_connected": False,
        "calendar_status": "Not configured",
    },
]


def seed_demo_doctors() -> None:
    """
    Seed demo doctor profiles into the store at startup.
    Only seeds a doctor if no profile for that number exists yet.
    Safe to call on every startup — idempotent.
    """
    from app.services.store import get_doctor_profile, save_doctor_profile

    seeded = 0
    for doc in _DEMO_DOCTORS:
        number = doc["doctor_number"]
        if not get_doctor_profile(number):
            save_doctor_profile(number, doc)
            seeded += 1

    if seeded:
        logger.info(f"[doctor_directory] Seeded {seeded} demo doctor profile(s)")
    else:
        logger.info("[doctor_directory] Demo doctors already present — skipping seed")
