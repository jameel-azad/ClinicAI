import asyncio
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


def _messages_url() -> str:
    sid, _, _ = _creds()
    return f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


async def send_whatsapp_message_async(to: str, body: str) -> bool:
    sid, token, from_num = _creds()
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.post(
                _messages_url(),
                data={"From": from_num, "To": _twilio_to(to), "Body": body},
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


def send_whatsapp_message_sync(to: str, body: str) -> bool:
    try:
        return asyncio.run(send_whatsapp_message_async(to, body))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, send_whatsapp_message_async(to, body)).result(timeout=20)


async def send_whatsapp_document_async(
    to: str, document_url: str, filename: str, caption: str = ""
) -> bool:
    sid, token, from_num = _creds()
    try:
        async with httpx.AsyncClient(auth=(sid, token)) as client:
            response = await client.post(
                _messages_url(),
                data={
                    "From": from_num,
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
    to: str, document_url: str, filename: str, caption: str = ""
) -> bool:
    try:
        return asyncio.run(send_whatsapp_document_async(to, document_url, filename, caption))
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                send_whatsapp_document_async(to, document_url, filename, caption),
            ).result(timeout=20)


async def send_whatsapp_interactive_buttons(
    to: str, body_text: str, buttons: list[dict]
) -> bool:
    # Twilio sandbox doesn't support Meta-style interactive buttons — send as plain text
    options = "\n".join(f"• {b['title']}" for b in buttons[:3])
    return await send_whatsapp_message_async(to, f"{body_text}\n\n{options}")


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


def send_whatsapp_message(to: str, body: str) -> bool:
    """Backward-compatible alias."""
    return send_whatsapp_message_sync(to, body)
