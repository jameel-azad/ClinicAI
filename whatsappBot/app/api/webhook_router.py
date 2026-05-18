import os
from fastapi import APIRouter, Form, Request, Response
from dotenv import load_dotenv

from app.graph.booking import booking_graph
from app.services.whatsapp import send_whatsapp_message
from app.services.store import all_sessions, all_appointments

load_dotenv()

router = APIRouter(tags=["WhatsApp Webhook"])


@router.get("/webhook/twilio")
async def webhook_health():
    """Simple health check for the Twilio webhook endpoint."""
    return {"status": "ok", "message": "ClinicAI Twilio webhook is live"}


@router.post("/webhook/twilio")
async def twilio_webhook(
    request: Request,
    From: str = Form(...),        # e.g. "whatsapp:+917766862219"
    Body: str = Form(""),         # The patient's message text
    NumMedia: str = Form("0"),    # Number of media attachments
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
):
    # Normalise the from number — strip "whatsapp:" prefix for internal use
    from_number = From.replace("whatsapp:", "").strip()
    message_text = Body.strip()

    print(f"\n[Webhook] From: {from_number} | Message: {message_text} | Media: {NumMedia}")

    reply = ""

    # ── Check for PDF media ────────────────────────────────────────────────────
    if NumMedia != "0" and MediaUrl0 and MediaContentType0 == "application/pdf":
        print(f"[Webhook] Received PDF: {MediaUrl0}")
        from app.services.pdf_service import handle_incoming_pdf
        reply = await handle_incoming_pdf(MediaUrl0)
    else:
        # ── Run the booking graph ──────────────────────────────────────────────────
        config = {"configurable": {"thread_id": from_number}}
        state_update = {
            "from_number": from_number,
            "incoming_message": message_text,
        }

        try:
            final_state = booking_graph.invoke(state_update, config=config)
            reply = final_state.get("reply_message", "")
            pipeline = final_state.get("pipeline_log", [])
            print(f"[Graph] Pipeline: {' → '.join(n.split(':')[0] for n in pipeline)}")
            print(f"[Graph] Reply: {reply[:80]}...")
        except Exception as e:
            print(f"[ERROR] Booking graph failed: {e}")
            reply = (
                "Sorry, we're experiencing a technical issue. "
                "Please try again or call the clinic directly."
            )

    # ── Send reply via Twilio ──────────────────────────────────────────────────
    if reply:
        # Send to the full whatsapp: format number
        await send_whatsapp_message(to=From, body=reply)

    # ── Return empty TwiML to Twilio (200 OK) ─────────────────────────────────
    # Twilio expects either a TwiML response OR a 200 with empty body.
    # We use the outgoing API approach so we return empty TwiML here.
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
        status_code=200,
    )


# ── Debug / admin endpoints ────────────────────────────────────────────────────

@router.get("/debug/sessions")
async def debug_sessions():
    """Shows all active booking sessions. For development only."""
    return {"sessions": all_sessions()}


@router.get("/debug/appointments")
async def debug_appointments():
    """Shows all confirmed appointments. For development only."""
    return {"appointments": all_appointments()}
