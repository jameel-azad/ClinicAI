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
# POST /webhook/twilio — Twilio inbound messages
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
        f"To: {To}"
    )

    # Upsert patient row immediately so the dashboard shows every patient
    # who has ever messaged the clinic — not just post-consultation ones.
    if identity.role == "patient" and clinic_id:
        try:
            from app.services.patient_service import upsert_patient
            asyncio.create_task(upsert_patient(clinic_id, from_number))
        except Exception:
            pass

    reply = ""

    if identity.role == "doctor":
        # Doctor sent an audio/voice note
        if (
            NumMedia != "0"
            and MediaUrl0
            and MediaContentType0
            and MediaContentType0.lower().startswith("audio")
        ):
            reply = await handle_doctor_voice_note(
                media_url=MediaUrl0,
                media_content_type=MediaContentType0,
                doctor_number=identity.phone_number,
                doctor_name=identity.display_name,
                caption=message_text,
            )
        else:
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

            # Update patient name in DB once the booking flow captures it
            captured_name = (final_state.get("session") or {}).get("patient_name")
            if captured_name and clinic_id and identity.role == "patient":
                try:
                    from app.services.patient_service import upsert_patient
                    asyncio.create_task(upsert_patient(clinic_id, from_number, captured_name))
                except Exception:
                    pass

        except Exception as e:
            print(f"[ERROR] Booking graph failed: {e}")
            reply = (
                "Sorry, we're experiencing a technical issue. "
                "Please try again or call the clinic directly."
            )

    if reply:
        await send_whatsapp_message_async(to=from_number, body=reply)


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
