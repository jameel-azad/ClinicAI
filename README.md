# ClinicAI

ClinicAI is a FastAPI + LangGraph backend for a WhatsApp-based clinic assistant. It handles patient appointment booking with doctor approval, lab report analysis, doctor voice note transcription into SOAP note PDFs, and WhatsApp interactive button support for doctor approvals — all through Twilio webhooks.

## Features

- WhatsApp patient assistant through Twilio webhooks.
- Personalised greeting for new patients (receptionist style) and doctors (feature overview), each triggered at the right moment.
- Intent classification for appointment booking, cancellation, rescheduling, follow-up, lab reports, prescriptions, general queries, and emergencies.
- Bilingual support — patients can reply in Hindi or English (Hinglish included).
- Appointment booking flow: patient → AI collects details → doctor approves via WhatsApp buttons → patient notified.
- **WhatsApp interactive buttons** for doctor approval of appointments and SOAP notes — no typing required.
- Doctor voice note → Whisper transcription → SOAP note → PDF sent to doctor for review → doctor approves → PDF delivered to patient.
- Lab report PDF from patient → safety check → AI extraction and summary → forwarded to the patient's doctor (requires prior booking).
- Doctor-side WhatsApp commands for pending approvals, today's appointments, setup, and profile.
- Optional Google Calendar availability checks, slot suggestions, and event creation.
- Appointment reminder scheduling with APScheduler, fired at the correct time before the appointment.
- `dev_start.py` one-command dev startup: launches ngrok, auto-writes `PUBLIC_BASE_URL` to `.env`, prints the Twilio webhook URL, then starts uvicorn.

## Project Structure

```text
main.py                          FastAPI app entry point
dev_start.py                     Dev startup: ngrok + uvicorn + .env auto-update
app/api/webhook_router.py        Twilio WhatsApp webhook and file-serving routes
app/graph/classifier.py          Intent classifier LangGraph
app/graph/booking.py             Appointment booking LangGraph state machine
app/graph/parser/                Lab report parser pipeline
app/graph/scribe/                Doctor voice note → SOAP PDF pipeline
app/services/appointment_approval.py  Appointment approval logic + button handler
app/services/soap_approval.py    SOAP note approval logic + button handler
app/services/clinical_scribe.py  Voice note download, pipeline orchestration, PDF storage
app/services/pdf_service.py      Lab report download, safety check, forwarding to doctor
app/services/doctor.py           Doctor message routing (buttons, SOAP, appointments, commands)
app/services/whatsapp.py         Twilio send helpers (text, media, template/buttons)
app/services/scheduler.py        APScheduler appointment reminders
app/services/store.py            In-memory stores: sessions, appointments, approvals, SOAPs
app/services/identity.py         Doctor number resolution and sender identification
app/prompts/                     LLM system prompts
app/schemas/                     Pydantic models and graph state types
scripts/google_calendar_auth.py  Google Calendar OAuth helper
```

## Setup

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
# LLM
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
WHISPER_MODEL=whisper-large-v3
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.5-flash

# Twilio
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# Doctors (Name:number pairs, comma-separated)
DOCTOR_WHATSAPP_NUMBERS=Dr Nabil:+919999999999,Dr Jameel:+918888888888

# Public URL (written automatically by dev_start.py when using ngrok)
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app

# Clinic
CLINIC_NAME=ClinicAI
REMINDER_MINUTES_BEFORE=5

# WhatsApp button templates (optional — falls back to text commands if not set)
APPOINTMENT_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SOAP_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Slot candidates for local calendar (comma-separated times)
APPOINTMENT_SLOT_CANDIDATES=10:30 AM,11:00 AM,5:00 PM,5:30 PM

# Storage directories
LAB_PDF_DIR=generated/lab_pdfs
SCRIBE_PDF_DIR=generated/scribe_pdfs
```

`PUBLIC_BASE_URL` is required for Twilio to fetch generated PDFs as WhatsApp media attachments.

## Development Startup

`dev_start.py` handles the full local dev setup in one command:

```powershell
python dev_start.py
```

What it does:
1. Starts an ngrok HTTPS tunnel on port 8000.
2. Polls the ngrok local API and reads the public URL.
3. Writes `PUBLIC_BASE_URL=<ngrok_url>` to `.env` automatically.
4. Prints the Twilio webhook URL to paste in the Twilio Console.
5. Starts uvicorn with `--reload`.
6. Shuts down ngrok cleanly on Ctrl+C.

Ngrok must be installed and authenticated first:

```powershell
ngrok config add-authtoken YOUR_TOKEN
```

Free token available at https://dashboard.ngrok.com.

After starting, paste the printed URL into the Twilio WhatsApp Sandbox settings:

```
https://<ngrok-id>.ngrok-free.app/webhook/twilio
```

> Every ngrok restart gives a new URL — update Twilio each time.

## Run (production / no ngrok)

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger docs: `http://localhost:8000/docs`

## Main Endpoints

```text
GET  /                              Health and feature summary
GET  /docs                          Swagger UI
GET  /graph/nodes                   Registered graph nodes
POST /classify                      Classify a patient message
POST /webhook/twilio                Twilio WhatsApp webhook
POST /parser/parse-report           Upload and parse a lab report PDF
GET  /parser/health                 Parser health check
GET  /debug/sessions                Active booking sessions
GET  /debug/appointments            Confirmed appointments
GET  /debug/identity                Configured doctor numbers
GET  /debug/pending-approvals       Pending doctor approvals
GET  /debug/doctors                 Saved doctor profiles
GET  /lab-report/pdf/{document_id}  Serve a stored lab report PDF
GET  /scribe/pdf/{document_id}      Serve a stored SOAP note PDF
```

The `/lab-report/pdf/` and `/scribe/pdf/` endpoints are hidden from Swagger and used as Twilio media URLs.

## WhatsApp Flows

### Patient — New Chat Greeting

When a patient sends their first message (no active booking session), they receive:

```
Namaste! Welcome to ClinicAI 🙏

I'm your virtual receptionist. Here's how I can help you:

📅 Book a doctor's appointment
📋 Share your lab report for the doctor to review

How may I assist you today?
(You can reply in Hindi or English)
```

### Patient — Appointment Booking

1. Patient messages the clinic (any first message starts the flow).
2. Classifier extracts intent and entities.
3. Booking graph collects patient name, date, time, preferred doctor, and symptoms.
4. Patient confirms the proposed slot.
5. System checks Google Calendar or local schedule for conflicts.
6. Doctor receives an approval request via WhatsApp (button message if `APPOINTMENT_APPROVAL_CONTENT_SID` is set, text otherwise).
7. Doctor taps **Approve** or **Reject** on the button, or replies `YES APTxxxxx` / `NO APTxxxxx`.
8. On approval: appointment saved, optional Google Calendar event created, reminder scheduled, patient notified.
9. On rejection: patient is asked for a different time.

### Patient — Lab Report Upload

1. Patient sends a PDF to the clinic WhatsApp number.
2. Bot checks the patient has a confirmed or pending appointment — if not, patient is asked to book first.
3. PDF is downloaded, safety-checked (LLM verifies it is a medical document).
4. Lab report parser extracts demographics, test values, abnormal/critical flags, and generates a doctor summary.
5. Text summary + original PDF are forwarded to the patient's doctor.
6. Patient receives a brief acknowledgment, with a critical-values warning if applicable.

### Doctor — New Chat Greeting

When a doctor sends `hi`, `hello`, `start`, or an empty message, they receive:

```
Hello Dr. Nabil! 👋

Welcome to ClinicAI. Here's what you can do:

🎙️ Voice note → Send an audio recording and I'll generate a SOAP note PDF for your patient
✅ Appointments → Approve or suggest an alternate time for pending patient bookings

How can I help you today?
```

### Doctor — Voice Note → SOAP Note PDF

1. Doctor sends a WhatsApp voice note (with optional caption: `Patient: +91XXXXXXXXXX`).
2. Audio is downloaded and transcribed by Groq Whisper.
3. Scribe pipeline generates a structured SOAP note and runs a grounding check.
4. A PDF is created and stored under `generated/scribe_pdfs/`.
5. Doctor receives the PDF with Approve/Reject buttons (or text prompt if no template configured).
6. Doctor taps **Approve** (or replies `APPROVE SOAPxxxxxx`) → PDF delivered to patient via WhatsApp.
7. Doctor taps **Reject** (or replies `REJECT SOAPxxxxxx`) → note discarded.

If the patient cannot be identified automatically, the doctor is prompted to include the patient's WhatsApp number:

```
APPROVE SOAPxxxxxx +91XXXXXXXXXX
```

### Doctor — Text Commands

```text
hi / hello / start    Welcome greeting with feature overview
help                  Commands list
today                 Today's confirmed appointments
pending / inbox       Pending appointment approval requests
setup doctor          Doctor profile setup flow
profile               View saved doctor profile
YES APTxxxxx          Approve appointment (text fallback)
NO APTxxxxx           Reject appointment (text fallback)
APPROVE SOAPxxxxx     Approve SOAP note (text fallback)
REJECT SOAPxxxxx      Reject SOAP note (text fallback)
```

## WhatsApp Button Templates

Two Twilio Content Templates are needed for the button feature. Create them in the [Twilio Content Template Builder](https://console.twilio.com).

### Appointment Approval Template

| Field | Value |
|---|---|
| Name | `appointment_approval` |
| Type | Quick Reply |
| Body | `Appointment request {{1}}`<br>`(newline)`<br>`Patient: {{2}}`<br>`Doctor: {{3}}`<br>`Date: {{4}}`<br>`Time: {{5}}`<br>`Reason: {{6}}` |
| Button 1 | Title: `Approve` · ID: `apt_approve` |
| Button 2 | Title: `Reject` · ID: `apt_reject` |

Add to `.env`:
```env
APPOINTMENT_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### SOAP Note Approval Template

| Field | Value |
|---|---|
| Name | `soap_approval` |
| Type | Quick Reply |
| Body | `📋 SOAP note ready for {{1}}.`<br>`(newline)`<br>`Patient: {{2}}`<br>`(newline)`<br>`Review the attached PDF and use the buttons below.` |
| Button 1 | Title: `Approve` · ID: `soap_approve` |
| Button 2 | Title: `Reject` · ID: `soap_reject` |

Add to `.env`:
```env
SOAP_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> Use actual line breaks (Enter key) in the body field — do not type `\n` literally.
>
> Both content SIDs are optional. If not set, the bot falls back to text-based approval commands automatically.

## Google Calendar Setup

```env
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_CREDENTIALS_FILE=google_credentials.json
GOOGLE_CALENDAR_TOKEN_FILE=google_token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_TIMEZONE=Asia/Kolkata
APPOINTMENT_DURATION_MINUTES=30
APPOINTMENT_SLOT_INTERVAL_MINUTES=30
```

Download OAuth client credentials from Google Cloud Console as `google_credentials.json`, then run:

```powershell
python scripts/google_calendar_auth.py
```

This creates `google_token.json` used for free/busy checks and event creation. If Calendar is disabled or the check fails, the system falls back to the local in-memory schedule.

## Notes

- All stores (sessions, appointments, approvals, SOAP pending list) are in-memory and reset on server restart. Use a real database for production.
- If Twilio credentials are missing, all message sending falls back to mock console output for development.
- `PUBLIC_BASE_URL` must be a reachable public URL — local `localhost` will not work with Twilio media.
- If a doctor has multiple pending appointment approvals, button taps ask them to specify the request ID via text. Single pending approvals are handled by buttons directly.
- Generated PDFs are excluded from Git via `generated/` in `.gitignore`.
