# ClinicAI

ClinicAI is a WhatsApp-native clinic management system built on FastAPI and LangGraph, with a Next.js management dashboard. Patients interact with the clinic entirely over WhatsApp — booking appointments, conducting consultations via voice and text, uploading lab reports, and receiving follow-ups. Doctors manage their practice through both WhatsApp (approvals, voice-note scribing, weekly insights) and the web dashboard (patient records, AI model configuration, full medical history timelines). Every consultation is automatically converted into a structured SOAP note, coded with SNOMED CT diagnoses and RxNorm medications, stored as a persistent medical record, and packaged as an HL7 FHIR R4 Bundle — all without any manual input.

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │            WhatsApp / Twilio         │
                        │   Patient ↔ WhatsApp ↔ Twilio        │
                        │   Doctor  ↔ WhatsApp ↔ Twilio        │
                        └──────────────┬──────────────────────┘
                                       │  POST /webhook/twilio
                                       ▼
                        ┌─────────────────────────────────────┐
                        │         FastAPI Backend              │
                        │                                      │
                        │  LangGraph Multi-Agent System        │
                        │  ┌────────────┐  ┌───────────────┐  │
                        │  │ RouterAgent│  │ ScribePipeline│  │
                        │  │ Classifier │  │ (Whisper→SOAP)│  │
                        │  └────┬───────┘  └───────────────┘  │
                        │       │                              │
                        │  ┌────▼──────────────────────────┐  │
                        │  │ Booking | Consult | Lab |      │  │
                        │  │ Emergency | AfterHours | Followup│ │
                        │  └───────────────────────────────┘  │
                        │                                      │
                        │  APScheduler (reminders, insights)   │
                        └──────┬──────────────┬───────────────┘
                               │              │
                    ┌──────────▼──┐    ┌──────▼────────┐
                    │  PostgreSQL  │    │     Redis      │
                    │  (persistent │    │  (sessions,    │
                    │   records)   │    │   TTL state)   │
                    └─────────────┘    └───────────────┘

                        ┌─────────────────────────────────────┐
                        │       Next.js Dashboard              │
                        │  Doctor → Browser → FastAPI REST     │
                        │  Auth | Patients | Appointments | Config│
                        └─────────────────────────────────────┘

LLM:  Groq LLaMA 3.3 70B (primary)  +  Gemini 2.5 Flash (fallback)
STT:  Groq Whisper large-v3
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| API Framework | FastAPI 0.115 | REST API, webhook handler, async request handling |
| Agent Orchestration | LangGraph 0.3 | Multi-agent graph (Router, Booking, Consult, Lab, Emergency, etc.) |
| Primary LLM | Groq LLaMA 3.3 70B | Intent classification, SOAP generation, clinical entities |
| Fallback LLM | Gemini 2.5 Flash | Classifier fallback when Groq is unavailable |
| Speech-to-Text | Groq Whisper large-v3 | Doctor voice note transcription |
| Messaging | Twilio WhatsApp API | Inbound/outbound WhatsApp messages, voice notes, PDFs, buttons |
| Session Store | Redis 7 | Active sessions, consultations, appointments, TTL management |
| Database | PostgreSQL 16 + SQLAlchemy asyncpg | Persistent clinics, patients, medical records, doctors |
| Migrations | Alembic | Schema version control |
| Task Scheduler | APScheduler 3.10 | Reminders, no-show recovery, after-hours flush, weekly insights |
| PDF Generation | ReportLab | SOAP note PDFs |
| PDF Parsing | pdfplumber + pytesseract | Lab report extraction with OCR fallback |
| Clinical Standards | SNOMED CT + RxNorm | Diagnosis and medication coding |
| Interoperability | HL7 FHIR R4 | Structured clinical data bundles |
| Auth | python-jose (JWT HS256) + passlib bcrypt | Dashboard authentication |
| Key Encryption | cryptography (Fernet) | Per-clinic API key encryption at rest |
| Dashboard | Next.js + Tailwind + shadcn/ui | Web management interface |
| Containerization | Docker Compose | Local and production deployment |
| Scheduling | Google Calendar API (optional) | Appointment event creation |

---

## Features

### Patient-Facing (WhatsApp)

- **Appointment booking** — Multi-turn conversational booking in English and Hinglish. Collects name, preferred date, time, symptoms, and routes to doctor approval. A patient can hold multiple active appointments with different doctors simultaneously.
- **Multiple appointment support** — Booking a second appointment (different doctor or specialty) while one is already confirmed is fully supported. The system prevents duplicate bookings (same patient + same doctor + same date/time) and guides the patient to choose a slot with suggestions if the requested one is taken.
- **Appointment management** — Cancel, reschedule, or check status over WhatsApp. When a patient has multiple active appointments, the bot presents a numbered selection list so they can target the correct one.
- **Consultation flow** — Send text messages and voice notes during an open consultation session. The doctor responds via WhatsApp; all messages are buffered and converted to a SOAP note on close.
- **Lab report upload** — Send a PDF lab report as a WhatsApp attachment. The system extracts results, flags critical values (CBC, LFT, KFT, Lipid, Thyroid), summarises them with Groq, and forwards to the doctor.
- **After-hours queue** — Messages sent outside clinic hours are queued in Redis and re-injected automatically at opening time.
- **Emergency response** — Detects emergency intent and immediately replies with 112 instructions while alerting all configured doctors.
- **Post-consultation follow-up** — Handles follow-up queries after consultation closes.

### Doctor-Facing (WhatsApp)

- **Appointment approval** — Receive appointment requests with interactive Approve/Reject buttons (Twilio Content Templates) or text commands (`YES APTxxxxx` / `NO APTxxxxx`).
- **Standalone voice-note scribe** — Send any voice note outside a consultation; the system transcribes with Whisper, generates a SOAP note PDF, runs confidence scoring, and sends it back for approval before forwarding to the patient.
- **Consultation voice buffering** — Voice notes sent during an active patient consultation are buffered into the session rather than processed as standalone SOAP notes.
- **SOAP approval** — Approve or reject generated SOAP PDFs via buttons or text (`APPROVE RXxxxxx` / `REJECT RXxxxxx`).
- **Weekly practice insights** — Every Monday at 8 AM IST, each doctor receives a 7-day summary: total appointments, past vs. upcoming, estimated no-show rate, busiest day and time slot, top patient complaints.
- **Appointment commands** — `today` shows the day's confirmed appointments; `pending` / `inbox` lists items awaiting approval.

### Doctor-Facing (Dashboard)

- **Clinic onboarding wizard** — Five-step flow: clinic details, add doctors, Twilio number, AI model selection, confirmation.
- **Doctor management** — CRUD for doctors including specialty, WhatsApp number, working hours, appointment duration, and buffer time.
- **Per-clinic AI model configuration** — Select vendor (Groq / Anthropic / OpenAI / Google), model name, STT model, and store encrypted API keys. Test the live connection directly from the UI.
- **Appointments dashboard** — Dedicated appointments page listing all clinic appointments with filters by status (active / cancelled / completed) and doctor name. Admins can cancel or mark appointments complete directly from the dashboard. Appointment data is persisted to PostgreSQL (write-through on doctor approval).
- **Patient list** — Searchable, paginated table of all patients with name, phone number, last consultation date, and record count.
- **Patient detail** — Full profile (allergies, chronic conditions, current medications, blood group, doctor notes) and a reverse-chronological medical records timeline.
- **Medical records timeline** — Each consultation record shows SOAP sections (S/O/A/P), confidence score, diagnosis chips with SNOMED codes, medication chips with RxNorm codes, and a link to the generated PDF.
- **Lab report history** — Lab records show panel type, color-coded abnormal and critical values, and the original PDF link.
- **Super-admin panel** — Separate `/admin` area for listing all clinics across tenants and toggling active/inactive status.

### Clinical Intelligence

- **SOAP generation** — Consultation transcripts (text + transcribed audio) are fed to LLaMA 3.3 70B to produce structured SOAP notes with per-section confidence scores.
- **Confidence hardening** — If any section scores below 0.6, the doctor receives a named warning alongside the PDF.
- **Clinical entity extraction** — After every SOAP generation, symptoms (name, severity, duration), diagnoses (name, SNOMED code, severity), and medications (name, RxNorm code, frequency) are extracted as structured JSON.
- **SNOMED CT coding** — Diagnoses coded via local JSON lookup with NLM API fallback.
- **RxNorm coding** — Medications coded via local JSON lookup.
- **HL7 FHIR R4 Bundle** — Each MedicalRecord can carry a full FHIR Bundle with Condition and MedicationRequest resources.
- **Grounding check** — SOAP pipeline includes a grounding verification node before finalizing the note.
- **Follow-up question generation** — The scribe pipeline generates personalized follow-up questions the doctor should ask at the next visit.

### Infrastructure

- **Multi-tenant** — Each clinic has its own Twilio number, model configuration, doctors, and patients. Incoming webhooks are routed to the correct clinic by matching the Twilio destination number.
- **Per-clinic LLM selection** — API keys stored encrypted with Fernet; never returned in plain text via the API.
- **JWT authentication** — Dashboard login issues 7-day tokens (HS256). Role-based access: admin, superadmin.
- **APScheduler jobs** — Appointment reminders, two-stage no-show recovery, consultation inactivity timeout, daily after-hours flush, weekly insights.
- **Docker Compose** — Single command brings up PostgreSQL 16, Redis 7, FastAPI backend, and Next.js dashboard.
- **`dev_start.py`** — One-command dev startup: launches ngrok, writes `PUBLIC_BASE_URL` to `.env`, prints the Twilio webhook URL, then starts uvicorn with `--reload`.

---

## Database Schema

### `clinics`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| name | String(255) | |
| twilio_number | String(30) | Unique; used to route inbound webhooks |
| timezone | String(50) | Default: Asia/Kolkata |
| open_hour | Integer | Default: 9 |
| close_hour | Integer | Default: 18 |
| is_active | Boolean | Soft-delete flag |
| created_at | DateTime(tz) | |

### `clinic_users`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| email | String(255) | Unique, indexed |
| hashed_password | String(255) | bcrypt |
| full_name | String(255) | |
| role | String(20) | `admin` or `superadmin` |
| clinic_id | String (FK → clinics) | Nullable |
| is_active | Boolean | |
| created_at | DateTime(tz) | |

### `doctors`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| clinic_id | String (FK → clinics) | Indexed |
| name | String(255) | |
| specialty | String(100) | |
| whatsapp_number | String(30) | |
| working_hours_start | Integer | Default: 9 |
| working_hours_end | Integer | Default: 18 |
| appointment_duration_minutes | Integer | Default: 30 |
| buffer_minutes | Integer | Default: 5 |
| is_active | Boolean | Soft-delete |
| created_at | DateTime(tz) | |

### `model_configs`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| clinic_id | String (FK → clinics) | Unique (one config per clinic) |
| llm_vendor | String(20) | Default: `groq` |
| llm_model | String(100) | Default: `llama-3.3-70b-versatile` |
| stt_model | String(100) | Default: `whisper-large-v3-turbo` |
| groq_api_key_enc | String(500) | Fernet-encrypted; nullable |
| anthropic_api_key_enc | String(500) | Fernet-encrypted; nullable |
| openai_api_key_enc | String(500) | Fernet-encrypted; nullable |
| google_api_key_enc | String(500) | Fernet-encrypted; nullable |
| updated_at | DateTime(tz) | Auto-updated |

### `patients`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| clinic_id | String (FK → clinics) | Indexed |
| phone_number | String(30) | Indexed; unique per clinic (enforced at service layer) |
| name | String(255) | Nullable; set on first consultation |
| age | Integer | Nullable |
| gender | String(10) | `male` / `female` / `other`; nullable |
| blood_group | String(5) | A+, B-, O+, etc.; nullable |
| allergies | JSON | Array |
| chronic_conditions | JSON | Array |
| current_medications | JSON | Array |
| doctor_notes | String(2000) | Free-text doctor notes |
| is_active | Boolean | |
| created_at | DateTime(tz) | |
| last_visit_at | DateTime(tz) | Nullable; updated per consultation |

### `appointments`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | `APTxxxxx` format — matches the Redis appointment_id |
| clinic_id | String (FK → clinics) | Indexed |
| patient_id | String (FK → patients) | Nullable; resolved on confirmation |
| doctor_id | String (FK → doctors) | Nullable; resolved by name lookup |
| from_number | String(30) | Patient WhatsApp number; indexed |
| patient_name | String(255) | Denormalized; nullable |
| doctor_name | String(255) | Denormalized |
| date_str | String(100) | Human-readable date as provided by the patient (e.g. `18 June 2026`) |
| time_str | String(50) | Human-readable time (e.g. `10:00 AM`) |
| appointment_datetime | DateTime | Parsed from date_str + time_str at save time; used for sorting and dedup |
| symptoms | JSON | Array of symptom strings |
| status | String(20) | `active` / `cancelled` / `completed`; default `active`; indexed |
| confirmed_at | DateTime(tz) | When the doctor approved the appointment |
| reminder_sent | Boolean | Whether the scheduled reminder was delivered |
| created_at | DateTime(tz) | |
| updated_at | DateTime(tz) | Auto-updated |

Unique constraint: `(clinic_id, from_number, doctor_name, appointment_datetime)` — prevents a patient from booking the same doctor at the same slot twice even across sessions.

### `medical_records`

| Column | Type | Notes |
|---|---|---|
| id | String (PK) | UUID |
| patient_id | String (FK → patients) | Indexed |
| clinic_id | String (FK → clinics) | Indexed |
| doctor_id | String (FK → doctors) | Nullable; indexed |
| visit_date | DateTime(tz) | Indexed |
| record_type | String(30) | `consultation`, `lab_report`, `booking` |
| chief_complaint | String(500) | Nullable |
| soap_subjective | Text | Nullable |
| soap_objective | Text | Nullable |
| soap_assessment | Text | Nullable |
| soap_plan | Text | Nullable |
| soap_confidence | Float | Nullable; overall confidence score |
| diagnoses | JSON | `[{"name": ..., "snomed_code": ..., "severity": ...}]` |
| medications | JSON | `[{"name": ..., "rxnorm_code": ..., "frequency": ...}]` |
| symptoms | JSON | `[{"name": ..., "severity": ..., "duration": ...}]` |
| lab_panel_type | String(30) | Nullable |
| lab_results | JSON | `{all_values, abnormals, criticals}` |
| fhir_bundle | JSON | Full HL7 FHIR R4 Bundle |
| pdf_url | String(500) | Link to generated PDF |
| created_at | DateTime(tz) | |

---

## API Endpoints

### Auth (`/api/auth`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/signup` | Create clinic + admin user + default ModelConfig; returns JWT |
| POST | `/api/auth/login` | Validate email/password; returns JWT |
| GET | `/api/auth/me` | Current user profile + clinic details |

### Clinics (`/api/clinics`)

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/api/clinics/` | Superadmin | List all clinics |
| GET | `/api/clinics/{clinic_id}` | Admin or superadmin | Clinic detail |
| PUT | `/api/clinics/{clinic_id}` | Admin or superadmin | Partial update (name, timezone, hours) |
| DELETE | `/api/clinics/{clinic_id}` | Superadmin | Soft-delete clinic |

### Doctors (`/api/clinics/{clinic_id}/doctors`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/clinics/{id}/doctors/` | List active doctors |
| POST | `/api/clinics/{id}/doctors/` | Create doctor |
| GET | `/api/clinics/{id}/doctors/{doctor_id}` | Doctor detail |
| PUT | `/api/clinics/{id}/doctors/{doctor_id}` | Partial update |
| DELETE | `/api/clinics/{id}/doctors/{doctor_id}` | Soft-delete |

### AI Config (`/api/clinics/{clinic_id}/config`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/clinics/{id}/config/` | LLM config (API keys masked as booleans) |
| PUT | `/api/clinics/{id}/config/` | Update vendor, model, STT model, API keys |
| POST | `/api/clinics/{id}/config/test` | Live connection test; returns latency in ms |

### Patients (`/api/clinics/{clinic_id}/patients`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/clinics/{id}/patients/` | Paginated patient list with optional name/phone search |
| GET | `/api/clinics/{id}/patients/by-phone/{phone}` | Look up patient by phone number |
| GET | `/api/clinics/{id}/patients/{patient_id}` | Full patient profile |
| PUT | `/api/clinics/{id}/patients/{patient_id}` | Partial update of patient profile |
| GET | `/api/clinics/{id}/patients/{patient_id}/records` | Medical records timeline (optional `type` filter) |

### Appointments (`/api/clinics/{clinic_id}/appointments`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/clinics/{id}/appointments/` | List appointments with optional filters: `status`, `doctor_name`, `from_date`, `to_date`, `skip`, `limit` |
| GET | `/api/clinics/{id}/appointments/{appointment_id}` | Single appointment detail |
| PUT | `/api/clinics/{id}/appointments/{appointment_id}` | Update appointment status (`active` / `cancelled` / `completed`) — updates both PostgreSQL and Redis |
| GET | `/api/clinics/{id}/appointments/patient/{patient_id}` | All appointments for a specific patient |

### WhatsApp & Clinical

| Method | Path | Description |
|---|---|---|
| GET | `/webhook/twilio` | Health check |
| POST | `/webhook/twilio` | Main Twilio inbound handler (all WhatsApp traffic) |
| POST | `/classify` | Direct classifier test (no WhatsApp needed) |
| POST | `/scribe/consult` | Consultation bundle → SOAP result (Jameel scribe API) |
| GET | `/scribe/pdf/{id}` | Serve a generated SOAP note PDF |
| POST | `/parser/parse-report` | Lab report PDF extraction |
| GET | `/lab-report/pdf/{id}` | Serve a lab report PDF |

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check + feature flags |
| GET | `/docs` | Swagger UI (FastAPI auto-docs) |

---

## Dashboard Routes

| Route | Description |
|---|---|
| `/` | Public marketing/landing page |
| `/auth/login` | Login form (email + password, saves JWT) |
| `/auth/signup` | Registration form (Zod-validated, creates clinic + admin) |
| `/onboarding` | Redirects to `/onboarding/clinic` |
| `/onboarding/clinic` | Step 1: Clinic name and details |
| `/onboarding/doctors` | Step 2: Add initial doctors |
| `/onboarding/twilio` | Step 3: Configure Twilio WhatsApp number |
| `/onboarding/model` | Step 4: Pick AI model and enter API key |
| `/onboarding/done` | Step 5: Completion confirmation |
| `/dashboard` | Overview: clinic stats, doctor cards, WhatsApp link, model badge |
| `/dashboard/doctors` | Doctors CRUD: list, invite, edit, deactivate |
| `/dashboard/patients` | Patient list: searchable table with name, phone, last consult |
| `/dashboard/patients/[id]` | Patient detail: full profile, medical records, allergies, notes |
| `/dashboard/appointments` | Appointments table: filter by status/doctor, cancel or complete from dashboard |
| `/dashboard/config` | AI Config: model selection, API key input, connection test |
| `/admin` | Super-admin: list all clinics, toggle active/inactive |
| `/admin/clinics/[id]` | Per-clinic detail view for super-admin |
| `/docs` | Redirects to `/docs/getting-started` |
| `/docs/getting-started` | Getting started guide |
| `/docs/doctor-guide` | Guide for doctors using the WhatsApp bot |
| `/docs/patient-guide` | Guide for patients |
| `/docs/ai-models` | Documentation on supported AI models |
| `/docs/twilio-setup` | Twilio/WhatsApp configuration walkthrough |

Dashboard sidebar navigation: Overview, Doctors, Patients, Appointments, AI Config, Documentation.

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 and Redis 7 (provided via Docker Compose, or install locally)
- Twilio account with a WhatsApp-enabled number (sandbox is fine for development)
- Groq API key (required); Gemini API key (recommended for classifier fallback)

### Quick Start (Docker — all services)

```bash
cp .env .env.local        # edit .env with your real keys
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs

The compose file starts four services: `postgres` (port 5432), `redis` (port 6379), `api` (port 8000), `dashboard` (port 3000).

### Local Development (recommended)

**Step 1 — Start data services only**

```bash
docker compose up postgres redis -d
```

**Step 2 — Backend**

```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

# Copy and fill in your environment variables
cp .env .env.local        # edit DATABASE_URL to point to localhost:5432

uvicorn main:app --reload --port 8000
```

**Step 3 — Dashboard**

```bash
cd dashboard
npm install
npm run dev
```

**Step 4 — Expose API for Twilio webhooks**

```bash
python dev_start.py
```

`dev_start.py` auto-starts ngrok, writes `PUBLIC_BASE_URL` into `.env`, prints the exact Twilio webhook URL to paste in the Twilio console, and then starts uvicorn. Every ngrok restart generates a new URL — paste it into the [Twilio WhatsApp Sandbox webhook field](https://console.twilio.com) each time, or use a paid ngrok static domain.

Twilio webhook URL to configure:
```
https://<ngrok-id>.ngrok-free.app/webhook/twilio
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key for LLaMA 3.3 70B and Whisper |
| `GROQ_MODEL` | No | Default: `llama-3.3-70b-versatile` |
| `WHISPER_MODEL` | No | Default: `whisper-large-v3` |
| `GEMINI_API_KEY` | Recommended | Google Gemini API key for classifier fallback |
| `GEMINI_MODEL` | No | Default: `gemini-2.5-flash` |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | Yes | Twilio WhatsApp sender number (e.g. `whatsapp:+14155238886`) |
| `SOAP_APPROVAL_CONTENT_SID` | No | Twilio Content Template SID for SOAP approval buttons |
| `APPOINTMENT_APPROVAL_CONTENT_SID` | No | Twilio Content Template SID for appointment approval buttons |
| `DOCTOR_WHATSAPP_NUMBERS` | Yes | CSV of `Name:+number` or bare `+number` pairs identifying doctor WhatsApp numbers |
| `DATABASE_URL` | Yes | PostgreSQL connection string, e.g. `postgresql+asyncpg://clinicai:password@localhost:5432/clinicai` |
| `REDIS_URL` | Yes | Redis connection string, e.g. `redis://localhost:6379` |
| `SECRET_KEY` | Yes | Secret used to sign JWT tokens |
| `ENCRYPTION_KEY` | Yes | Fernet key for encrypting API keys at rest |
| `PUBLIC_BASE_URL` | Yes | Publicly reachable base URL for webhook callbacks and PDF links (written automatically by `dev_start.py`) |
| `DASHBOARD_URL` | No | Dashboard origin for CORS; default `http://localhost:3000` |
| `CLINIC_NAME` | No | Default clinic name; default `ClinicAI` |
| `CLINIC_OPEN_HOUR` | No | Clinic opening hour (24h); default `9` |
| `CLINIC_CLOSE_HOUR` | No | Clinic closing hour (24h); default `20` |
| `SEED_DEMO_DOCTORS` | No | Seed demo doctor records on startup; default `false` |
| `REMINDER_MINUTES_BEFORE` | No | Minutes before appointment to send reminder; use `2` for demo, `120` for production |
| `DEMO_REMINDER_DELAY_MINUTES` | No | Demo reminder delay override; default `2` |
| `CONSULTATION_TIMEOUT_MINUTES` | No | Inactivity minutes before consultation auto-closes; use `2` for demo, `30` for production |
| `FOLLOWUP_DEFAULT_DAYS` | No | Days after consultation to send follow-up; default `2` |
| `DEMO_FOLLOWUP_DELAY_MINUTES` | No | Demo follow-up delay override; default `3` |
| `JAMEEL_SCRIBE_URL` | No | Remote scribe API URL; leave empty to run the scribe pipeline locally |
| `GOOGLE_CALENDAR_ENABLED` | No | Enable Google Calendar integration; default `False` |
| `GOOGLE_CALENDAR_CREDENTIALS_FILE` | No | Path to Google OAuth credentials JSON |
| `GOOGLE_CALENDAR_TOKEN_FILE` | No | Path to Google OAuth token cache file |
| `GOOGLE_CALENDAR_ID` | No | Google Calendar ID; default `primary` |
| `GOOGLE_CALENDAR_TIMEZONE` | No | Timezone for calendar events; default `Asia/Kolkata` |
| `APPOINTMENT_DURATION_MINUTES` | No | Default appointment slot length; default `30` |
| `APPOINTMENT_SLOT_CANDIDATES` | No | Override candidate time slots (CSV) |

---

## How Patients Use It

1. Join the clinic's Twilio WhatsApp sandbox by messaging the sandbox keyword to the clinic's WhatsApp number.
2. Send any greeting (`hi`, `hello`) to receive a welcome message.
3. To book: say `I want to book an appointment with Dr [Name]` and follow the conversational prompts for date, time, and symptoms.
4. Once the doctor approves, receive a confirmation with date and time. A reminder is sent automatically before the appointment.
5. To book a second appointment with a different doctor (e.g. orthopedic while waiting for a cardiology appointment), just say `book appointment` again. The bot starts a fresh booking flow while keeping the existing appointment intact.
6. To cancel or reschedule, say `cancel` or `reschedule`. If you have multiple active appointments, the bot shows a numbered list — reply with the number to target the right one.
7. During the appointment, continue the conversation over WhatsApp. Send voice notes or text describing symptoms.
8. To close the consultation, send a closing phrase such as `ok done`, `take care`, or `bye`. The SOAP note is generated and the doctor reviews the PDF before sending it back.
9. To upload a lab report, send the PDF as a WhatsApp attachment. The system extracts results and forwards them to the doctor.
10. For follow-up queries after a consultation, send a message and the bot responds with context from the last visit.

---

## How Doctors Use It

### Via WhatsApp

1. Receive appointment requests with Approve/Reject buttons. Tap to approve or reply `YES APTxxxxx`.
2. Send a voice note at any time (outside a consultation) to generate a SOAP note PDF for that patient. Review and approve it before it is sent to the patient.
3. During an active consultation, send voice notes to add clinical observations to the session buffer. Send `ok done` or a closing phrase to finalize.
4. Send `today` for the day's appointments or `pending` / `inbox` for items awaiting approval.
5. Receive weekly practice insights every Monday morning automatically.

### Via Dashboard

1. Log in at `/auth/login` with the admin credentials created during signup.
2. Complete the onboarding wizard (`/onboarding`) to configure the clinic, add doctors, set up the Twilio number, and choose an AI model.
3. Manage doctors at `/dashboard/doctors` — add, edit, or deactivate.
4. Browse patients at `/dashboard/patients` — search by name or phone number.
5. Open a patient detail page to view the full medical history timeline including SOAP notes, diagnoses with SNOMED codes, medications with RxNorm codes, and lab report values.
6. View all clinic appointments at `/dashboard/appointments`. Filter by status or doctor name, and cancel or mark appointments complete directly from the table.
7. Configure or change the AI model and API keys at `/dashboard/config` and test the connection live.

---

## Medical History Flow

Every interaction that creates clinical data is automatically persisted — no manual data entry required.

1. **First WhatsApp contact**: When a patient messages for the first time, `upsert_patient` creates a `Patient` row for `(clinic_id, phone_number)`. The name is updated whenever it becomes known (e.g., from the booking flow).

2. **Appointment confirmation**: When a doctor approves an appointment, an `Appointment` row is written to PostgreSQL (write-through from Redis) with `status="active"`. The appointment is simultaneously kept in Redis for fast lookup during the WhatsApp conversation flow. Cancellations and reschedules update `status` in both stores.

3. **Each consultation**: When a consultation closes (via closing phrase or inactivity timeout), `patient_service` is called from the consultation service. A `MedicalRecord` row with `record_type="consultation"` is written containing the full SOAP note, clinical entities (symptoms, diagnoses, medications), SNOMED/RxNorm codes, confidence scores, the FHIR bundle, and a link to the generated PDF. `Patient.last_visit_at` is updated.

4. **Lab reports**: When a lab PDF is processed, a `MedicalRecord` with `record_type="lab_report"` is written containing the panel type, all values, and flagged abnormals and criticals.

5. **Dashboard view**: The doctor opens the patient detail page for the full medical history timeline, and the appointments page for all upcoming and past appointments — all rendered from PostgreSQL.

Data accumulates automatically from every patient interaction without any manual effort from the doctor or clinic staff.

---

## Known Limitations

- **APScheduler state is in-memory** — Scheduled jobs (reminders, no-show recovery, weekly insights) are lost if the server restarts. A Redis jobstore would make them durable.
- **LangGraph MemorySaver is in-RAM** — Booking sub-graph thread checkpoints are lost on server restart. A `RedisSaver` or `PostgresSaver` would provide persistence.
- **MedicalRecord has no appointment_id foreign key** — Consultation records link to the patient but not to a specific appointment. Adding an `appointment_id` column to `medical_records` would close the appointment → consultation → SOAP chain.
- **No test suite** — There are no automated unit or integration tests. The pipeline is verified manually (see the existing detailed test guide in the repository).
- **Doctor-side consultation close not wired** — The doctor cannot currently send a closing phrase from their side to finalize a consultation; the close must come from the patient side or via timeout.
- **No CI/CD pipeline** — There is no automated build, test, or deployment pipeline configured.
- **Twilio webhook signature validation not implemented** — The webhook endpoint does not verify the `X-Twilio-Signature` header. This should be added before production deployment.
- **Debug endpoints are unauthenticated** — `/debug/*` endpoints expose internal state without auth and must be removed or gated before public deployment.
- **ngrok URL changes on every restart** — The Twilio webhook URL must be updated manually (or `PUBLIC_BASE_URL` re-written) each time the dev server restarts without a paid static domain.
