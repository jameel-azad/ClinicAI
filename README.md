# ClinicAI

ClinicAI is a FastAPI + LangGraph backend for a WhatsApp-based clinic assistant. It can classify patient messages, manage appointment booking with doctor approval, check Google Calendar availability, parse lab report PDFs, and convert doctor voice notes into patient-ready clinical note PDFs.

## Features

- WhatsApp patient assistant through Twilio webhooks.
- Intent classification for appointment booking, cancellation, rescheduling, follow-up, lab reports, prescriptions, general queries, and emergencies.
- Appointment booking flow with doctor approval before final confirmation.
- Doctor-side WhatsApp commands for pending approvals, today's appointments, setup, and profile.
- Optional Google Calendar availability checks, slot suggestions, and event creation.
- Lab report PDF parsing with extracted patient info, test values, abnormal flags, critical flags, and doctor summary.
- Doctor voice note transcription into a grounded SOAP note PDF, then WhatsApp delivery to the patient.
- Reminder scheduling with APScheduler.

## Project Structure

```text
main.py                         FastAPI app entry point
app/api/                        API routers
app/graph/classifier.py         Intent classifier LangGraph
app/graph/booking.py            Appointment booking LangGraph
app/graph/parser/               Lab report parser pipeline
app/graph/scribe/               Doctor voice note to SOAP PDF pipeline
app/services/                   Twilio, calendar, storage, approval, PDF, scribe services
app/prompts/                    LLM prompts
app/schemas/                    Pydantic models and graph state types
scripts/google_calendar_auth.py Google Calendar OAuth helper
```

## Setup

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root.

```env
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
WHISPER_MODEL=whisper-large-v3-turbo

TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

DOCTOR_WHATSAPP_NUMBERS=Dr Mehta:+919999999999,Dr Sharma:+918888888888

PUBLIC_BASE_URL=https://your-public-ngrok-url.ngrok-free.app
CLINIC_NAME=ClinicAI
REMINDER_MINUTES_BEFORE=5
```

`PUBLIC_BASE_URL` is required when sending generated PDFs through WhatsApp because Twilio needs a public media URL.

## Run

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open Swagger docs:

```text
http://localhost:8000/docs
```

For Twilio WhatsApp, expose your local server through a public tunnel and configure Twilio's inbound webhook:

```text
POST https://your-public-url/webhook/twilio
```

## Main Endpoints

```text
GET  /                         Health and feature summary
GET  /docs                     Swagger UI
GET  /graph/nodes              Registered graph nodes
POST /classify                 Classify a patient message
POST /webhook/twilio           Twilio WhatsApp webhook
POST /parser/parse-report      Upload and parse a lab report PDF
GET  /parser/health            Parser health check
GET  /debug/sessions           Development session view
GET  /debug/appointments       Development appointment view
GET  /debug/identity           Configured doctor numbers
GET  /debug/pending-approvals  Pending doctor approvals
GET  /debug/doctors            Saved doctor profiles
```

Generated clinical note PDFs are served internally at:

```text
GET /scribe/pdf/{document_id}
```

This endpoint is hidden from Swagger and used as the public Twilio media URL.

## WhatsApp Flows

### Patient Appointment Booking

1. Patient messages the clinic.
2. Classifier extracts intent and entities.
3. Booking graph collects patient name, date, time, doctor, and symptoms.
4. Patient confirms the proposed slot.
5. System checks Google Calendar or local pending/confirmed appointments.
6. Doctor receives an approval request.
7. Doctor replies `YES APTxxxxx` or `NO APTxxxxx`.
8. On approval, appointment is saved, optional calendar event is created, reminder is scheduled, and patient is notified.

### Doctor Commands

Known doctor numbers are configured with `DOCTOR_WHATSAPP_NUMBERS`.

Supported commands:

```text
help
today
pending
inbox
setup doctor
profile
YES APTxxxxx
NO APTxxxxx
```

### Doctor Voice Note to Patient PDF

When a configured doctor sends a WhatsApp voice note:

1. Twilio sends the audio media URL to `/webhook/twilio`.
2. ClinicAI downloads the audio.
3. Groq Whisper transcribes it.
4. The scribe graph generates a SOAP note.
5. A grounding check flags unsupported clinical statements.
6. A PDF is generated and stored under `generated/scribe_pdfs`.
7. ClinicAI resolves the patient from the caption, transcript, or confirmed appointment.
8. The PDF is sent to the patient as WhatsApp media.

To help patient matching, the doctor can include a patient phone number or patient name in the voice note caption.

## Lab Report Parser

`POST /parser/parse-report` accepts a PDF and returns:

- patient demographics
- all extracted test values
- abnormal values
- critical values
- doctor-facing summary
- warnings

WhatsApp PDF uploads from patients are also handled by the Twilio webhook and summarized back in WhatsApp.

## Google Calendar Setup

Enable Calendar integration:

```env
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CALENDAR_CREDENTIALS_FILE=google_credentials.json
GOOGLE_CALENDAR_TOKEN_FILE=google_token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_TIMEZONE=Asia/Kolkata
APPOINTMENT_DURATION_MINUTES=30
APPOINTMENT_SLOT_INTERVAL_MINUTES=30
DEFAULT_APPOINTMENT_YEAR=2026
```

Download OAuth client credentials from Google Cloud Console as `google_credentials.json`, then run:

```powershell
python scripts/google_calendar_auth.py
```

This creates `google_token.json`, which is used for free/busy checks and event creation.

## Notes

- In-memory stores are used for sessions, appointments, approvals, doctor profiles, and generated PDF lookup. Use a real database or object storage for production.
- Twilio media sending requires `PUBLIC_BASE_URL` to point at a reachable public server.
- If Twilio credentials are missing, message sending falls back to mock console output for development.
- Generated PDFs are ignored by Git through `generated/`.
