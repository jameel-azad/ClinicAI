import asyncio
import json
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _creds() -> tuple[str, str, str]:
    return (
        os.getenv("TWILIO_ACCOUNT_SID", ""),
        os.getenv("TWILIO_AUTH_TOKEN", ""),
        os.getenv("TWILIO_WHATSAPP_FROM", ""),
    )


def _twilio_to(num: str) -> str:
    n = num.strip()
    return n if n.startswith("whatsapp:") else f"whatsapp:{n}"


def _twilio_from(clinic_number: str | None) -> str:
    """Return the Twilio-formatted From number.

    Uses the clinic's own twilio_number when provided; falls back to the
    global TWILIO_WHATSAPP_FROM env var so single-clinic / dev setups keep
    working without any extra config.
    """
    if clinic_number:
        n = clinic_number.strip()
        return n if n.startswith("whatsapp:") else f"whatsapp:{n}"
    _, _, env_from = _creds()
    return env_from


def _messages_url() -> str:
    sid, _, _ = _creds()
    return f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


async def send_whatsapp_message_async(to: str, body: str, from_number: str | None = None) -> bool:
    sid, token, _ = _creds()
    effective_from = _twilio_from(from_number)
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.post(
                _messages_url(),
                data={"From": effective_from, "To": _twilio_to(to), "Body": body},
                timeout=30,
            )
        response.raise_for_status()
        logger.info("WhatsApp message sent to %s", to)
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("WhatsApp message failed (HTTP %s): %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("WhatsApp message failed: %s", exc)
        return False


def send_whatsapp_message_sync(to: str, body: str, from_number: str | None = None) -> bool:
    try:
        return asyncio.run(send_whatsapp_message_async(to, body, from_number))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, send_whatsapp_message_async(to, body, from_number)).result(timeout=20)


async def send_whatsapp_document_async(
    to: str, document_url: str, filename: str, caption: str = "", from_number: str | None = None
) -> bool:
    sid, token, _ = _creds()
    effective_from = _twilio_from(from_number)
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.post(
                _messages_url(),
                data={
                    "From": effective_from,
                    "To": _twilio_to(to),
                    "Body": caption or filename,
                    "MediaUrl": document_url,
                },
                timeout=30,
            )
        response.raise_for_status()
        logger.info("WhatsApp document sent to %s (%s)", to, filename)
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("WhatsApp document failed (HTTP %s): %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("WhatsApp document failed: %s", exc)
        return False


def send_whatsapp_document_sync(
    to: str, document_url: str, filename: str, caption: str = "", from_number: str | None = None
) -> bool:
    try:
        return asyncio.run(send_whatsapp_document_async(to, document_url, filename, caption, from_number))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                send_whatsapp_document_async(to, document_url, filename, caption, from_number),
            ).result(timeout=20)


async def send_whatsapp_template_async(
    to: str, content_sid: str, variables: dict, from_number: str | None = None
) -> bool:
    """Send a Twilio Content Template message (supports quick-reply buttons)."""
    sid, token, _ = _creds()
    effective_from = _twilio_from(from_number)
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.post(
                _messages_url(),
                data={
                    "From": effective_from,
                    "To": _twilio_to(to),
                    "ContentSid": content_sid,
                    "ContentVariables": json.dumps({str(k): str(v) for k, v in variables.items()}),
                },
                timeout=30,
            )
        response.raise_for_status()
        msg_sid = response.json().get("sid", "?")
        msg_status = response.json().get("status", "?")
        logger.info(
            "WhatsApp template queued to %s | content=%s | msg=%s | status=%s",
            to, content_sid, msg_sid, msg_status,
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("WhatsApp template failed (HTTP %s): %s", exc.response.status_code, exc.response.text)
        return False
    except Exception as exc:
        logger.error("WhatsApp template failed: %s", exc)
        return False


async def check_content_template_approval(content_sid: str) -> str:
    """Return the WhatsApp approval status for a Content Template SID.

    Possible values: 'approved', 'pending', 'rejected', 'unsubmitted', or 'unknown'.
    Used at startup to warn when a template is not yet approved by Meta.
    """
    sid, token, _ = _creds()
    if not sid or not content_sid:
        return "unknown"
    url = f"https://content.twilio.com/v1/Content/{content_sid}/ApprovalRequests"
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.get(url, timeout=10)
        if response.status_code == 404:
            return "unknown"
        response.raise_for_status()
        data = response.json()
        whatsapp = data.get("whatsapp") or {}
        return (whatsapp.get("status") or "unknown").lower()
    except Exception:
        return "unknown"


def send_whatsapp_template_sync(to: str, content_sid: str, variables: dict, from_number: str | None = None) -> bool:
    try:
        return asyncio.run(send_whatsapp_template_async(to, content_sid, variables, from_number))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run, send_whatsapp_template_async(to, content_sid, variables, from_number)
            ).result(timeout=20)


async def send_whatsapp_interactive_buttons(
    to: str, body_text: str, buttons: list[dict], from_number: str | None = None
) -> bool:
    # Fallback for when no Content Template SID is configured
    options = "\n".join(f"• {b['title']}" for b in buttons[:3])
    return await send_whatsapp_message_async(to, f"{body_text}\n\n{options}", from_number)


async def download_media_bytes(url: str) -> bytes | None:
    """Download media from a Twilio MediaUrl (Basic Auth required)."""
    sid, token, _ = _creds()
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except httpx.HTTPStatusError as exc:
        logger.error("download_media_bytes failed (HTTP %s): %s", exc.response.status_code, exc.response.text)
        return None
    except Exception as exc:
        logger.error("download_media_bytes failed: %s", exc)
        return None


def send_whatsapp_message(to: str, body: str, from_number: str | None = None) -> bool:
    """Backward-compatible alias."""
    return send_whatsapp_message_sync(to, body, from_number)
