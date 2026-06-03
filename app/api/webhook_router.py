import asyncio
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from dotenv import load_dotenv

from app.graph.router import router_graph
from app.services.clinical_scribe import get_scribe_pdf_path, handle_doctor_voice_note
from app.services.pdf_service import get_lab_pdf_path
from app.services.doctor import handle_doctor_message
from app.services.identity import all_doctor_numbers, identify_sender_async
from app.services.store import (
    all_appointments,
    all_consultations,
    all_doctor_profiles,
    all_pending_approvals,
    all_sessions,
)
from app.services.whatsapp import (
    download_media_bytes,
    get_media_download_url,
    send_whatsapp_message_async,
)

load_dotenv()

router = APIRouter(tags=["WhatsApp Webhook"])

# ---------------------------------------------------------------------------
# Mime-type → file extension mapping for Meta audio messages
# ---------------------------------------------------------------------------
_AUDIO_MIME_TO_EXT: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "application/ogg": ".ogg",
    # Meta commonly sends voice notes as these types
    "audio/aac": ".aac",
    "audio/amr": ".amr",
}


# ---------------------------------------------------------------------------
# GET /webhook/whatsapp — Meta hub verification
# ---------------------------------------------------------------------------

@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake."""
    expected_token = os.getenv("META_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Invalid verify token")


# ---------------------------------------------------------------------------
# POST /webhook/whatsapp — Meta Cloud API inbound messages
# ---------------------------------------------------------------------------

@router.post("/webhook/whatsapp")
async def meta_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive inbound WhatsApp messages from the Meta Cloud API.
    Always returns 200 immediately; all processing runs in a background task.
    """
    try:
        payload = await request.json()
    except Exception:
        # Malformed body — still return 200 so Meta doesn't retry indefinitely
        return Response(content="ok", status_code=200)

    # Ignore non-whatsapp_business_account objects (e.g. status updates from
    # other Meta products) quickly.
    if payload.get("object") != "whatsapp_business_account":
        return Response(content="ok", status_code=200)

    # Fan out — each change entry may carry multiple messages
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Delivery/read receipts arrive under "statuses" — skip them
            if "statuses" in value and "messages" not in value:
                continue

            messages = value.get("messages", [])
            if not messages:
                continue

            metadata = value.get("metadata", {})
            to_number = metadata.get("display_phone_number", "")

            for message in messages:
                # Schedule each message as an independent background task so
                # one slow handler does not delay others.
                background_tasks.add_task(
                    _handle_meta_message, message, to_number
                )

    return Response(content="ok", status_code=200)


# ---------------------------------------------------------------------------
# Backward-compat alias: POST /webhook/twilio → same handler
# ---------------------------------------------------------------------------

@router.post("/webhook/twilio")
async def twilio_compat_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Legacy Twilio webhook path kept for backward compatibility.
    Delegates to the Meta handler — callers should migrate to /webhook/whatsapp.
    """
    return await meta_webhook(request, background_tasks)


# ---------------------------------------------------------------------------
# Core message processing (runs in background task)
# ---------------------------------------------------------------------------

async def _handle_meta_message(message: dict, to_number: str) -> None:
    """
    Parse a single Meta message object and route it to the appropriate handler.
    Sends a WhatsApp reply when the handler returns a non-empty string.
    """
    from_raw: str = message.get("from", "")
    if not from_raw:
        return

    # Meta already sends E.164 (+91...) — normalise once
    from_number = from_raw if from_raw.startswith("+") else f"+{from_raw}"

    message_type: str = message.get("type", "text")

    identity = await identify_sender_async(from_number)

    print(
        f"\n[Webhook] From: {from_number} | Role: {identity.role} | "
        f"Type: {message_type} | To: {to_number}"
    )

    reply = ""

    try:
        if message_type == "audio":
            reply = await _handle_audio_message(message, identity)

        elif message_type == "document":
            reply = await _handle_document_message(message, identity, from_number)

        elif message_type == "interactive":
            reply = await _handle_interactive_message(message, identity)

        else:
            # text / image / sticker / location / contacts / unknown — treat as text
            text_obj = message.get("text", {})
            body = text_obj.get("body", "").strip() if isinstance(text_obj, dict) else ""
            reply = await _handle_text_message(body, identity)

    except Exception as exc:
        print(f"[ERROR] _handle_meta_message failed for {from_number}: {exc}")
        reply = (
            "Sorry, we're experiencing a technical issue. "
            "Please try again or call the clinic directly."
        )

    if reply:
        await send_whatsapp_message_async(to=from_number, body=reply)


# ---------------------------------------------------------------------------
# Per-type handlers
# ---------------------------------------------------------------------------

async def _handle_audio_message(message: dict, identity) -> str:
    """Download Meta audio and pass to the voice-note / scribe pipeline."""
    audio_obj = message.get("audio", {})
    media_id: str = audio_obj.get("id", "")
    mime_type: str = audio_obj.get("mime_type", "audio/ogg")
    caption: str = message.get("caption", "")

    if not media_id:
        return "I received an audio message but could not read the media ID."

    # Build a temporary file URL that the existing pipeline accepts
    media_url = await get_media_download_url(media_id)
    if not media_url:
        return "Could not retrieve the audio from WhatsApp. Please try again."

    if identity.role == "doctor":
        return await handle_doctor_voice_note(
            media_url=media_url,
            media_content_type=mime_type,
            doctor_number=identity.phone_number,
            doctor_name=identity.display_name,
            caption=caption,
        )

    # Non-doctor audio — not currently handled; acknowledge receipt
    return "Thank you for the audio message. Please send a text message so I can assist you."


async def _handle_document_message(message: dict, identity, from_number: str) -> str:
    """Download a document and pass to the PDF pipeline if it is a PDF."""
    doc_obj = message.get("document", {})
    media_id: str = doc_obj.get("id", "")
    mime_type: str = doc_obj.get("mime_type", "")
    filename: str = doc_obj.get("filename", "document")

    if not media_id:
        return "I received a document but could not read the media ID."

    is_pdf = (
        mime_type.lower() == "application/pdf"
        or filename.lower().endswith(".pdf")
    )

    if not is_pdf:
        return "I received a file, but only PDF documents are currently supported."

    print(f"[Webhook] Received PDF document (media_id={media_id}) from {from_number}")

    # Download bytes and write to a temp file so the existing pipeline works
    pdf_bytes = await download_media_bytes(media_id)
    if not pdf_bytes:
        return "Could not download the PDF from WhatsApp. Please try again."

    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)

        # Build a file:// URL the existing handler can read, or pass as path.
        # handle_incoming_pdf currently accepts a URL string; wrap with file:// so
        # httpx/requests won't try to re-download from Meta.
        file_url = f"file://{temp_path}"

        from app.services.pdf_service import handle_incoming_pdf
        reply = await handle_incoming_pdf(file_url, from_number)
    finally:
        # Clean up temp file after pipeline is done
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    return reply


async def _handle_interactive_message(message: dict, identity) -> str:
    """
    Handle Meta interactive/button_reply messages.

    Meta interactive payload structure:
      message["interactive"]["type"] == "button_reply"
      message["interactive"]["button_reply"]["id"]    — button ID
      message["interactive"]["button_reply"]["title"] — button label

    Button IDs currently in use:
      Appointment approval : "approve", "reject", "suggest_time"
      SOAP approval        : "soap_approve", "soap_reject"
    """
    interactive = message.get("interactive", {})
    interactive_type = interactive.get("type", "")

    button_payload = ""
    button_title = ""

    if interactive_type == "button_reply":
        btn = interactive.get("button_reply", {})
        button_payload = btn.get("id", "")
        button_title = btn.get("title", "")
    elif interactive_type == "list_reply":
        lst = interactive.get("list_reply", {})
        button_payload = lst.get("id", "")
        button_title = lst.get("title", "")

    print(
        f"[Webhook] Interactive: type={interactive_type} "
        f"id={button_payload!r} title={button_title!r}"
    )

    if not button_payload:
        return ""

    if identity.role == "doctor":
        # Route to doctor handler with button_payload — same interface as Twilio ButtonPayload
        reply = handle_doctor_message(
            message_text="",
            doctor_name=identity.display_name,
            doctor_number=identity.phone_number,
            button_payload=button_payload,
        )
        return reply or ""

    # Patient-side interactive (e.g. quick-reply from booking flow)
    config = {"configurable": {"thread_id": identity.phone_number}}
    state_update = {
        "from_number": identity.phone_number,
        "incoming_message": button_payload,
    }
    return await _invoke_router_graph(state_update, config, identity.phone_number)


async def _handle_text_message(body: str, identity) -> str:
    """Route a plain text message to the doctor or patient pipeline."""
    if identity.role == "doctor":
        reply = handle_doctor_message(
            message_text=body,
            doctor_name=identity.display_name,
            doctor_number=identity.phone_number,
            button_payload="",
        )
        return reply or ""

    config = {"configurable": {"thread_id": identity.phone_number}}
    state_update = {
        "from_number": identity.phone_number,
        "incoming_message": body,
    }
    return await _invoke_router_graph(state_update, config, identity.phone_number)


async def _invoke_router_graph(
    state_update: dict,
    config: dict,
    from_number: str,
) -> str:
    """
    Run the LangGraph router in a thread (it is synchronous) and persist the
    session reply context to Redis for context-aware classification.
    """
    try:
        final_state = await asyncio.to_thread(
            router_graph.invoke, state_update, config
        )
        reply: str = final_state.get("reply_message", "")
        pipeline = final_state.get("pipeline_log", [])
        print(f"[Graph] Pipeline: {' -> '.join(n.split(':')[0] for n in pipeline)}")
        if reply:
            print(f"[Graph] Reply: {reply[:80]}...")

        # Persist session to Redis with last_bot_response for context-aware classification
        if reply and final_state.get("session"):
            from app.schemas import BookingSession
            from app.services.store import save_session
            try:
                sess_dict = dict(final_state["session"])
                sess_dict["last_bot_response"] = reply[:300]
                save_session(BookingSession(**sess_dict))
            except Exception as sess_err:
                print(f"[WARN] Could not persist session: {sess_err}")

        return reply

    except Exception as exc:
        print(f"[ERROR] Booking graph failed for {from_number}: {exc}")
        return (
            "Sorry, we're experiencing a technical issue. "
            "Please try again or call the clinic directly."
        )


# ---------------------------------------------------------------------------
# Debug endpoints (unchanged)
# ---------------------------------------------------------------------------

@router.get("/debug/sessions")
async def debug_sessions():
    """Shows all active booking sessions. For development only."""
    return {"sessions": all_sessions()}


@router.get("/debug/appointments")
async def debug_appointments():
    """Shows all confirmed appointments. For development only."""
    return {"appointments": all_appointments()}


@router.get("/debug/identity")
async def debug_identity():
    """Shows configured doctor numbers. For development only."""
    return {"doctor_numbers": all_doctor_numbers()}


@router.get("/debug/pending-approvals")
async def debug_pending_approvals():
    """Shows pending doctor approvals. For development only."""
    return {"pending_approvals": all_pending_approvals()}


@router.get("/debug/doctors")
async def debug_doctors():
    """Shows saved doctor profiles. For development only."""
    return {"doctor_profiles": all_doctor_profiles()}


@router.get("/debug/consultations")
async def debug_consultations():
    """Shows all active/recent consultation sessions. For development only."""
    return {"consultations": all_consultations()}


# ---------------------------------------------------------------------------
# PDF download endpoints (unchanged)
# ---------------------------------------------------------------------------

@router.get("/lab-report/pdf/{document_id}", include_in_schema=False)
async def download_lab_pdf(document_id: str):
    pdf_path = get_lab_pdf_path(document_id)
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Lab report PDF not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="lab_report.pdf",
    )


@router.get("/scribe/pdf/{document_id}", include_in_schema=False)
async def download_scribe_pdf(document_id: str):
    pdf_path = get_scribe_pdf_path(document_id)
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Transcript PDF not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="clinical_note.pdf",
    )
