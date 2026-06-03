# ClinicAI — Engineering Report
**Version:** 4.0.0
**Date:** 2026-06-02

---

## 1. Project Overview

ClinicAI is a WhatsApp-native clinical front-desk assistant and SaaS platform built on FastAPI + LangGraph. It handles the full patient lifecycle — from first contact through appointment booking, real-time consultation orchestration, clinical documentation, and post-visit follow-up — entirely over WhatsApp via Twilio, with a companion Next.js dashboard for clinic administrators and doctors.

**Core premise:** A patient sends a WhatsApp message. ClinicAI classifies intent using a Groq-hosted LLaMA 3.3 70B model, routes to a specialist agent, manages multi-turn state in Redis, and replies with a contextually appropriate response. Doctors interact with the same WhatsApp interface to approve appointments, receive SOAP notes, perform clinical review, and close consultations. The beta dashboard (Sprint 4) adds full multi-tenant SaaS onboarding, persistent patient profiles, and medical history browsing.

**Who uses it and how:**

| Actor | Interface | Primary Actions |
|---|---|---|
| Patient | WhatsApp | Book appointments, consult with AI assistant, receive follow-ups, submit lab reports |
| Doctor | WhatsApp | Approve/reject bookings, review SOAP notes, REGEN command, voice note upload |
| Clinic Admin | Next.js Dashboard | Onboarding, doctor management, AI model configuration, patient records browsing |
| Super-Admin | Next.js /admin | Multi-tenant clinic oversight, activate/deactivate clinics |

**Current state:** Beta — multi-clinic SaaS onboarding dashboard is live. Core WhatsApp flows are stable and production-tested. PostgreSQL persistence is complete. No CI/CD pipeline yet.

**Technology stack summary:**

- Runtime: Python 3.12, FastAPI 0.115.5, uvicorn 0.32.1
- Agent framework: LangGraph 0.3.5 (`StateGraph`, `MemorySaver`)
- LLM: Groq LLaMA 3.3 70B (primary), Gemini 2.5 Flash (fallback), per-clinic override via DB
- STT: Groq Whisper Large v3 / Whisper Large v3 Turbo
- Database: PostgreSQL 16 via SQLAlchemy 2.0 async + asyncpg
- Session store: Redis 7
- Messaging: Twilio WhatsApp Business API
- Scheduling: APScheduler 3.10.4 BackgroundScheduler
- PDF: ReportLab (generation), pdfplumber + pytesseract (extraction/OCR)
- Medical coding: SNOMED CT, RxNorm, HL7 FHIR R4
- Dashboard: Next.js 16 App Router, TypeScript, Tailwind CSS, shadcn/ui, React Query

---

## 2. Sprint History

### Sprint 1 — Core WhatsApp Automation

- **Intent classifier** — 6-node LangGraph `StateGraph`; classifies inbound messages into: booking, consultation, emergency, lab report, follow-up, general.
- **Appointment booking state machine** — 10-state finite state machine: `GREETING → COLLECTING_INFO → COLLECT_DATE_TIME → COLLECT_DOCTOR_PREFERENCE → CONFIRM_SLOT → WAITING_DOCTOR_APPROVAL → BOOKED` plus `CANCEL_CONFIRM`, `RESCHEDULE_INIT`, `RESCHEDULE_CONFIRM`. Full round-trip with doctor approval via Twilio Content Template interactive buttons (Approve / Reject / Suggest Time).
- **Doctor approval workflow** — Twilio interactive buttons sent to doctor's WhatsApp; button payload parsed by webhook to advance booking state machine.
- **Google Calendar integration** — Optional; creates calendar events on booking confirmation. Controlled by `GOOGLE_CALENDAR_ENABLED` env var.
- **APScheduler jobs** — Appointment reminders (configurable minutes before), no-show recovery, after-hours message flush, weekly clinical insights per doctor.
- **Standalone clinical scribe** — Voice note (OGG) → Groq Whisper transcription → LLM SOAP note generation → ReportLab PDF → WhatsApp delivery to doctor.
- **Lab report parsing** — PDF upload → pdfplumber text extraction + pytesseract OCR fallback → panel detection (CBC/LFT/KFT/LIPID/THYROID) → LLM structured extraction → abnormal/critical flagging → summary delivery.
- **Redis session store** — Multi-turn conversation state persisted per phone number with TTL.

### Sprint 2 — Multi-Agent Refactor

- **RouterAgent** — Top-level LangGraph agent replaces monolithic intent classifier. Dispatches to six specialist sub-agents based on classified intent.
- **Six sub-agents:**
  - `BookingAgent` — full appointment booking state machine
  - `ConsultationAgent` — real-time doctor-patient consultation buffering; integrates Jameel scribe contract
  - `EmergencyAgent` — immediate WhatsApp alert to on-call doctor
  - `LabAgent` — PDF/image lab report pipeline
  - `FollowUpAgent` — post-consultation follow-up scheduling and reminders
  - `AfterHoursAgent` — queues messages received outside clinic hours; flushes at opening
- **Jameel scribe integration contract** — Defined API boundary between ConsultationAgent session close and external scribe pipeline; enables parallel scribe development.
- **ConsultationAgent session management** — `ConsultationSession` dataclass buffered in Redis (4h TTL); accumulates all messages with `sender_role` tagging.
- **AfterHoursAgent flush job** — APScheduler job reads queued after-hours messages at `CLINIC_OPEN_HOUR` and processes them.
- **Enhanced EmergencyAgent** — Sends WhatsApp alert to all registered doctor numbers with patient phone and summary.
- **Weekly insights job** — Per-doctor APScheduler weekly job summarizes consultation volume and common complaint categories.

### Sprint 3 — Medical Coding and FHIR

- **HL7 FHIR R4 Bundle generation** — `fhir_coding_node` added to scribe pipeline after entity extraction. Builds valid FHIR R4 `Bundle` containing `Condition` and `MedicationRequest` resources programmatically.
- **SNOMED CT coding** — Every diagnosis and symptom receives an authoritative SNOMED CT concept ID. LLM is explicitly excluded from code assignment; the coding layer uses a deterministic lookup chain.
- **RxNorm coding** — Every medication receives an RxNorm RxCUI via the same lookup chain.
- **`terminology.py` three-tier lookup:**
  1. Local curated JSON tables (instant, offline)
  2. NLM public UMLS/RxNav API (network, authoritative)
  3. `UNKNOWN` sentinel (never hallucinates a code)
- **`REGEN` command** — Doctor sends `REGEN <feedback>` via WhatsApp to trigger SOAP regeneration using original audio transcription plus correction feedback, without re-recording.
- **Multi-doctor registry** — 14 specialty types; doctor routing supports preference-matching during booking.
- **SOAP codes in output** — SNOMED/RxNorm codes appear in both the PDF report and the doctor's WhatsApp approval message.

### Sprint 4 — Beta Dashboard and Persistent Data Layer (Current)

- **PostgreSQL data layer** — SQLAlchemy 2.0 async ORM, 6 models: `Clinic`, `ClinicUser`, `Doctor`, `ModelConfig`, `Patient`, `MedicalRecord`. Alembic for migrations.
- **JWT authentication** — `python-jose` HS256 tokens, 7-day expiry, bcrypt password hashing via passlib. Full `GET /me`, login, and signup flows.
- **Clinic management APIs** — `/api/clinics` CRUD; soft-delete pattern (`is_active=False`).
- **Doctor management APIs** — `/api/clinics/{clinic_id}/doctors` CRUD with all scheduling fields.
- **Patient management APIs** — `/api/clinics/{clinic_id}/patients` — paginated list, phone lookup, full profile detail, medical records timeline.
- **LLM config API with encrypted keys** — `/api/clinics/{clinic_id}/config` — per-clinic vendor/model/STT selection; API keys encrypted with Fernet (AES-128-CBC) before storage; never returned in plain text; `POST /test` validates live connection.
- **Unified doctor identity** — `identity.py` checks `DOCTOR_WHATSAPP_NUMBERS` env var first, then falls back to async DB query against `doctors` table. Enables full DB-driven doctor management without env var changes.
- **Persistent patient profiles** — `patient_service.py` `upsert_patient()` creates or updates `Patient` row on every WhatsApp interaction. Name captured during booking flow and stored.
- **Automatic medical history** — `save_consultation_record()` called on every ConsultationAgent close; `save_lab_record()` called on every lab report parse. Both write `MedicalRecord` rows to PostgreSQL with full structured data.
- **Next.js 16 dashboard** — Full App Router SPA with sidebar navigation, JWT-gated routes, shadcn/ui component library.
- **5-step onboarding wizard** — Clinic → Doctors → Twilio → AI Model → Done.
- **Patient list and detail views** — Searchable/paginated patient table; detail view shows SOAP history, diagnosis chips (SNOMED codes), lab result color-coding (normal/abnormal/critical), allergies, chronic conditions, doctor notes.
- **Docker Compose** — Four services: `postgres:16-alpine`, `redis:7-alpine`, `api`, `dashboard`.

---

## 3. Architecture

### 3.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  WHATSAPP CHANNEL                                               │
│                                                                 │
│  Patient Device          Doctor Device                          │
│  (WhatsApp)              (WhatsApp)                             │
└──────────┬───────────────────────┬──────────────────────────────┘
           │                       │
           └───────────┬───────────┘
                       ↓
              Twilio WhatsApp API
                       ↓
         POST /webhook/twilio  [webhook_router.py]
                       ↓
         identify_sender_async()
         ┌─────────────┴──────────────┐
         │  env var lookup first      │
         │  DB fallback (doctors tbl) │
         └─────────────┬──────────────┘
                       ↓
           ┌───────────┴────────────┐
           │                        │
        PATIENT                   DOCTOR
           │                        │
           ↓                        ↓
   router_graph (LangGraph)   handle_doctor_message()
   after_hours_check               │
        ↓                    ┌─────┴──────────────────┐
   intent_node               │  Approval button       │
   (6-class classifier)      │  SOAP review           │
        ↓                    │  REGEN <feedback>      │
   session_node              │  Voice note upload     │
        ↓                    └────────────────────────┘
   dispatch:
   ┌──────────────────────────────────────┐
   │ BookingAgent      → Google Calendar  │
   │ ConsultationAgent → Redis session    │
   │ EmergencyAgent    → Doctor alert     │
   │ LabAgent          → OCR pipeline     │
   │ FollowUpAgent     → APScheduler      │
   │ AfterHoursAgent   → queue/flush      │
   └──────────────────────────────────────┘
           │
           ↓  (on ConsultationAgent close)
   scribe_service pipeline:
     transcribe_audio_node
     → soap_generator_node
     → extract_entities_node
     → fhir_coding_node (SNOMED + RxNorm)
     → grounding_check_node
     → followup_generator_node
     → pdf_output_node
           │
           ↓
   patient_service.save_consultation_record()
           │
           ↓
     PostgreSQL (MedicalRecord row)

┌─────────────────────────────────────────────────────────────────┐
│  DASHBOARD CHANNEL                                              │
│                                                                 │
│  Clinic Admin / Doctor Browser                                  │
│         ↓                                                       │
│  Next.js Dashboard (port 3000)                                  │
│    /auth/login → POST /api/auth/login → JWT                     │
│    /onboarding/* → 5-step wizard                                │
│    /dashboard → clinic stats, doctor cards                      │
│    /dashboard/doctors → CRUD                                    │
│    /dashboard/patients → list → [id] detail + history           │
│    /dashboard/config → LLM model selection + key test           │
│    /admin → superadmin multi-tenant oversight                   │
│         ↓                                                       │
│  FastAPI Management APIs (port 8000)                            │
│    /api/auth  /api/clinics  /api/doctors                        │
│    /api/config  /api/patients                                   │
└─────────────────────────────────────────────────────────────────┘

Shared Infrastructure:
  PostgreSQL 16  ←── SQLAlchemy async ORM (asyncpg driver)
  Redis 7        ←── Conversation sessions, booking state, queues
  APScheduler    ←── Reminders, flush jobs, weekly insights
```

### 3.2 Database Schema

#### Table: `clinics`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key, auto-generated |
| `name` | String(255) | Clinic display name |
| `twilio_number` | String(30) | Unique; routes inbound WhatsApp to correct clinic |
| `timezone` | String(50) | Default: `Asia/Kolkata` |
| `open_hour` | Integer | Default: 9; used by AfterHoursAgent |
| `close_hour` | Integer | Default: 18 |
| `is_active` | Boolean | Soft-delete flag |
| `created_at` | DateTime(tz) | Server-side `now()` |

Relationships: `users` (one-to-many ClinicUser), `doctors` (one-to-many Doctor), `model_config` (one-to-one ModelConfig), `patients` (one-to-many Patient).

#### Table: `clinic_users`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `email` | String(255) | Unique, indexed |
| `hashed_password` | String(255) | bcrypt hash |
| `full_name` | String(255) | |
| `role` | String(20) | `admin` or `superadmin` |
| `clinic_id` | String (FK → clinics.id) | Nullable; superadmins have no clinic |
| `is_active` | Boolean | |
| `created_at` | DateTime(tz) | |

Relationships: `clinic` (many-to-one Clinic).

#### Table: `doctors`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `clinic_id` | String (FK → clinics.id) | Indexed |
| `name` | String(255) | |
| `specialty` | String(100) | One of 14 supported specialties |
| `whatsapp_number` | String(30) | E.164 format; used for approval routing |
| `working_hours_start` | Integer | Hour of day (0-23), default 9 |
| `working_hours_end` | Integer | Hour of day (0-23), default 18 |
| `appointment_duration_minutes` | Integer | Default 30 |
| `buffer_minutes` | Integer | Buffer between appointments, default 5 |
| `is_active` | Boolean | Soft-delete flag |
| `created_at` | DateTime(tz) | |

Relationships: `clinic` (many-to-one Clinic). Referenced by `MedicalRecord.doctor_id`.

#### Table: `model_configs`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `clinic_id` | String (FK → clinics.id) | Unique (one config per clinic) |
| `llm_vendor` | String(20) | `groq`, `anthropic`, `openai`, `google`; default `groq` |
| `llm_model` | String(100) | Default `llama-3.3-70b-versatile` |
| `stt_model` | String(100) | Default `whisper-large-v3-turbo` |
| `groq_api_key_enc` | String(500) | Fernet-encrypted; nullable |
| `anthropic_api_key_enc` | String(500) | Fernet-encrypted; nullable |
| `openai_api_key_enc` | String(500) | Fernet-encrypted; nullable |
| `google_api_key_enc` | String(500) | Fernet-encrypted; nullable |
| `updated_at` | DateTime(tz) | Auto-updated on every write |

Relationships: `clinic` (many-to-one Clinic). Auto-created at clinic signup with Groq defaults.

#### Table: `patients`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `clinic_id` | String (FK → clinics.id) | Indexed; patient is scoped to one clinic |
| `phone_number` | String(30) | Indexed; unique per clinic enforced at service layer |
| `name` | String(255) | Nullable; populated during booking |
| `age` | Integer | Nullable |
| `gender` | String(10) | `male`/`female`/`other`; nullable |
| `blood_group` | String(5) | `A+`, `B-`, `O+`, etc.; nullable |
| `allergies` | JSON | Array of allergy strings |
| `chronic_conditions` | JSON | Array of condition strings |
| `current_medications` | JSON | Array of medication strings |
| `doctor_notes` | String(2000) | Free-text notes from doctor; nullable |
| `is_active` | Boolean | Default true |
| `created_at` | DateTime(tz) | |
| `last_visit_at` | DateTime(tz) | Nullable; updated on each new MedicalRecord |

Relationships: `clinic` (many-to-one Clinic), `records` (one-to-many MedicalRecord, ordered by `visit_date DESC`).

No database-level unique constraint on `(clinic_id, phone_number)` — enforced via `upsert_patient()` service logic.

#### Table: `medical_records`

| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Primary key |
| `patient_id` | String (FK → patients.id) | Indexed |
| `clinic_id` | String (FK → clinics.id) | Indexed; denormalized for query efficiency |
| `doctor_id` | String (FK → doctors.id) | Nullable; indexed |
| `visit_date` | DateTime(tz) | Indexed; defaults to insert time |
| `record_type` | String(30) | `consultation`, `lab_report`, `booking` |
| `chief_complaint` | String(500) | Nullable |
| `soap_subjective` | Text | Nullable |
| `soap_objective` | Text | Nullable |
| `soap_assessment` | Text | Nullable |
| `soap_plan` | Text | Nullable |
| `soap_confidence` | Float | LLM self-reported confidence score; nullable |
| `diagnoses` | JSON | Array of `{name, snomed_code, severity}` |
| `medications` | JSON | Array of `{name, rxnorm_code, frequency}` |
| `symptoms` | JSON | Array of `{name, severity, duration}` |
| `lab_panel_type` | String(30) | `CBC`, `LFT`, `KFT`, `LIPID`, `THYROID`; nullable |
| `lab_results` | JSON | `{all_values: [...], abnormals: [...], criticals: [...]}` |
| `fhir_bundle` | JSON | Full FHIR R4 Bundle as JSON object; nullable |
| `pdf_url` | String(500) | Path/URL to generated PDF; nullable |
| `created_at` | DateTime(tz) | |

Relationships: `patient` (many-to-one Patient), `doctor` (many-to-one Doctor, nullable).

Retention: No TTL or archival policy implemented yet. All records are permanent.

### 3.3 Redis Key Schema

Redis is used for multi-turn conversation state, booking state machine state, after-hours queues, and session metadata. The following key patterns are in use (TTLs sourced from `store.py` and session management):

| Key Pattern | Content | TTL |
|---|---|---|
| `session:{phone_number}` | Current agent state + conversation buffer | 4 hours |
| `booking:{phone_number}` | BookingAgent sub-state machine (JSON) | 24 hours |
| `consultation:{phone_number}` | ConsultationSession buffer (messages + roles) | 4 hours |
| `afterhours:{clinic_id}:{phone_number}` | Queued after-hours messages | Until flush at open hour |
| `followup:{phone_number}` | Follow-up scheduling metadata | Until follow-up sent |
| `doctor_alert:{phone_number}:{timestamp}` | Emergency alert dedup key | 1 hour |

LangGraph `MemorySaver` checkpoints for the router graph and sub-agents are stored in-process RAM, not Redis. Booking sub-state survives Redis eviction but is lost on API server restart.

### 3.4 LLM Stack

| Role | Model | Provider | Config |
|---|---|---|---|
| Primary LLM | `llama-3.3-70b-versatile` | Groq | `GROQ_API_KEY` env var |
| Fallback LLM | `gemini-2.5-flash` | Google Gemini | `GEMINI_API_KEY` env var |
| STT (transcription) | `whisper-large-v3` / `whisper-large-v3-turbo` | Groq | `WHISPER_MODEL` env var |
| Per-clinic override | Any supported model | Any supported vendor | `model_configs` table |

`llm_factory.py` resolves the correct LLM client at runtime:
1. Load `ModelConfig` for the clinic via `resolve_model_config_for_clinic()`.
2. If a clinic-specific encrypted API key is present for the configured vendor, decrypt with Fernet and use it.
3. Fall back to global env-var key if no clinic key is configured.
4. If no `ModelConfig` row exists, use global env-var defaults.

Supported vendors in `model_configs.llm_vendor`: `groq`, `anthropic`, `openai`, `google`. LangChain integration packages are conditionally imported; `langchain-anthropic` and `langchain-openai` are listed as optional in `requirements.txt`.

---

## 4. WhatsApp Flows

### 4.1 Appointment Booking (10-State Machine)

The BookingAgent manages a finite state machine with the following states:

```
GREETING
  ↓ (patient message)
COLLECTING_INFO          ← Gathers name, phone, reason for visit
  ↓
COLLECT_DATE_TIME        ← Parses preferred appointment date/time (NLP)
  ↓
COLLECT_DOCTOR_PREFERENCE ← Optional specialty/doctor name preference
  ↓
CONFIRM_SLOT             ← Shows proposed slot to patient for confirmation
  ↓
WAITING_DOCTOR_APPROVAL  ← Sends Twilio interactive button message to doctor
  ↓
  ├── Doctor approves → BOOKED (confirmation to patient + calendar event)
  ├── Doctor rejects → notifies patient, returns to COLLECT_DATE_TIME
  └── Doctor suggests time → RESCHEDULE_INIT → RESCHEDULE_CONFIRM → BOOKED

Side states:
  CANCEL_CONFIRM         ← Patient asks to cancel; requires confirmation
```

**Doctor approval message** — Sent via Twilio Content Template (`SOAP_APPROVAL_CONTENT_SID`). Contains: patient name, phone, requested time, doctor name. Interactive buttons: `Approve`, `Reject`, `Suggest Time`.

**Reminder logic** — APScheduler fires a reminder job `REMINDER_MINUTES_BEFORE` (default 120) minutes before the appointment time. A separate no-show job fires 30 minutes after the appointment start if no consultation session has begun.

**Google Calendar** — Controlled by `GOOGLE_CALENDAR_ENABLED=False` (disabled by default). When enabled, creates a calendar event using service account credentials in `google_credentials.json`.

### 4.2 Consultation Flow

The ConsultationAgent handles real-time AI-mediated doctor-patient conversations.

**Session lifecycle:**
1. Patient message classified as `consultation` intent by RouterAgent.
2. `ConsultationSession` created in Redis with `session_id`, `patient_phone`, `doctor_phone`, `clinic_id`, `start_time`. TTL: 4 hours.
3. All subsequent messages from both patient and doctor are appended to the session buffer with `sender_role` tagging (`patient` or `doctor`).
4. AI responds to patient messages in the context of the accumulated conversation.
5. **Closing triggers:** 14-phrase vocabulary (English/Hindi, e.g., "that's all", "bas kar", "theek hai") OR 30-minute inactivity timeout (`CONSULTATION_TIMEOUT_MINUTES=2` in demo config, 30 in production).
6. On close: `scribe_service` pipeline is invoked.

**Doctor-initiated close** — Not yet implemented. Only patient-side close triggers the scribe pipeline (see Known Limitations §9.3).

### 4.3 Clinical Scribe Pipeline

Invoked after ConsultationAgent session close or when a doctor uploads a standalone voice note.

```
Input: audio (OGG) or consultation transcript buffer
  ↓
transcribe_audio_node
  → Groq Whisper STT → raw transcript text
  ↓
soap_generator_node
  → LLM prompt (transcript + system context) → structured SOAP note
  → Sections: Subjective, Objective, Assessment, Plan + confidence score
  ↓
extract_entities_node
  → LLM structured extraction → diagnoses[], medications[], symptoms[]
  → Each entity: name + severity/frequency/duration (no codes yet)
  ↓
fhir_coding_node
  → terminology.py three-tier lookup for each entity:
      1. Local curated JSON tables
      2. NLM UMLS / RxNav public API
      3. UNKNOWN sentinel
  → SNOMED CT codes → diagnoses + symptoms
  → RxNorm RxCUIs → medications
  → Builds FHIR R4 Bundle (Condition + MedicationRequest resources)
  ↓
grounding_check_node
  → Validates SOAP consistency; flags potential hallucinations
  ↓
followup_generator_node
  → Generates follow-up instructions and schedules FollowUpAgent job
  → Default delay: FOLLOWUP_DEFAULT_DAYS (2 days) or DEMO_FOLLOWUP_DELAY_MINUTES (3)
  ↓
pdf_output_node
  → ReportLab generates PDF with SOAP + codes + FHIR summary
  → Saved to ./generated/ volume
  → PDF sent to doctor via WhatsApp
  → SOAP + entity + FHIR data written to PostgreSQL MedicalRecord
```

**REGEN command:** Doctor sends `REGEN <optional feedback>` via WhatsApp. The pipeline re-runs from `soap_generator_node` using the stored audio transcript plus the feedback as correction context. Audio is not re-transcribed. A new MedicalRecord row is written; the old one is retained.

### 4.4 Lab Report Flow

Triggered when a patient or doctor sends a PDF or image to the lab report intent handler.

```
Input: PDF or image media attachment (MediaUrl0 from Twilio)
  ↓
Download media with Twilio auth headers
  ↓
Text extraction:
  → pdfplumber (PDF text extraction, primary)
  → pytesseract OCR (image or scanned PDF fallback)
  ↓
Panel detection
  → Regex + keyword matching → CBC | LFT | KFT | LIPID | THYROID
  ↓
LLM structured extraction
  → Per-panel prompt → {test_name, value, unit, reference_range, status}[]
  ↓
Abnormal/critical flagging
  → Compare value vs reference_range → normal | abnormal | critical
  ↓
SNOMED coding for test names and conditions
  ↓
MedicalRecord written to PostgreSQL
  → record_type = "lab_report"
  → lab_panel_type, lab_results JSON
  ↓
Summary WhatsApp message to doctor
  → Abnormals highlighted, criticals flagged with urgency language
```

---

## 5. Medical History System

### 5.1 Patient Lifecycle

```
First WhatsApp message received
  ↓
identify_sender_async() → classified as "patient"
  ↓
resolve_clinic_by_twilio_number(to_number) → Clinic row
  ↓
upsert_patient(clinic_id, phone_number)
  → SELECT WHERE clinic_id + phone_number
  → INSERT if not found
  → Returns patient_id
  ↓
Patient.name updated when captured during booking flow
Patient.last_visit_at updated on every new MedicalRecord

Consultation closes:
  → scribe_service completes
  → patient_service.save_consultation_record(patient_id, clinic_id, doctor_id, soap_data, entities, fhir_bundle)
  → MedicalRecord INSERT with record_type="consultation"

Lab report processed:
  → patient_service.save_lab_record(patient_id, clinic_id, lab_panel_type, lab_results)
  → MedicalRecord INSERT with record_type="lab_report"
```

### 5.2 Patient Model Fields

| Field | Type | Description |
|---|---|---|
| `id` | UUID string | Primary key |
| `clinic_id` | FK string | Owning clinic |
| `phone_number` | String(30) | WhatsApp number in E.164 format |
| `name` | String(255) | Optional; captured during booking |
| `age` | Integer | Optional |
| `gender` | String(10) | `male`, `female`, or `other` |
| `blood_group` | String(5) | `A+`, `B-`, `O+`, etc. |
| `allergies` | JSON array | Allergy strings; default empty list |
| `chronic_conditions` | JSON array | Condition strings; default empty list |
| `current_medications` | JSON array | Medication strings; default empty list |
| `doctor_notes` | String(2000) | Free-text notes from doctor (editable via dashboard) |
| `is_active` | Boolean | Default true |
| `created_at` | DateTime(tz) | First WhatsApp contact |
| `last_visit_at` | DateTime(tz) | Updated on each new MedicalRecord |

### 5.3 MedicalRecord Model Fields

| Field | Type | Description |
|---|---|---|
| `id` | UUID string | Primary key |
| `patient_id` | FK string | Owning patient |
| `clinic_id` | FK string | Denormalized for query efficiency |
| `doctor_id` | FK string | Nullable; attending doctor |
| `visit_date` | DateTime(tz) | Indexed; defaults to insert time |
| `record_type` | String(30) | `consultation`, `lab_report`, or `booking` |
| `chief_complaint` | String(500) | Patient's stated primary concern |
| `soap_subjective` | Text | Patient-reported symptoms and history |
| `soap_objective` | Text | Objective findings |
| `soap_assessment` | Text | AI/doctor assessment and differential |
| `soap_plan` | Text | Treatment plan and follow-up instructions |
| `soap_confidence` | Float | LLM self-reported confidence (0.0–1.0) |
| `diagnoses` | JSON | `[{name, snomed_code, severity}]` |
| `medications` | JSON | `[{name, rxnorm_code, frequency}]` |
| `symptoms` | JSON | `[{name, severity, duration}]` |
| `lab_panel_type` | String(30) | `CBC`, `LFT`, `KFT`, `LIPID`, `THYROID` |
| `lab_results` | JSON | `{all_values, abnormals, criticals}` arrays |
| `fhir_bundle` | JSON | Complete FHIR R4 Bundle object |
| `pdf_url` | String(500) | Path/URL to generated PDF in `./generated/` |
| `created_at` | DateTime(tz) | Row creation timestamp |

### 5.4 Doctor Dashboard View

On the `/dashboard/patients/[id]` page, clinic admins and doctors see:

- **Profile card** — Name, phone, age, gender, blood group; all fields editable via `PUT /api/clinics/{clinic_id}/patients/{patient_id}`.
- **Allergies, chronic conditions, current medications** — Displayed as chips; editable.
- **Doctor notes** — Free-text field; editable inline.
- **Visit timeline** — All `MedicalRecord` rows ordered by `visit_date DESC`. Each record shows: date, record type badge, doctor name, chief complaint.
- **SOAP tabs** — Expandable per-record view of all four SOAP sections.
- **Diagnosis chips** — Each diagnosis displayed with name + SNOMED CT code badge.
- **Medication chips** — Name + RxNorm RxCUI badge.
- **Lab results table** — Test name, value, reference range; abnormals highlighted in amber, criticals in red.

---

## 6. Dashboard Architecture

### 6.1 Tech Stack

| Component | Technology | Version |
|---|---|---|
| Framework | Next.js App Router | 16 |
| Language | TypeScript | Latest |
| Styling | Tailwind CSS | Latest |
| UI Components | shadcn/ui (Base UI) | Latest |
| Data Fetching | React Query (TanStack Query) | Latest |
| Forms | react-hook-form + zod | Latest |
| HTTP Client | axios | Latest |
| Toast Notifications | sonner | Latest |
| Build Output | Next.js standalone | — |

### 6.2 Route Map

```
/                                   — Public marketing/landing page (WhatsApp-first AI clinic pitch)

/auth/login                         — Login form (email + password → POST /api/auth/login → JWT saved)
/auth/signup                        — Registration form (zod-validated; creates clinic + user atomically)

/onboarding                         — Redirects to /onboarding/clinic
/onboarding/clinic                  — Step 1: Clinic name and basic details
/onboarding/doctors                 — Step 2: Add initial doctors (name, specialty, WhatsApp number)
/onboarding/twilio                  — Step 3: Enter Twilio WhatsApp number
/onboarding/model                   — Step 4: Select AI vendor/model
/onboarding/done                    — Step 5: Completion screen with next-steps guidance

/dashboard                          — Protected shell (JWT-gated); sidebar: Overview, Doctors, Patients, AI Config, Docs
/dashboard (page)                   — Clinic overview: stats, doctor list cards, WhatsApp link copy, active model badge
/dashboard/doctors                  — Doctors CRUD: list all doctors, invite new, edit details, deactivate
/dashboard/patients                 — Patient list: searchable/paginated table (name, phone, last consult date)
/dashboard/patients/[id]            — Patient detail: profile edit, medical records timeline, SOAP tabs, lab color-coding
/dashboard/config                   — AI Config: set vendor/model/STT, upload API key, test connection, view active model

/admin                              — Superadmin panel: list all clinics, toggle active/inactive status
/admin/clinics/[id]                 — Per-clinic detail view for superadmin inspection

/docs                               — Redirects to /docs/getting-started
/docs/getting-started               — Getting started guide for new clinic admins
/docs/doctor-guide                  — Guide for doctors using the WhatsApp bot
/docs/patient-guide                 — Guide for patients interacting with the AI
/docs/ai-models                     — Documentation on supported AI models and vendor selection
/docs/twilio-setup                  — Twilio/WhatsApp number configuration walkthrough
```

**Sidebar navigation (in `dashboard/layout.tsx`):**

| Label | Route | Icon |
|---|---|---|
| Overview | `/dashboard` | LayoutDashboard |
| Doctors | `/dashboard/doctors` | Users |
| Patients | `/dashboard/patients` | Users2 |
| AI Config | `/dashboard/config` | Settings |
| Documentation | `/docs` | BookOpen |

### 6.3 Auth Flow

```
User submits login form
  ↓
POST /api/auth/login (email + password)
  ↓
FastAPI: hash compare via passlib/bcrypt
  ↓
create_access_token(sub=user_id) → JWT (HS256, 7-day expiry)
  ↓
Response: {access_token, token_type, clinic_id, user_id, role}
  ↓
Dashboard: saveToken(token) → localStorage
  ↓
axios interceptor: adds "Authorization: Bearer <token>" to all API requests
  ↓
FastAPI: OAuth2PasswordBearer extracts token → verify_token() → user lookup
  ↓
get_current_user dependency: returns ClinicUser or raises HTTP 401
get_current_admin: raises HTTP 403 if role not in {admin, superadmin}
get_current_superadmin: raises HTTP 403 if role != superadmin
  ↓
Dashboard layout.tsx: isAuthenticated() check → redirect to /auth/login if false
```

### 6.4 Per-Clinic Model Selection

```
Admin navigates to /dashboard/config
  ↓
GET /api/clinics/{clinic_id}/config
  → Returns: llm_vendor, llm_model, stt_model, has_groq_key (bool), has_google_key (bool), etc.
  → API keys are NEVER returned in plain text; only boolean presence flags
  ↓
Admin selects vendor (groq/google/anthropic/openai), enters model name, pastes API key
  ↓
PUT /api/clinics/{clinic_id}/config
  → encrypt_api_key(raw_key) → Fernet AES-128-CBC → stores in {vendor}_api_key_enc column
  ↓
POST /api/clinics/{clinic_id}/config/test
  → test_llm_connection(model_config) → live inference call
  → Returns: {success: bool, response: str, latency_ms: float}
  ↓
At runtime (WhatsApp webhook):
  resolve_model_config_for_clinic(clinic_id, db) → ModelConfig row
  llm_factory.build_llm(model_config) →
    1. Decrypt clinic API key if present
    2. Instantiate LangChain LLM client (ChatGroq / ChatGoogleGenerativeAI / etc.)
    3. Fall back to global env-var key if no clinic key
    4. Return configured LLM instance to calling agent
```

---

## 7. API Reference

### 7.1 Auth Router — `/api/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/signup` | None | Creates Clinic + default ModelConfig + admin ClinicUser atomically. Returns JWT. Rejects duplicate email or Twilio number with HTTP 400. |
| POST | `/api/auth/login` | None | Validates email + password. Returns JWT with `clinic_id`, `user_id`, `role`. |
| GET | `/api/auth/me` | Bearer JWT | Returns authenticated user profile + clinic name, Twilio number, timezone, hours. |

### 7.2 Clinic Router — `/api/clinics`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/` | Superadmin | Lists all clinics. |
| GET | `/api/clinics/{clinic_id}` | Admin (own clinic) or Superadmin | Returns clinic detail including Twilio number. |
| PUT | `/api/clinics/{clinic_id}` | Admin (own clinic) or Superadmin | Partial update: name, timezone, open_hour, close_hour. |
| DELETE | `/api/clinics/{clinic_id}` | Superadmin | Soft-delete: sets `is_active=False`. |

### 7.3 Doctor Router — `/api/clinics/{clinic_id}/doctors`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/doctors/` | Admin or Superadmin | Lists active doctors for the clinic. |
| POST | `/api/clinics/{clinic_id}/doctors/` | Admin or Superadmin | Creates a doctor with all scheduling fields. Returns HTTP 201. |
| GET | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | Admin or Superadmin | Fetches a single doctor's full detail. |
| PUT | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | Admin or Superadmin | Partial update of any doctor field. |
| DELETE | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | Admin or Superadmin | Soft-delete: sets `is_active=False`. |

### 7.4 Config Router — `/api/clinics/{clinic_id}/config`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/config/` | Admin or Superadmin | Returns LLM config; API keys shown as boolean presence flags only. Auto-creates default config row if absent. |
| PUT | `/api/clinics/{clinic_id}/config/` | Admin or Superadmin | Updates vendor, model, STT model, and/or API keys (encrypted before storage). |
| POST | `/api/clinics/{clinic_id}/config/test` | Admin or Superadmin | Runs live inference call with saved config. Returns `{success, response, latency_ms}`. |

### 7.5 Patient Router — `/api/clinics/{clinic_id}/patients`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/patients/` | Admin or Superadmin | Paginated list of active patients; optional name/phone search filter; includes record count per patient. |
| GET | `/api/clinics/{clinic_id}/patients/by-phone/{phone_number}` | Admin or Superadmin | Lookup patient by phone number. Declared before `/{patient_id}` to avoid route shadowing. |
| GET | `/api/clinics/{clinic_id}/patients/{patient_id}` | Admin or Superadmin | Full patient detail: all profile fields, allergies, conditions, medications, notes. |
| PUT | `/api/clinics/{clinic_id}/patients/{patient_id}` | Admin or Superadmin | Partial update of any patient profile field. |
| GET | `/api/clinics/{clinic_id}/patients/{patient_id}/records` | Admin or Superadmin | Medical records timeline; optional `?type=consultation` or `?type=lab_report` filter; joins Doctor table for doctor name. |

### 7.6 Webhook Router — `/webhook`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/webhook/twilio` | None | Health check. Returns `{"status": "ok"}`. |
| POST | `/webhook/twilio` | None (Twilio signature — not yet verified) | Main inbound handler. Accepts Form: `From`, `Body`, `NumMedia`, `MediaUrl0`, `MediaContentType0`, `ButtonPayload`. Routes to doctor or patient handler. |

### 7.7 Startup and Middleware

Routers registered in `main.py`:

- **Hard-registered:** `auth_router`, `clinic_router`, `doctor_api_router`, `config_router`, `patient_router`
- **Optionally loaded** (missing modules silently skipped, except `classifier_router` which raises `RuntimeError`): `classifier_router`, `webhook_router`, `parser_router`, `scribe_router`
- **CORS:** `allow_origins` from `DASHBOARD_URL` env var (default `http://localhost:3000`)
- **Startup jobs:** DB table creation, APScheduler start, after-hours flush job, weekly insights job per doctor, optional demo doctor seeding (`SEED_DEMO_DOCTORS=true`)

---

## 8. Deployment

### 8.1 Docker Compose

Four services defined in `docker-compose.yml`:

| Service | Image | Port | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | DB/user/pass: `clinicai`/`clinicai`/`password`. Healthcheck: `pg_isready`. Named volume: `postgres_data`. |
| `redis` | `redis:7-alpine` | 6379 | No auth configured. |
| `api` | Built from root `Dockerfile` | 8000 | Reads `.env` file; env overrides `DATABASE_URL` and `REDIS_URL` for Docker networking. Volume mount: `./generated:/app/generated`. Depends on healthy postgres + started redis. |
| `dashboard` | Built from `./dashboard/Dockerfile` | 3000 | Multi-stage build → standalone Next.js output. `NEXT_PUBLIC_API_URL=http://localhost:8000`. Depends on api. |

**Run commands:**

```bash
# Build and start all services
docker compose up --build

# Start in background
docker compose up --build -d

# View API logs
docker compose logs -f api

# Stop all services
docker compose down

# Wipe database volume
docker compose down -v
```

### 8.2 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Groq API key for LLM + STT |
| `GEMINI_API_KEY` | No | — | Google Gemini API key for fallback LLM |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Default Groq model name |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Default Gemini model name |
| `WHISPER_MODEL` | No | `whisper-large-v3` | Groq Whisper model for STT |
| `TWILIO_ACCOUNT_SID` | Yes | — | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio auth token |
| `SOAP_APPROVAL_CONTENT_SID` | Yes | — | Twilio Content Template SID for doctor approval buttons |
| `APPOINTMENT_APPROVAL_CONTENT_SID` | Yes | — | Twilio Content Template SID for appointment approval |
| `TWILIO_WHATSAPP_FROM` | Yes | — | Twilio WhatsApp sender number (e.g., `whatsapp:+14155238886`) |
| `DOCTOR_WHATSAPP_NUMBERS` | No | — | CSV of `Name:+number` or bare `+number`; env-var doctor registry |
| `CLINIC_NAME` | No | `ClinicAI` | Default clinic display name |
| `SEED_DEMO_DOCTORS` | No | `false` | Seed demo doctor rows into DB on startup |
| `REMINDER_MINUTES_BEFORE` | No | `120` | Minutes before appointment to send reminder |
| `DEMO_REMINDER_DELAY_MINUTES` | No | `2` | Demo mode: reminder fires after N minutes |
| `FOLLOWUP_DEFAULT_DAYS` | No | `2` | Days after consultation to send follow-up |
| `DEMO_FOLLOWUP_DELAY_MINUTES` | No | `3` | Demo mode: follow-up fires after N minutes |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://clinicai:password@localhost:5432/clinicai` | PostgreSQL async connection URL |
| `SECRET_KEY` | Yes | — | JWT signing secret (HS256); use a long random string in production |
| `ENCRYPTION_KEY` | Yes | — | Fernet key for API key encryption; generate with `Fernet.generate_key()` |
| `DASHBOARD_URL` | No | `http://localhost:3000` | Dashboard origin for CORS allow_origins |
| `CLINIC_OPEN_HOUR` | No | `9` | Hour (0-23) when clinic opens; used by AfterHoursAgent |
| `CLINIC_CLOSE_HOUR` | No | `20` | Hour (0-23) when clinic closes |
| `CONSULTATION_TIMEOUT_MINUTES` | No | `30` (2 in demo) | Minutes of inactivity before consultation auto-closes |
| `JAMEEL_SCRIBE_URL` | No | — | External scribe service URL (integration contract; empty = use local scribe) |
| `GOOGLE_CALENDAR_ENABLED` | No | `False` | Enable Google Calendar event creation on booking |
| `GOOGLE_CALENDAR_CREDENTIALS_FILE` | No | `google_credentials.json` | Service account credentials path |
| `GOOGLE_CALENDAR_TOKEN_FILE` | No | `google_token.json` | OAuth token cache path |
| `GOOGLE_CALENDAR_ID` | No | `primary` | Target calendar ID |
| `GOOGLE_CALENDAR_TIMEZONE` | No | `Asia/Kolkata` | Calendar timezone |
| `APPOINTMENT_DURATION_MINUTES` | No | `30` | Default appointment slot length |
| `APPOINTMENT_SLOT_CANDIDATES` | No | — | Pre-defined slot candidates (optional override) |
| `PUBLIC_BASE_URL` | Yes (for Twilio) | — | Public-facing URL for webhook (e.g., ngrok URL in development) |

### 8.3 Local Development Setup

**Prerequisites:** Python 3.12, Node.js 20, Docker, PostgreSQL 16, Redis 7.

**Option A — Docker Compose (recommended):**

```bash
# 1. Copy and populate environment
cp .env.example .env    # (no .env.example exists yet; create .env manually)

# 2. Build and start all services
docker compose up --build

# API available at: http://localhost:8000
# Dashboard available at: http://localhost:3000
# API docs (Swagger): http://localhost:8000/docs
```

**Option B — Manual (API only):**

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Populate .env (DATABASE_URL + REDIS_URL pointing to local services)

# 4. Run API
uvicorn main:app --reload --port 8000
```

**Option C — Dashboard only:**

```bash
cd dashboard
npm install
npm run dev
# Dashboard available at: http://localhost:3000
```

**Database migrations:**

```bash
# Run Alembic migrations (first-time setup)
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "description of change"
```

**Twilio webhook setup (development):**

```bash
# Expose local API via ngrok
ngrok http 8000

# Set PUBLIC_BASE_URL in .env to the ngrok HTTPS URL
# Configure Twilio WhatsApp sandbox webhook URL to:
# https://<ngrok-subdomain>.ngrok.io/webhook/twilio
```

**Running tests:**

```bash
pytest
# Note: pytest is installed but no test files exist yet (see Known Limitations)
```

---

## 9. Known Limitations

The following are tracked technical gaps and deferred work items as of Sprint 4.

1. **APScheduler in-process — no persistent jobstore.** All scheduled jobs (reminders, after-hours flush, weekly insights) are registered in-memory. A server restart drops all pending jobs. Fix: configure APScheduler with a Redis jobstore (`RedisJobStore` via `apscheduler.jobstores.redis`).

2. **LangGraph MemorySaver in RAM — booking sub-state not crash-resilient.** `MemorySaver` checkpoints the RouterAgent and sub-agent state graphs in process memory. If the API server restarts mid-booking, the patient's state machine is lost and they receive a confused response. Fix: replace `MemorySaver` with a Redis or PostgreSQL checkpoint store.

3. **Doctor-side consultation close does not trigger scribe.** The scribe pipeline (SOAP generation, FHIR coding, PDF, MedicalRecord write) only fires when the patient sends a closing phrase or the inactivity timeout fires. If only the doctor closes, the session data is never persisted. Fix: detect `doctor_close` intent in `handle_doctor_message()` and call the scribe pipeline explicitly.

4. **`DOCTOR_WHATSAPP_NUMBERS` env var takes priority over DB doctors.** `identify_sender_async()` checks the env var first; DB lookup is a fallback. This means manually deactivating a doctor in the database does not immediately prevent them from being recognized as a doctor if their number is still in the env var. Fix: remove env-var checking from `identify_sender_async()` or make DB the authoritative source.

5. **No test suite.** `pytest` and `pytest-asyncio` are installed but `D:\ClinicAI` contains zero test files. No unit, integration, or end-to-end tests exist. All validation is manual. Fix: add `tests/` directory with at minimum: model creation tests, `upsert_patient` behavior, `identify_sender` resolution logic, and scribe pipeline unit tests.

6. **No CI/CD pipeline or container health checks.** No GitHub Actions, no pre-commit hooks, no automated build validation. The `docker-compose.yml` has a healthcheck on postgres but not on the `api` or `dashboard` containers. Fix: add GitHub Actions workflow for lint + test on push; add `HEALTHCHECK` instructions to both Dockerfiles.

7. **`clinic_id` not reliably propagated through WhatsApp sessions.** `patient_service.upsert_patient()` requires `clinic_id`, which comes from `resolve_clinic_by_twilio_number(to_number)`. If the `to_number` does not match any `Clinic.twilio_number` in the database (e.g., during single-tenant deployments with only env-var config), clinic resolution returns `None` and patient rows are written without a valid `clinic_id`, breaking foreign key integrity. Fix: enforce clinic resolution at startup or seed a default clinic row matched to `TWILIO_WHATSAPP_FROM`.

---

## 10. Security Notes

The following security properties and gaps apply to the current codebase. Auditors and engineers deploying to production should address all items marked as requiring action.

| Area | Current State | Production Recommendation |
|---|---|---|
| **JWT algorithm** | HS256, 7-day expiry | Use shorter expiry (e.g., 15 minutes) with refresh token rotation. Consider RS256 for multi-service deployments. |
| **JWT secret** | `SECRET_KEY` env var | Use a cryptographically random 256-bit secret. Rotate on compromise. |
| **API key storage** | Fernet (AES-128-CBC) encrypted, stored in `model_configs` table | Current approach is acceptable. Ensure `ENCRYPTION_KEY` is stored in a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault), not in `.env`. |
| **API key exposure** | Config GET returns boolean presence flags only; keys never returned in API responses | Maintain this invariant. Add an audit log for key updates. |
| **WhatsApp webhook auth** | No Twilio request signature validation | Implement Twilio signature verification using `twilio.request_validator.RequestValidator`. Without this, any HTTP client can inject fake WhatsApp messages. |
| **CORS** | `allow_origins=[DASHBOARD_URL]` (env var) | Correct approach. Verify `DASHBOARD_URL` is set to the production domain, not `*`. |
| **Debug endpoints** | `/debug/*` endpoints expose Redis session data | Gate all `/debug/*` routes behind `get_current_superadmin` dependency or remove from production builds. |
| **Password hashing** | bcrypt via passlib | Correct. Ensure `bcrypt==4.0.1` is pinned and audited for known CVEs. |
| **Database credentials** | Hardcoded defaults (`clinicai`/`password`) in `docker-compose.yml` | Replace with secrets injection (Docker secrets or env var overrides). Never commit production credentials. |
| **`.env` file** | Present in repo root; not in `.gitignore` (confirm) | Ensure `.env` is in `.gitignore`. Create `.env.example` with all keys and placeholder values for new developers. |
| **Multi-tenancy isolation** | All API routes check `clinic_id` ownership via `get_current_admin` | Verify every data-access path filters by `clinic_id`. A superadmin can currently access all clinics by design. |
| **HTTPS** | Not configured in Docker Compose or FastAPI | Use a reverse proxy (nginx, Caddy, or AWS ALB) to terminate TLS in production. Never expose the FastAPI server directly on port 8000. |
