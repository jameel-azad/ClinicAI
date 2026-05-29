# ClinicAI — Sprint 2 (Complete)

ClinicAI is a WhatsApp-native clinic assistant built on FastAPI + LangGraph. It covers the full patient lifecycle — appointment booking, real-time consultation orchestration, clinical SOAP note generation, lab report parsing, and post-visit follow-up — entirely over WhatsApp using Twilio.

**Sprint 2** refactors the single booking pipeline into a full multi-agent system: `RouterAgent → {BookingAgent, ConsultationAgent, EmergencyAgent, AfterHoursAgent, LabAgent, FollowUpAgent}` with a Jameel-side clinical scribe pipeline that converts consultation bundles into SOAP note PDFs, a structured clinical entity extractor, confidence-aware doctor alerts, and a weekly practice insights report.

---

## Features

- **Multi-agent routing** — RouterAgent classifies intent, checks clinic hours, and dispatches to the correct specialist agent per message.
- **10-intent classifier** — Groq LLaMA 3.3 70B with Gemini 2.5 Flash fallback; bilingual Hindi/English (Hinglish); context-aware using previous bot response.
- **Appointment booking** — Multi-turn state machine; doctor approval via WhatsApp interactive buttons or text; Google Calendar integration (optional).
- **ConsultationAgent** — Buffers all patient text + doctor voice notes into a `ConsultationSession`; ends on closing phrase or inactivity timeout; triggers full SOAP pipeline.
- **Clinical scribe pipeline** — Consultation bundle → Whisper transcription → LLaMA SOAP generation → clinical entity extraction → grounding check → follow-up questions → ReportLab PDF → delivered to doctor via WhatsApp.
- **Clinical entity extractor** — After every SOAP generation, extracts all symptoms (name, severity, duration), medications (name, dose, frequency), and diagnoses from the transcript + SOAP note as structured JSON (`clinical_entities`).
- **SOAP confidence hardening** — Overall SOAP confidence is computed after every voice note or consultation. If confidence < 0.6, the doctor receives a named section warning (`⚠️ I am not confident about [Assessment]`) alongside the PDF, both in the standalone voice note flow and in the consultation summary.
- **Single voice note scribe** — Doctor sends standalone voice note → Whisper → SOAP PDF → confidence check → doctor approves → sent to patient.
- **Lab report parsing** — Patient sends PDF → pdfplumber extraction + OCR fallback → critical value flagging (CBC, LFT, KFT, Lipid, Thyroid thresholds) → Groq summary → forwarded to doctor.
- **After-hours agent** — Messages outside clinic hours queued to Redis, re-injected at opening time.
- **Emergency agent** — Instant 112 response to patient + alert to all configured doctors.
- **Weekly practice insights** — Every Monday at 8 AM IST, each doctor receives a 7-day summary: total appointments, past vs. upcoming, estimated no-show rate, busiest day, busiest time slot, and top 3 patient complaints.
- **APScheduler jobs** — Appointment reminder, no-show recovery (×2), consultation inactivity timeout, daily after-hours flush, weekly insights (Monday 8 AM).
- **Redis persistence** — All sessions, appointments, consultations, approvals stored in Redis with TTLs; in-memory fallback for dev.
- **`dev_start.py`** — One-command dev startup: ngrok + auto-writes `PUBLIC_BASE_URL` to `.env` + uvicorn.

---

## Project Structure

```
main.py                                   FastAPI entry point, lifespan, router registration
dev_start.py                              Dev startup: ngrok + uvicorn + .env auto-update

app/
├── api/
│   ├── webhook_router.py                 Twilio webhook, doctor/patient routing, debug endpoints
│   ├── classifier_router.py              POST /classify — direct HTTP classifier test
│   ├── parser_router.py                  POST /parse-lab-report
│   └── scribe_router.py                  POST /scribe/consult — Jameel scribe API endpoint
│
├── graph/
│   ├── classifier.py                     Intent classification pipeline (6-node LangGraph)
│   ├── router.py                         RouterAgent — top-level orchestrator (8-node LangGraph)
│   ├── booking.py                        Backward-compat shim → router_graph
│   ├── agents/
│   │   ├── booking_agent.py              Multi-turn booking state machine
│   │   ├── consultation_agent.py         Consultation session lifecycle (Sprint 2 core)
│   │   ├── emergency_agent.py            Emergency response + doctor alert
│   │   ├── after_hours_agent.py          Queue + ack for out-of-hours messages
│   │   ├── followup_agent.py             Post-consultation follow-up handling
│   │   └── lab_agent.py                  Lab report intent (no PDF attached)
│   ├── scribe/
│   │   ├── pipeline.py                   Scribe LangGraph: transcribe → soap → extract_entities → grounding → follow-up → pdf
│   │   ├── nodes.py                      Whisper, SOAP generator, entity extractor, confidence helpers, grounding check, follow-up, PDF
│   │   ├── state.py                      ScribeState TypedDict (includes clinical_entities, follow_up_days)
│   │   └── pdf_builder.py               ReportLab SOAP PDF builder
│   └── parser/                           Lab report extraction pipeline
│
├── services/
│   ├── store.py                          Redis + in-memory dual persistence layer
│   ├── scheduler.py                      APScheduler jobs (reminder, no-show, timeout, flush, weekly insights)
│   ├── consultation_service.py           Consultation bundle builder + Jameel API caller
│   ├── scribe_service.py                 Jameel-side: bundle → transcribe → SOAP → PDF
│   ├── clinical_scribe.py               Single voice note download + scribe orchestration
│   ├── appointment_approval.py           Approval workflow + button handler
│   ├── soap_approval.py                  SOAP approval workflow + button handler
│   ├── pdf_service.py                    Lab report download + forwarding
│   ├── doctor.py                         Doctor message command router
│   ├── doctor_setup.py                   Doctor onboarding (5-step WhatsApp flow)
│   ├── whatsapp.py                       Twilio send helpers (text, media, template/buttons)
│   ├── identity.py                       Sender identification (doctor vs patient)
│   └── google_calendar.py               Google Calendar availability + event creation
│
├── prompts/                              LLM system prompts (classifier, SOAP, booking entities)
└── schemas/                              Pydantic models, TypedDicts, intent/state constants
```

---

## Setup

### 1. Install dependencies

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start Redis

```powershell
docker run -d -p 6379:6379 redis
```

Or use a local Redis service. The app falls back to in-memory stores if Redis is unavailable (state lost on restart).

### 3. Create `.env`

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

# Doctors — comma-separated "Name:+91number" pairs
DOCTOR_WHATSAPP_NUMBERS=Dr Jameel:+919801581020

# Clinic
CLINIC_NAME=ClinicAI
CLINIC_OPEN_HOUR=9
CLINIC_CLOSE_HOUR=20

# Timing — use demo values below for testing, revert to production values before go-live
REMINDER_MINUTES_BEFORE=2          # Demo: 2 min | Production: 120
CONSULTATION_TIMEOUT_MINUTES=2     # Demo: 2 min | Production: 30
WEEKLY_INSIGHTS_HOUR=8             # Hour (IST, 24h) to send Monday practice insights to doctors

# Jameel scribe API — leave empty to run locally, set URL when deployed separately
JAMEEL_SCRIBE_URL=

# Redis
REDIS_URL=redis://localhost:6379

# Public URL — written automatically by dev_start.py, or set manually
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app

# WhatsApp button templates (optional — text fallback used if not set)
APPOINTMENT_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SOAP_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Google Calendar (optional)
GOOGLE_CALENDAR_ENABLED=False
GOOGLE_CALENDAR_CREDENTIALS_FILE=google_credentials.json
GOOGLE_CALENDAR_TOKEN_FILE=google_token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_TIMEZONE=Asia/Kolkata
APPOINTMENT_DURATION_MINUTES=30
```

### 4. Start the server

```powershell
python dev_start.py
```

This starts ngrok, writes `PUBLIC_BASE_URL` to `.env` automatically, prints the Twilio webhook URL, then starts uvicorn with `--reload`.

Paste the printed URL into the [Twilio WhatsApp Sandbox](https://console.twilio.com) webhook field:

```
https://<ngrok-id>.ngrok-free.app/webhook/twilio
```

> Every ngrok restart gives a new URL — update Twilio each time, or use a paid ngrok static domain.

---

## API Endpoints

```
GET  /                              Health check + feature flags
GET  /docs                          Swagger UI
GET  /graph/nodes                   Registered graph nodes (debug)
POST /classify                      Classify a message directly (no WhatsApp needed)
POST /webhook/twilio                Twilio WhatsApp webhook (all messages flow here)
POST /scribe/consult                Jameel scribe API — consultation bundle → SOAP result
GET  /debug/sessions                All active BookingSession objects
GET  /debug/appointments            All confirmed AppointmentRecord objects
GET  /debug/identity                Configured doctor phone numbers
GET  /debug/pending-approvals       Pending doctor appointment approvals
GET  /debug/doctors                 Saved doctor profiles
GET  /debug/consultations           All active/recent ConsultationSession objects
GET  /scribe/pdf/{id}               Serve a SOAP note PDF
GET  /lab-report/pdf/{id}           Serve a lab report PDF
```

---

## Testing the Pipeline

The steps below walk through every feature end-to-end. Use two real phones: one as the **patient** (any WhatsApp number joined to the Twilio sandbox), one as the **doctor** (the number in `DOCTOR_WHATSAPP_NUMBERS`).

### Prerequisites

Before starting any test:

1. Server is running (`python dev_start.py` or `uvicorn main:app --reload`)
2. ngrok tunnel is live and Twilio webhook is updated
3. Redis is running (`docker ps` or check `GET /` → `"scheduler": true`)
4. Patient phone has joined the Twilio sandbox: send `join <your-sandbox-keyword>` to `+14155238886`
5. Confirm server is healthy: `GET http://localhost:8000/` should return `"status": "ok"`

---

### Test 1 — Intent Classifier (no WhatsApp needed)

Verify the classifier works before testing the full flow.

```powershell
curl -X POST http://localhost:8000/classify `
  -H "Content-Type: application/json" `
  -d '{"from_number": "+919876543210", "message": "I want to book an appointment with Dr Jameel tomorrow at 10am"}'
```

**Expected:** `intent: "appointment_book"`, `confidence > 0.85`, `entities.doctor_name: "Dr Jameel"`, `entities.requested_date: "tomorrow"`, `entities.requested_time: "10am"`

Test emergency:
```powershell
curl -X POST http://localhost:8000/classify `
  -H "Content-Type: application/json" `
  -d '{"from_number": "+919876543210", "message": "mujhe bahut takleef hai emergency hai"}'
```

**Expected:** `intent: "emergency"`, `confidence > 0.9`

---

### Test 2 — Appointment Booking (full multi-turn flow)

**From the patient phone:**

1. Send: `hi` → expect welcome greeting
2. Send: `I want to book an appointment with Dr Jameel` → bot asks for name
3. Send your name (e.g. `Rahul Sharma`) → bot asks for date
4. Send: `tomorrow` → bot asks for time
5. Send: `10am` → bot asks for symptoms
6. Send: `I have a fever and headache` → bot shows confirmation slot
7. Send: `yes confirm` → bot says "Waiting for doctor approval"

**Verify session state:**
```
GET http://localhost:8000/debug/sessions
```
Look for your patient number. `state` should be `WAITING_DOCTOR_APPROVAL`.

**From the doctor phone:**

8. You receive a WhatsApp message with appointment details + Approve/Reject buttons (or text `YES APTxxxxx`)
9. Tap **Approve** (or reply `YES APT<id>`)

**Expected on patient phone:** "Your appointment has been confirmed with Dr Jameel on tomorrow at 10:00 AM."

**Verify appointment saved:**
```
GET http://localhost:8000/debug/appointments
```

---

### Test 3 — Appointment Reminder

With `REMINDER_MINUTES_BEFORE=2`, the reminder fires 2 minutes before the appointment time.

1. Book an appointment for a time that is 3–5 minutes from now (e.g. if it's 14:00, book for 14:05).
2. Doctor approves.
3. Wait approximately `appointment_time - 2 minutes`.

**Expected on patient phone:** "⏰ Reminder — ClinicAI. Your appointment with Dr Jameel is in 2 minutes!"

> If the appointment time is less than 2 minutes away when approved, the reminder fires in 30 seconds.

---

### Test 4 — Appointment Cancellation and Rescheduling

**Cancel:**

From the patient phone: `I want to cancel my appointment`

**Expected:** Bot confirms cancellation and asks if you need a new slot.

**Reschedule:**

From the patient phone: `reschedule my appointment to day after tomorrow at 3pm`

**Expected:** Bot collects new slot → sends to doctor for approval again.

---

### Test 5 — Emergency Flow

From the patient phone:

Send: `emergency mujhe bahut takleef ho rahi hai` (or any emergency message)

**Expected on patient phone:** Immediate response with emergency instructions and "Call 112".

**Expected on doctor phone:** WhatsApp alert — "🚨 EMERGENCY ALERT — Patient +91... sent an emergency message. Please respond immediately or call 112."

---

### Test 6 — After-Hours Message

1. Temporarily change `.env`: `CLINIC_CLOSE_HOUR=0` (makes the clinic always closed) and restart the server.
2. From the patient phone: send any message.

**Expected:** "ClinicAI is closed right now (9 AM – 8 PM IST). Your message has been received and we'll respond first thing when we open."

**Verify message was queued:**
```
GET http://localhost:8000/debug/sessions
```
(The message is in Redis under `clinicai:afterhours:{doctor_number}`)

3. Restore `CLINIC_CLOSE_HOUR=20` and restart. The after-hours flush job will re-process the queued message at the next `CLINIC_OPEN_HOUR:00`.

---

### Test 7 — Lab Report Upload

1. First complete a booking (Test 2) so the patient has a confirmed appointment.
2. From the patient phone: send a PDF lab report as a WhatsApp attachment.

**Expected on patient phone:** "Lab report received. I've forwarded it to your doctor for review."

**Expected on doctor phone:** Lab report summary + original PDF forwarded.

**Verify:**
```
GET http://localhost:8000/debug/pending-approvals
```

---

### Test 8 — Doctor Voice Note → Single SOAP Note (outside consultation)

This tests the standalone scribe pipeline (not inside a consultation).

1. From the **doctor phone**: send a WhatsApp voice note (no active consultation for any patient).
2. Speak a sample clinical note, e.g.: *"Patient is Suresh, 45 years old. BP is 140 over 90. Starting Amlodipine 5mg once daily. Follow-up in two weeks."*

**Expected on doctor phone:**
- PDF attachment with the SOAP note for review
- Approve / Reject buttons (or text `APPROVE RXxxxxxx` / `REJECT RXxxxxxx`)

3. Tap **Approve**.

**Expected on patient phone:** PDF delivered (if patient number was identifiable from caption or recent appointment).

> To specify the patient explicitly, send the voice note with caption: `Patient: +91XXXXXXXXXX`

**Confidence hardening check:**

If the SOAP note has overall confidence < 0.6 across non-missing sections, the doctor's message includes a warning alongside the PDF:

```
⚠️ Low confidence warning: I am not confident about the [Objective] section(s). Please review carefully before sending.
```

To trigger this: speak a deliberately vague voice note (no objective clinical measurements) and the Objective section confidence should drop below 0.6.

---

### Test 9 — Consultation Lifecycle (Sprint 2 core feature)

This is the main Sprint 2 flow. Set `CONSULTATION_TIMEOUT_MINUTES=2` in `.env` for testing.

#### 9a — Start consultation

**From the patient phone:**

Send: `doctor mujhe sir dard ho raha hai aur bukhar bhi hai`

**Expected on patient phone:** "Message received — consultation in progress. 🩺 The doctor will respond shortly."

**Verify consultation session created:**
```
GET http://localhost:8000/debug/consultations
```
Look for your patient number. You should see:
- `is_active: true`
- `messages: [{sender_role: "patient", text: "doctor mujhe..."}]`
- `journey_state` on the booking session should be `CONSULTATION_ACTIVE` (check `/debug/sessions`)

#### 9b — Doctor sends voice note during consultation

**From the doctor phone:** Send a WhatsApp voice note.

Speak something like: *"Patient has headache and fever since two days. Temperature 101 degrees. Prescribing Paracetamol 500mg three times daily for three days. Review if fever persists."*

**Expected on doctor phone:** "🎙️ Voice note received and added to the active consultation buffer. Send *ok done* or *take care* when the consultation is complete."

**Verify audio was buffered** (not processed as standalone SOAP):
```
GET http://localhost:8000/debug/consultations
```
Check `audio_files` array — it should now contain the audio URL.

**Patient can also send more messages:**

From the patient phone: `kal se chal raha hai aur neend nahi aayi`

Check `/debug/consultations` → `messages` array now has 2 patient messages + 1 doctor audio.

#### 9c — End consultation via closing phrase

**From the patient phone:** Send `ok done` (or `take care`, `bas`, `done`, `bye`)

**Expected on patient phone:** "Your consultation has been recorded. The doctor will send any prescriptions or follow-up instructions shortly. 🙏"

**Expected on doctor phone (within ~60 seconds):**
- WhatsApp message with consultation summary:
  ```
  📋 ClinicAI — Consultation Summary
  Patient: +91...
  Messages: 3 | Audio files: 1
  Ended: closing_phrase

  Dx: Fever and headache
  Rx: Paracetamol 500mg TDS...

  Follow-up questions to ask patient:
    1. How are you feeling today? Has the fever reduced?
    2. Have you been taking the medication as prescribed?
  ```
- PDF link: `GET /scribe/pdf/{id}` — opens the full SOAP note PDF

**Verify consultation was cleaned up:**
```
GET http://localhost:8000/debug/consultations
```
Should be empty or the session's `is_active` should be `false`.

**Verify journey state updated:**
```
GET http://localhost:8000/debug/sessions
```
Patient's `journey_state` should now be `POST_CONSULT`.

#### 9d — End consultation via inactivity timeout

Repeat steps 9a–9b but do NOT send a closing phrase. Wait `CONSULTATION_TIMEOUT_MINUTES` (2 minutes in demo).

**Expected:** After 2 minutes of silence, the server automatically calls `finalize_and_send()` and the doctor receives the summary — same as the closing phrase path.

Server logs will show:
```
[Consultation] Timeout fired for +91... — finalising
[ConsultationService] Summary sent to doctor +919801581020
[ConsultationService] ConsultationSession deleted for +91...
```

---

### Test 10 — Scribe API Directly (Jameel-side endpoint)

Test `POST /scribe/consult` directly without going through the WhatsApp flow.

```powershell
curl -X POST http://localhost:8000/scribe/consult `
  -H "Content-Type: application/json" `
  -d '{
    "patient_id": "+919876543210",
    "doctor_id": "+919801581020",
    "messages": [
      {"sender_role": "patient", "text": "doctor mujhe sir dard ho raha hai", "audio_url": null, "timestamp": "2026-05-27T10:00:00"},
      {"sender_role": "doctor",  "text": "Patient has mild headache since morning. Prescribing Paracetamol 500mg OD.", "audio_url": null, "timestamp": "2026-05-27T10:02:00"}
    ],
    "audio_files": []
  }'
```

**Expected response:**
```json
{
  "soap_note_pdf_url": "https://...ngrok.../scribe/pdf/...",
  "follow_up_questions": ["How are you feeling today?", "..."],
  "missing_sections": [],
  "summary_for_whatsapp": "Dx: Mild headache | Rx: Paracetamol 500mg OD",
  "clinical_entities": {
    "symptoms": [{"name": "headache", "severity": "mild", "duration": "morning"}],
    "medications": [{"name": "Paracetamol", "dose": "500mg", "frequency": "OD"}],
    "diagnoses": ["Mild cephalgia"]
  },
  "overall_confidence": 0.82,
  "low_confidence_sections": []
}
```

Open the `soap_note_pdf_url` in a browser to verify the PDF was generated correctly.

---

### Test 11 — Follow-Up Query (post-consultation)

After completing Test 9, the patient's `journey_state` is `POST_CONSULT`.

From the patient phone: `doctor ne jo follow up questions pooche the, kya hain woh?`

**Expected:** Bot responds with context-appropriate follow-up messaging (acknowledges POST_CONSULT state).

---

### Test 12 — No-Show Recovery

1. Book an appointment for a time 2 minutes from now.
2. Doctor approves.
3. Do NOT send any message from the patient phone after the appointment time.
4. Wait `appointment_time + 1 hour` (or set a past appointment time in the booking for faster testing).

**Expected on patient phone (at +1hr):** "👋 Hi! We noticed you may have missed your appointment today. Reply *reschedule* to book a new slot."

**Expected at +24hr:** Second follow-up message with reschedule prompt.

> The no-show check is skipped if `last_active` timestamp is newer than the appointment time — i.e. if the patient sent any message after the appointment.

---

### Test 14 — Weekly Practice Insights

The weekly insights job fires every Monday at `WEEKLY_INSIGHTS_HOUR` IST. To verify without waiting until Monday, temporarily trigger it via the scheduler or call `_weekly_insights_job(doctor_number)` directly in a Python shell.

First book and confirm 2–3 appointments to populate data:

1. Complete Test 2 twice (two bookings for different time slots).
2. Open a Python shell in the project root:

```powershell
python -c "
import os; os.chdir(r'D:\ClinicAI')
from app.services.scheduler import _weekly_insights_job
_weekly_insights_job('+919801581020')
"
```

**Expected on doctor phone:**

```
📊 ClinicAI — Weekly Practice Report
Week of 22 May 2026

Total appointments: 2
  ✅ Past: 1 | ⏳ Upcoming: 1
  ❌ Estimated no-shows: 0

📅 Busiest day: Thursday (1 appointments)
⏰ Busiest time: Morning (10:00 AM – 12:00 PM)

🩺 Top patient complaints:
  • fever: 1 patient(s)
  • headache: 1 patient(s)

Stay healthy! See you next week. 🌟
```

> `WEEKLY_INSIGHTS_HOUR` defaults to `8` (8 AM IST). Change in `.env` to adjust delivery time.

---

### Test 13 — Doctor Onboarding

From the **doctor phone**: send `setup doctor`

Follow the 5-step flow:
1. Name
2. Google email (for calendar — enter any value if calendar is disabled)
3. Working hours (e.g. `9am to 8pm`)
4. Appointment duration (e.g. `30`)
5. Buffer time (e.g. `5`)

**Verify profile saved:**
```
GET http://localhost:8000/debug/doctors
```

---

### Quick Debug Checklist

At any point during testing, use these endpoints to inspect current state:

| Endpoint | What to check |
|---|---|
| `GET /` | All feature flags are `true` (classifier, whatsapp_webhook, booking_graph, scheduler) |
| `GET /debug/sessions` | Patient's `state` and `journey_state` |
| `GET /debug/appointments` | Confirmed appointment records |
| `GET /debug/pending-approvals` | Approvals with `status: "waiting_doctor"` |
| `GET /debug/consultations` | Active session, message buffer, audio_files |
| `GET /debug/doctors` | Doctor profile after onboarding |
| `GET /graph/nodes` | Verify all graph nodes are registered |

**Server logs** (uvicorn console) show the full pipeline trace for every message:

```
[Webhook] From: +919876543210 | Role: patient | Message: hi
[Graph] Pipeline: router/intent_node -> router/session_node -> booking_dispatch_node
[Graph] Reply: Namaste! Welcome to ClinicAI...
```

---

## WhatsApp Flows Reference

### Patient

| Message | Intent | Agent dispatched |
|---|---|---|
| `hi / hello / book appointment` | `appointment_book` | BookingAgent |
| `cancel my appointment` | `appointment_cancel` | BookingAgent |
| `reschedule to tomorrow 3pm` | `appointment_reschedule` | BookingAgent |
| `what is the status of my booking` | `appointment_status` | BookingAgent |
| `doctor mujhe bukhar hai` (during consult) | `consultation_message` | ConsultationAgent |
| `ok done / take care / bas` (during consult) | `consultation_message` | ConsultationAgent → finalize |
| Send PDF | lab report | `pdf_service` (bypasses router) |
| `emergency mujhe takleef hai` | `emergency` | EmergencyAgent |
| Any message outside 9am–8pm IST | — | AfterHoursAgent |
| `doctor ne kya bola tha` (after consult) | `followup_query` | FollowUpAgent |

### Doctor

| Message / Action | What happens |
|---|---|
| Tap **Approve** button | `appointment_approval.handle_appointment_button_reply()` |
| Tap **Reject** button | Appointment rejected, patient asked for new slot |
| `YES APTxxxxx` | Text-based appointment approval |
| `NO APTxxxxx` | Text-based appointment rejection |
| Send voice note (no active consultation) | Standalone scribe pipeline → SOAP PDF → approval buttons |
| Send voice note (during active consultation) | Audio buffered into ConsultationSession |
| Tap **Approve** (SOAP) | `soap_approval` → PDF sent to patient |
| `APPROVE RXxxxxxx` | Text-based SOAP approval |
| `REJECT RXxxxxxx` | SOAP discarded |
| `OK LABxxxxxx` | Lab review acknowledged |
| `today` | Today's confirmed appointments |
| `pending` / `inbox` | Pending approval requests |
| `setup doctor` | 5-step onboarding flow |
| `hi` / `hello` | Doctor welcome greeting |

---

## WhatsApp Button Templates

Two Twilio Content Templates are required for interactive approval buttons. Create them at [console.twilio.com/content-template-builder](https://console.twilio.com).

### Appointment Approval

| Field | Value |
|---|---|
| Type | Quick Reply |
| Body | `Appointment request from {{1}}\nPatient: {{2}}\nDate: {{3}}\nTime: {{4}}\nReason: {{5}}` |
| Button 1 | Label: `Approve` · ID: `apt_approve` |
| Button 2 | Label: `Reject` · ID: `apt_reject` |

```env
APPOINTMENT_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### SOAP Note Approval

| Field | Value |
|---|---|
| Type | Quick Reply |
| Body | `📋 SOAP note ready for {{1}}.\nPatient: {{2}}\nReview the PDF and approve or reject.` |
| Button 1 | Label: `Approve` · ID: `soap_approve` |
| Button 2 | Label: `Reject` · ID: `soap_reject` |

```env
SOAP_APPROVAL_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> Both are optional — text fallback commands work automatically if not configured.

---

## Production Notes

- **Revert demo timing values** before go-live: `REMINDER_MINUTES_BEFORE=120`, `CONSULTATION_TIMEOUT_MINUTES=30`, `WEEKLY_INSIGHTS_HOUR=8` (8 AM IST is production-ready; adjust to doctor's preference)
- **LangGraph MemorySaver** is in-process only — a server restart loses thread checkpoints. Replace with `RedisSaver` for production.
- **Debug endpoints** (`/debug/*`) are unauthenticated — remove or gate behind auth before exposing publicly.
- **`.env` must not be committed** — it contains live API keys.
- **`PUBLIC_BASE_URL`** must be a stable reachable URL in production — not ngrok.
- **Twilio webhook signature validation** is not implemented — add `RequestValidator` before production deployment.
