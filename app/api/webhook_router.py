import asyncio
import os
import threading as _threading

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
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

_DEFAULT_OPEN_HOUR  = int(os.getenv("CLINIC_OPEN_HOUR",  "9"))
_DEFAULT_CLOSE_HOUR = int(os.getenv("CLINIC_CLOSE_HOUR", "20"))

# Set DEBUG_ENDPOINTS=true in .env to enable unauthenticated-data debug routes.
# Never set this in production.
_DEBUG_ENDPOINTS = os.getenv("DEBUG_ENDPOINTS", "").lower() == "true"

router = APIRouter(tags=["WhatsApp Webhook"])

# ── Per-patient asyncio locks ─────────────────────────────────────────────────
# Serialises concurrent graph invocations for the same patient phone number.
# This prevents:
#   1. MemorySaver checkpoint corruption (two threads writing same thread_id).
#   2. Consultation-message read-modify-write races on the webhook path.
_patient_locks: dict[str, asyncio.Lock] = {}
_patient_locks_guard = _threading.Lock()


def _get_patient_lock(patient_number: str) -> asyncio.Lock:
    with _patient_locks_guard:
        if patient_number not in _patient_locks:
            _patient_locks[patient_number] = asyncio.Lock()
        return _patient_locks[patient_number]


# ── Twilio signature validation ───────────────────────────────────────────────

async def _verify_twilio_signature(request: Request) -> None:
    """FastAPI dependency: validates X-Twilio-Signature on every inbound webhook.

    Skipped in dev/mock mode (TWILIO_AUTH_TOKEN not set).
    Set WEBHOOK_PUBLIC_URL to the exact URL Twilio posts to (handles reverse
    proxies where the URL visible to FastAPI differs from Twilio's target).
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        return  # dev/mock mode — no credentials, skip validation

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing X-Twilio-Signature header")

    # Reconstruct the URL Twilio signed against.
    base = os.getenv("WEBHOOK_PUBLIC_URL", "").strip().rstrip("/")
    if base:
        url = f"{base}/webhook/twilio"
    else:
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        if forwarded_proto and forwarded_host:
            url = f"{forwarded_proto}://{forwarded_host}{request.url.path}"
        else:
            url = str(request.url).split("?")[0]

    # Read and cache all form fields; Starlette caches body so Form(...) params
    # parsed later by FastAPI still work correctly.
    form = await request.form()
    params = dict(form)

    try:
        from twilio.request_validator import RequestValidator
        if not RequestValidator(auth_token).validate(url, params, signature):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[Webhook] Signature validation error: {exc}")
        raise HTTPException(status_code=403, detail="Signature validation failed")


async def _resolve_clinic(to_number: str, db: AsyncSession):
    """Look up the Clinic row whose twilio_number matches the Twilio To field."""
    try:
        from app.models.clinic import Clinic
        clean = to_number.replace("whatsapp:", "").strip()
        result = await db.execute(
            select(Clinic).where(
                Clinic.is_active.is_(True),
                Clinic.twilio_number.in_([to_number, clean, f"whatsapp:{clean}"]),
            )
        )
        return result.scalar_one_or_none()
    except Exception:
        return None



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
async def twilio_webhook(
    request: Request,
    From: str = Form(...),
    To: str = Form(""),
    Body: str = Form(""),
    NumMedia: str = Form("0"),
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
    ButtonPayload: str = Form(""),
    _sig: None = Depends(_verify_twilio_signature),
    db: AsyncSession = Depends(get_db),
):
    identity = await identify_sender_async(From)
    from_number = identity.phone_number
    message_text = Body.strip()

    # Resolve clinic from Twilio "To" number — gives us per-clinic hours
    clinic = await _resolve_clinic(To, db)
    clinic_id       = clinic.id          if clinic else None
    clinic_open_hour  = clinic.open_hour  if clinic else _DEFAULT_OPEN_HOUR
    clinic_close_hour = clinic.close_hour if clinic else _DEFAULT_CLOSE_HOUR

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
    elif identity.role == "doctor":
        reply = handle_doctor_message(
            message_text,
            identity.display_name,
            identity.phone_number,
            button_payload=ButtonPayload,
        )
    elif (
        NumMedia != "0"
        and MediaUrl0
        and MediaContentType0
        and MediaContentType0.lower() == "application/pdf"
    ):
        print(f"[Webhook] Received PDF: {MediaUrl0}")
        from app.services.pdf_service import handle_incoming_pdf

        reply = await handle_incoming_pdf(MediaUrl0, from_number)
    else:
        config = {"configurable": {"thread_id": from_number}}
        state_update = {
            "from_number": from_number,
            "incoming_message": message_text,
            "clinic_id": clinic_id,
            "clinic_open_hour": clinic_open_hour,
            "clinic_close_hour": clinic_close_hour,
        }

        try:
            # Run the synchronous LangGraph pipeline in a thread pool so it
            # does not block the async event loop.  The per-patient lock
            # serialises concurrent requests for the same patient, which:
            #   (a) prevents MemorySaver checkpoint corruption, and
            #   (b) eliminates consultation-message read-modify-write races.
            patient_lock = _get_patient_lock(from_number)
            async with patient_lock:
                final_state = await asyncio.to_thread(
                    router_graph.invoke, state_update, config=config
                )
            reply = final_state.get("reply_message", "")
            pipeline = final_state.get("pipeline_log", [])
            print(f"[Graph] Pipeline: {' -> '.join(n.split(':')[0] for n in pipeline)}")
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

        except Exception as e:
            print(f"[ERROR] Booking graph failed: {e}")
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

def _require_debug(current_user) -> None:
    """Raises 404 unless DEBUG_ENDPOINTS=true is set in the environment.
    Returns 404 (not 403) so the endpoints appear non-existent to scanners.
    """
    if not _DEBUG_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/debug/sessions")
async def debug_sessions(current_user=Depends(get_current_user)):
    """Shows all active booking sessions. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
    return {"sessions": all_sessions()}


@router.get("/debug/appointments")
async def debug_appointments(current_user=Depends(get_current_user)):
    """Shows all confirmed appointments. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
    return {"appointments": all_appointments()}


@router.get("/debug/identity")
async def debug_identity(current_user=Depends(get_current_user)):
    """Shows configured doctor numbers. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
    return {"doctor_numbers": all_doctor_numbers()}


@router.get("/debug/pending-approvals")
async def debug_pending_approvals(current_user=Depends(get_current_user)):
    """Shows pending doctor approvals. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
    return {"pending_approvals": all_pending_approvals()}


@router.get("/debug/doctors")
async def debug_doctors(current_user=Depends(get_current_user)):
    """Shows saved doctor profiles. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
    return {"doctor_profiles": all_doctor_profiles()}


@router.get("/debug/consultations")
async def debug_consultations(current_user=Depends(get_current_user)):
    """Shows all active/recent consultation sessions. Requires DEBUG_ENDPOINTS=true + auth."""
    _require_debug(current_user)
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
