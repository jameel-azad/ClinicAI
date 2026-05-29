"""
Terminology lookup service for SNOMED CT and RxNorm codes.

Lookup order for every term:
  1. Local JSON table  (fast, offline, version-controlled)
  2. NLM public API   (authoritative fallback for unmapped terms)
  3. UNKNOWN sentinel (non-blocking — pipeline always completes)

The LLM extracts entity *names*; this module assigns *codes*.
It must never delegate code assignment back to the LLM.
"""

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
_TERMINOLOGY_DIR = Path(__file__).parent.parent.parent / "data" / "terminology"
_SNOMED_FILE = _TERMINOLOGY_DIR / "snomed.json"
_RXNORM_FILE = _TERMINOLOGY_DIR / "rxnorm.json"

# ---------------------------------------------------------------------------
# FHIR system URIs
# ---------------------------------------------------------------------------
SNOMED_SYSTEM = "http://snomed.info/sct"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"

# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

class SnomedResult(TypedDict):
    concept_id: str   # SNOMED CT concept ID, e.g. "38341003", or "UNKNOWN"
    fsn: str          # Fully Specified Name or best available display
    system: str       # always SNOMED_SYSTEM
    source: str       # "local" | "nlm_api" | "unknown"


class RxNormResult(TypedDict):
    rxcui: str        # RxNorm RxCUI, e.g. "17767", or "UNKNOWN"
    display: str      # drug display name
    system: str       # always RXNORM_SYSTEM
    source: str       # "local" | "nlm_api" | "unknown"


# ---------------------------------------------------------------------------
# Module-level caches (reset on server restart — intentional)
# ---------------------------------------------------------------------------
_snomed_table: dict | None = None
_rxnorm_table: dict | None = None
_snomed_cache: dict[str, SnomedResult] = {}  # runtime cache for API hits
_rxnorm_cache: dict[str, RxNormResult] = {}  # runtime cache for API hits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(term: str) -> str:
    """Lowercase, strip parenthetical Hinglish originals, collapse whitespace."""
    term = term.lower().strip()
    term = re.sub(r"\s*\([^)]*\)", "", term)   # remove "(bukhar)" style suffixes
    term = re.sub(r"[^\w\s]", " ", term)
    return re.sub(r"\s+", " ", term).strip()


def _load_snomed_table() -> dict:
    global _snomed_table
    if _snomed_table is None:
        with open(_SNOMED_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _snomed_table = {_normalize(k): v for k, v in data["terms"].items()}
        logger.debug(f"[terminology] SNOMED table loaded: {len(_snomed_table)} terms")
    return _snomed_table


def _load_rxnorm_table() -> dict:
    global _rxnorm_table
    if _rxnorm_table is None:
        with open(_RXNORM_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _rxnorm_table = {_normalize(k): v for k, v in data["terms"].items()}
        logger.debug(f"[terminology] RxNorm table loaded: {len(_rxnorm_table)} terms")
    return _rxnorm_table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_snomed(term: str, timeout: float = 4.0) -> SnomedResult:
    """
    Return SNOMED CT concept ID and FSN for a clinical term.

    Lookup order: local table → NLM Clinical Tables API → UNKNOWN.
    Result is cached in-memory to avoid redundant API calls within a session.
    """
    normalized = _normalize(term)
    if not normalized:
        return _snomed_unknown(term)

    if normalized in _snomed_cache:
        return _snomed_cache[normalized]

    # 1. Local table
    try:
        table = _load_snomed_table()
        if normalized in table:
            entry = table[normalized]
            result: SnomedResult = {
                "concept_id": entry["concept_id"],
                "fsn": entry["fsn"],
                "system": SNOMED_SYSTEM,
                "source": "local",
            }
            _snomed_cache[normalized] = result
            return result
    except Exception as exc:
        logger.warning(f"[terminology] SNOMED local table error: {exc}")

    # 2. NLM Clinical Tables API
    try:
        resp = httpx.get(
            "https://clinicaltables.nlm.nih.gov/api/snomed_ct/v3/search",
            params={"terms": term, "df": "code,consumer_name", "maxList": "1"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Response format: [total_count, code_array, null, [[code, display], ...]]
        if data[0] > 0 and data[3]:
            code, display = data[3][0]
            result = {
                "concept_id": code,
                "fsn": display,
                "system": SNOMED_SYSTEM,
                "source": "nlm_api",
            }
            _snomed_cache[normalized] = result
            logger.info(f"[terminology] SNOMED API hit: '{term}' → {code}")
            return result
    except Exception as exc:
        logger.warning(f"[terminology] SNOMED API lookup failed for '{term}': {exc}")

    # 3. UNKNOWN fallback
    result = _snomed_unknown(term)
    _snomed_cache[normalized] = result
    return result


def lookup_rxnorm(drug_name: str, timeout: float = 4.0) -> RxNormResult:
    """
    Return RxNorm RxCUI and display name for a drug.

    Lookup order: local table → NLM RxNorm API → UNKNOWN.
    Result is cached in-memory to avoid redundant API calls within a session.
    """
    normalized = _normalize(drug_name)
    if not normalized:
        return _rxnorm_unknown(drug_name)

    if normalized in _rxnorm_cache:
        return _rxnorm_cache[normalized]

    # 1. Local table
    try:
        table = _load_rxnorm_table()
        if normalized in table:
            entry = table[normalized]
            result: RxNormResult = {
                "rxcui": entry["rxcui"],
                "display": entry["display"],
                "system": RXNORM_SYSTEM,
                "source": "local",
            }
            _rxnorm_cache[normalized] = result
            return result
    except Exception as exc:
        logger.warning(f"[terminology] RxNorm local table error: {exc}")

    # 2. NLM RxNorm API — two-step: get RxCUI, then fetch display name
    try:
        # Step 2a: resolve name → RxCUI
        resp = httpx.get(
            "https://rxnav.nlm.nih.gov/REST/rxcui.json",
            params={"name": drug_name, "search": "1"},
            timeout=timeout,
        )
        resp.raise_for_status()
        rxcui_list = resp.json().get("idGroup", {}).get("rxnormId", [])
        if rxcui_list:
            rxcui = rxcui_list[0]
            # Step 2b: fetch display name for the RxCUI
            display = drug_name  # fallback display
            try:
                props_resp = httpx.get(
                    f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/properties.json",
                    timeout=timeout,
                )
                props_resp.raise_for_status()
                display = props_resp.json().get("properties", {}).get("name", drug_name)
            except Exception:
                pass  # use raw drug_name as display

            result = {
                "rxcui": rxcui,
                "display": display,
                "system": RXNORM_SYSTEM,
                "source": "nlm_api",
            }
            _rxnorm_cache[normalized] = result
            logger.info(f"[terminology] RxNorm API hit: '{drug_name}' → {rxcui}")
            return result
    except Exception as exc:
        logger.warning(f"[terminology] RxNorm API lookup failed for '{drug_name}': {exc}")

    # 3. UNKNOWN fallback
    result = _rxnorm_unknown(drug_name)
    _rxnorm_cache[normalized] = result
    return result


# ---------------------------------------------------------------------------
# Cache management (useful in tests or when terminology files are updated)
# ---------------------------------------------------------------------------

def clear_caches() -> None:
    """Reset all in-memory caches and reload local tables on next call."""
    global _snomed_table, _rxnorm_table
    _snomed_table = None
    _rxnorm_table = None
    _snomed_cache.clear()
    _rxnorm_cache.clear()


# ---------------------------------------------------------------------------
# Fallback constructors
# ---------------------------------------------------------------------------

def _snomed_unknown(term: str) -> SnomedResult:
    return {"concept_id": "UNKNOWN", "fsn": term, "system": SNOMED_SYSTEM, "source": "unknown"}


def _rxnorm_unknown(drug_name: str) -> RxNormResult:
    return {"rxcui": "UNKNOWN", "display": drug_name, "system": RXNORM_SYSTEM, "source": "unknown"}
