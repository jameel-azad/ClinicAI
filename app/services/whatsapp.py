import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
_BASE = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v21.0')}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN', '')}",
        "Content-Type": "application/json",
    }


def _phone_number_id() -> str:
    return os.getenv("META_PHONE_NUMBER_ID", "")


def _clean_number(num: str) -> str:
    return num.replace("whatsapp:", "").strip()


async def send_whatsapp_message_async(to: str, body: str) -> bool:
    url = f"{_BASE}/{_phone_number_id()}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": _clean_number(to),
        "type": "text",
        "text": {"body": body},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=_headers(), timeout=30)
        response.raise_for_status()
        logger.info("WhatsApp message sent to %s", _clean_number(to))
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp message failed (HTTP %s): %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("WhatsApp message failed: %s", exc)
        return False


def send_whatsapp_message_sync(to: str, body: str) -> bool:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, send_whatsapp_message_async(to, body))
                return future.result()
        else:
            return loop.run_until_complete(send_whatsapp_message_async(to, body))
    except RuntimeError:
        return asyncio.run(send_whatsapp_message_async(to, body))


async def send_whatsapp_document_async(
    to: str, document_url: str, filename: str, caption: str = ""
) -> bool:
    url = f"{_BASE}/{_phone_number_id()}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": _clean_number(to),
        "type": "document",
        "document": {
            "link": document_url,
            "filename": filename,
            "caption": caption,
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=_headers(), timeout=30)
        response.raise_for_status()
        logger.info(
            "WhatsApp document sent to %s (file: %s)", _clean_number(to), filename
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp document failed (HTTP %s): %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("WhatsApp document failed: %s", exc)
        return False


def send_whatsapp_document_sync(
    to: str, document_url: str, filename: str, caption: str = ""
) -> bool:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    send_whatsapp_document_async(to, document_url, filename, caption),
                )
                return future.result()
        else:
            return loop.run_until_complete(
                send_whatsapp_document_async(to, document_url, filename, caption)
            )
    except RuntimeError:
        return asyncio.run(
            send_whatsapp_document_async(to, document_url, filename, caption)
        )


async def send_whatsapp_interactive_buttons(
    to: str, body_text: str, buttons: list[dict]
) -> bool:
    url = f"{_BASE}/{_phone_number_id()}/messages"
    capped_buttons = buttons[:3]
    payload = {
        "messaging_product": "whatsapp",
        "to": _clean_number(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": b["id"], "title": b["title"]},
                    }
                    for b in capped_buttons
                ]
            },
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=_headers(), timeout=30)
        response.raise_for_status()
        logger.info(
            "WhatsApp interactive buttons sent to %s (%d buttons)",
            _clean_number(to),
            len(capped_buttons),
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "WhatsApp interactive buttons failed (HTTP %s): %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("WhatsApp interactive buttons failed: %s", exc)
        return False


async def get_media_download_url(media_id: str) -> str | None:
    url = f"{_BASE}/{media_id}"
    auth_headers = {"Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN', '')}"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=auth_headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        media_url = data.get("url")
        if not media_url:
            logger.error("No 'url' field in media metadata response: %s", data)
            return None
        return media_url
    except httpx.HTTPStatusError as exc:
        logger.error(
            "get_media_download_url failed (HTTP %s): %s",
            exc.response.status_code,
            exc.response.text,
        )
        return None
    except Exception as exc:
        logger.error("get_media_download_url failed: %s", exc)
        return None


async def download_media_bytes(media_id: str) -> bytes | None:
    media_url = await get_media_download_url(media_id)
    if not media_url:
        return None

    auth_headers = {"Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN', '')}"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, headers=auth_headers, timeout=60)
        response.raise_for_status()
        return response.content
    except httpx.HTTPStatusError as exc:
        logger.error(
            "download_media_bytes failed (HTTP %s): %s",
            exc.response.status_code,
            exc.response.text,
        )
        return None
    except Exception as exc:
        logger.error("download_media_bytes failed: %s", exc)
        return None


def send_whatsapp_message(to: str, body: str) -> bool:
    """Backward-compatible alias for send_whatsapp_message_sync."""
    return send_whatsapp_message_sync(to, body)
