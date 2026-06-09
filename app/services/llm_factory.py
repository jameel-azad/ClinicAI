"""
LLM factory — encryption helpers, vendor model factory, and LLM connectivity test.

Encryption key: ENCRYPTION_KEY env var (Fernet-compatible base64, 32 bytes).
If not set a stable key is derived from SECRET_KEY so dev environments work
without extra configuration.  Production deployments MUST set ENCRYPTION_KEY.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fernet singleton
# ---------------------------------------------------------------------------

_fernet_instance: Optional[Fernet] = None


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    raw = os.getenv("ENCRYPTION_KEY", "").strip()
    if raw:
        _fernet_instance = Fernet(raw.encode() if isinstance(raw, str) else raw)
    else:
        # Derive a stable key from SECRET_KEY for dev convenience.
        secret = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_USE_32_CHARS_MIN")
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        logger.warning(
            "[llm_factory] ENCRYPTION_KEY not set — deriving Fernet key from SECRET_KEY. "
            "Set ENCRYPTION_KEY in production."
        )
        _fernet_instance = Fernet(derived)
    return _fernet_instance


def encrypt_api_key(plain: str) -> str:
    """Encrypt *plain* API key and return a ciphertext string safe for DB storage."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(enc: str) -> Optional[str]:
    """Decrypt a ciphertext produced by *encrypt_api_key*. Returns None on failure."""
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except (InvalidToken, Exception):
        return None


# ---------------------------------------------------------------------------
# LLM connectivity test
# ---------------------------------------------------------------------------

async def test_llm_connection(
    vendor: str,
    model: str,
    groq_api_key_enc: Optional[str] = None,
    anthropic_api_key_enc: Optional[str] = None,
    openai_api_key_enc: Optional[str] = None,
    google_api_key_enc: Optional[str] = None,
) -> dict:
    """
    Send a minimal "Hello, respond with OK" prompt to the configured LLM.
    Returns {success: bool, response: str, latency_ms: int}.
    """
    prompt = "Hello, respond with OK"
    start = time.monotonic()

    try:
        v = vendor.lower()
        if v == "groq":
            key = (decrypt_api_key(groq_api_key_enc) if groq_api_key_enc else None) or os.getenv("GROQ_API_KEY", "")
            text = await _call_groq(key, model, prompt)
        elif v == "anthropic":
            key = (decrypt_api_key(anthropic_api_key_enc) if anthropic_api_key_enc else None) or os.getenv("ANTHROPIC_API_KEY", "")
            text = await _call_anthropic(key, model, prompt)
        elif v == "openai":
            key = (decrypt_api_key(openai_api_key_enc) if openai_api_key_enc else None) or os.getenv("OPENAI_API_KEY", "")
            text = await _call_openai(key, model, prompt)
        elif v in ("google", "gemini"):
            key = (decrypt_api_key(google_api_key_enc) if google_api_key_enc else None) or os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
            text = await _call_google(key, model, prompt)
        else:
            raise ValueError(f"Unsupported LLM vendor: {vendor!r}")

        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": True, "response": text, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("[llm_factory] LLM connectivity test failed: %s", exc)
        return {"success": False, "response": str(exc), "latency_ms": latency_ms}


async def _call_groq(api_key: str, model: str, prompt: str) -> str:
    import httpx
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 16}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def _call_anthropic(api_key: str, model: str, prompt: str) -> str:
    import httpx
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    payload = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": prompt}]}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()


async def _call_openai(api_key: str, model: str, prompt: str) -> str:
    import httpx
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 16}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def _call_google(api_key: str, model: str, prompt: str) -> str:
    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 16}}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

def get_llm_for_vendor(
    vendor: str,
    model: str,
    enc_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 512,
):
    """Return a LangChain chat model for the given vendor.

    Falls back to the corresponding env-var key when enc_key is None or
    decryption fails, so system-level defaults always work even when a clinic
    has not configured its own key yet.
    """
    api_key: Optional[str]
    v = (vendor or "groq").lower()

    if v == "anthropic":
        from langchain_anthropic import ChatAnthropic
        api_key = (decrypt_api_key(enc_key) if enc_key else None) or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("No Anthropic API key available (clinic config or ANTHROPIC_API_KEY env var)")
        return ChatAnthropic(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)

    elif v == "openai":
        from langchain_openai import ChatOpenAI
        api_key = (decrypt_api_key(enc_key) if enc_key else None) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("No OpenAI API key available (clinic config or OPENAI_API_KEY env var)")
        return ChatOpenAI(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)

    elif v in ("google", "gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = (decrypt_api_key(enc_key) if enc_key else None) or os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY"))
        if not api_key:
            raise ValueError("No Google API key available (clinic config or GEMINI_API_KEY env var)")
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=api_key,
            temperature=temperature, max_output_tokens=max_tokens,
        )

    else:  # groq (default)
        from langchain_groq import ChatGroq
        api_key = (decrypt_api_key(enc_key) if enc_key else None) or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("No Groq API key available (clinic config or GROQ_API_KEY env var)")
        return ChatGroq(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)


def get_groq_client(enc_key: Optional[str] = None):
    """Return a raw Groq client using the clinic-specific key or the env fallback.

    Used for Whisper STT transcription which calls the Groq audio API directly.
    """
    from groq import Groq
    api_key = (decrypt_api_key(enc_key) if enc_key else None) or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("No Groq API key available (clinic config or GROQ_API_KEY env var)")
    return Groq(api_key=api_key)


def get_default_llm():
    """Returns default Groq LLM using env vars."""
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY"),
    )


def get_default_stt_model() -> str:
    return os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")
