import os
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")


def _get_client():
    """Returns a Twilio REST client. Raises clearly if credentials are missing."""
    if not ACCOUNT_SID or not AUTH_TOKEN:
        raise RuntimeError(
            "Twilio credentials missing. Set TWILIO_ACCOUNT_SID and "
            "TWILIO_AUTH_TOKEN in your .env file."
        )
    from twilio.rest import Client
    return Client(ACCOUNT_SID, AUTH_TOKEN)


def send_whatsapp_message_sync(to: str, body: str) -> bool:
    # Normalise to Twilio whatsapp: format
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    # Dev mode — no credentials set, just print
    if not ACCOUNT_SID or not AUTH_TOKEN:
        print(f"\n[Twilio MOCK] ──────────────────────────")
        print(f"  To  : {to}")
        print(f"  Body: {body}")
        print(f"────────────────────────────────────────\n")
        return True

    try:
        client = _get_client()
        message = client.messages.create(
            from_=FROM_NUMBER,
            body=body,
            to=to,
        )
        print(f"[Twilio] Sent SID={message.sid} to {to}")
        return True
    except Exception as e:
        print(f"[Twilio ERROR] {e}")
        return False


def send_whatsapp_media_sync(to: str, body: str, media_url: str) -> bool:
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    if not ACCOUNT_SID or not AUTH_TOKEN:
        print("\n[Twilio MOCK MEDIA]")
        print(f"  To       : {to}")
        print(f"  Body     : {body}")
        print(f"  Media URL: {media_url}\n")
        return True

    try:
        client = _get_client()
        message = client.messages.create(
            from_=FROM_NUMBER,
            body=body,
            media_url=[media_url],
            to=to,
        )
        print(f"[Twilio] Sent media SID={message.sid} to {to}")
        return True
    except Exception as e:
        print(f"[Twilio MEDIA ERROR] {e}")
        return False


def send_whatsapp_template_sync(to: str, content_sid: str, content_variables: dict) -> bool:
    """Send a Twilio Content Template message (e.g. buttons). Cannot be combined with body/media."""
    import json
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    if not ACCOUNT_SID or not AUTH_TOKEN:
        print(f"\n[Twilio MOCK TEMPLATE]")
        print(f"  To        : {to}")
        print(f"  ContentSid: {content_sid}")
        print(f"  Variables : {content_variables}\n")
        return True

    try:
        client = _get_client()
        message = client.messages.create(
            content_sid=content_sid,
            content_variables=json.dumps(content_variables),
            from_=FROM_NUMBER,
            to=to,
        )
        print(f"[Twilio] Sent template SID={message.sid} to {to}")
        return True
    except Exception as e:
        print(f"[Twilio TEMPLATE ERROR] {e}")
        return False


async def send_whatsapp_message(to: str, body: str) -> bool:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, send_whatsapp_message_sync, to, body
    )


async def send_whatsapp_media(to: str, body: str, media_url: str) -> bool:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, send_whatsapp_media_sync, to, body, media_url
    )
