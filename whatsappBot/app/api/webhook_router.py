from fastapi import APIRouter, Form, Request, Response
from dotenv import load_dotenv

from app.graph.booking import booking_graph
from app.services.doctor import handle_doctor_message
from app.services.identity import all_doctor_numbers, identify_sender
from app.services.store import all_appointments, all_pending_approvals, all_sessions
from app.services.store import all_doctor_profiles
from app.services.whatsapp import send_whatsapp_message

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
    Body: str = Form(""),         # Incoming WhatsApp text
    NumMedia: str = Form("0"),    # Number of media attachments
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
):
    identity = identify_sender(From)
    from_number = identity.phone_number
    message_text = Body.strip()

    print(
        f"\n[Webhook] From: {from_number} | Role: {identity.role} | "
        f"Message: {message_text} | Media: {NumMedia}"
    )

    reply = ""

    if identity.role == "doctor":
        reply = handle_doctor_message(
            message_text,
            identity.display_name,
            identity.phone_number,
        )
    elif (
        NumMedia != "0"
        and MediaUrl0
        and MediaContentType0
        and MediaContentType0.lower() == "application/pdf"
    ):
        print(f"[Webhook] Received PDF: {MediaUrl0}")
        from app.services.pdf_service import handle_incoming_pdf

        reply = await handle_incoming_pdf(MediaUrl0)
    else:
        config = {"configurable": {"thread_id": from_number}}
        state_update = {
            "from_number": from_number,
            "incoming_message": message_text,
        }

        try:
            final_state = booking_graph.invoke(state_update, config=config)
            reply = final_state.get("reply_message", "")
            pipeline = final_state.get("pipeline_log", [])
            print(f"[Graph] Pipeline: {' -> '.join(n.split(':')[0] for n in pipeline)}")
            print(f"[Graph] Reply: {reply[:80]}...")
        except Exception as e:
            print(f"[ERROR] Booking graph failed: {e}")
            reply = (
                "Sorry, we're experiencing a technical issue. "
                "Please try again or call the clinic directly."
            )

    if reply:
        await send_whatsapp_message(to=From, body=reply)

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
        status_code=200,
    )


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
