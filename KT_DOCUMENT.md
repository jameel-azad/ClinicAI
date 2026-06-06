# ClinicAI — Knowledge Transfer Document

**Project:** ClinicAI  
**Prepared for:** Tech Head  
**Prepared by:** Nabil (Xccelera AI)  
**Date:** June 2026  

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Directory Structure](#3-directory-structure)
4. [Database Schema](#4-database-schema)
5. [REST API Endpoints](#5-rest-api-endpoints)
6. [LangGraph Multi-Agent System](#6-langgraph-multi-agent-system)
7. [SOAP Scribe Pipeline](#7-soap-scribe-pipeline)
8. [Lab Report Parser Pipeline](#8-lab-report-parser-pipeline)
9. [Key Services & Integrations](#9-key-services--integrations)
10. [Session & State Management](#10-session--state-management)
11. [Authentication & Authorization](#11-authentication--authorization)
12. [Environment Variables](#12-environment-variables)
13. [End-to-End Data Flows](#13-end-to-end-data-flows)
14. [Multi-Tenant Architecture](#14-multi-tenant-architecture)
15. [Scheduler (APScheduler)](#15-scheduler-apscheduler)
16. [How to Run Locally](#16-how-to-run-locally)
17. [Known Limitations & Technical Debt](#17-known-limitations--technical-debt)
18. [Debugging Guide](#18-debugging-guide)
19. [Key Files to Read First](#19-key-files-to-read-first)

---

## 1. Project Overview

ClinicAI is a **multi-tenant, WhatsApp-native clinic management system** built on FastAPI and LangGraph. It handles both patient-facing and doctor-facing interactions entirely through WhatsApp, backed by a web management dashboard.

### Core Capabilities

| Capability | Description |
|---|---|
| Patient WhatsApp Bot | Appointment booking, consultation messages, lab report uploads, follow-up queries, emergency detection |
| Doctor WhatsApp Bot | Appointment approvals, SOAP note review/approval, voice-note transcription, weekly insights |
| AI Clinical Scribe | Groq Whisper STT + LLaMA 3.3 70B → S/O/A/P notes with confidence scores |
| Lab Report Parser | PDF → structured extraction of test values, abnormals, criticals, doctor summary |
| Clinical Coding | SNOMED CT diagnosis codes, RxNorm medication codes, HL7 FHIR R4 bundles |
| Web Dashboard | Next.js admin panel for clinic/patient/doctor management and AI model configuration |
| Automated Scheduling | Appointment reminders, consultation timeouts, after-hours queuing, weekly doctor insights |

---

## 2. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| API Framework | FastAPI | 0.115 |
| Agent Orchestration | LangGraph | 0.3 |
| ORM | SQLAlchemy | 2.0 (async) |
| DB Driver | asyncpg | latest |
| Database | PostgreSQL | 16 |
| Cache / Session Store | Redis | 7 |
| Primary LLM | Groq LLaMA 3.3 70B | `llama-3.3-70b-versatile` |
| Fallback LLM | Google Gemini 2.5 Flash | `gemini-2.5-flash` |
| STT | Groq Whisper | `whisper-large-v3` |
| PDF Generation | ReportLab | latest |
| PDF Parsing | pdfplumber | latest |
| Messaging | Twilio WhatsApp API | — |
| Task Scheduler | APScheduler | 3.10 |
| Auth | JWT (HS256) + passlib bcrypt | — |
| Encryption | Fernet (cryptography) | — |
| Dashboard | Next.js | separate deployment |
| Database Migrations | Alembic | latest |

---

## 3. Directory Structure

```
D:\ClinicAI
├── main.py                        # FastAPI app entrypoint, lifespan hooks, health check
├── requirements.txt               # All Python dependencies
├── docker-compose.yml             # PostgreSQL, Redis, FastAPI, Next.js (full stack)
├── Dockerfile                     # Docker build for FastAPI backend
├── dev_start.py                   # Local dev: auto-ngrok, .env writer, uvicorn launcher
├── alembic.ini                    # Database migration config
├── .env                           # Environment variables (API keys, DB URL, Twilio creds)
│
├── alembic/                       # Database migrations
│   ├── env.py
│   └── versions/
│       └── 001_add_google_calendar_id_to_doctors.py
│
├── app/                           # Main application package
│   ├── database.py                # AsyncSessionLocal, engine setup
│   │
│   ├── core/                      # Auth & security
│   │   ├── deps.py                # FastAPI dependencies (get_db, get_current_user, get_current_admin, get_current_superadmin)
│   │   └── security.py            # JWT create/verify, password hashing
│   │
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── clinic.py              # Clinic
│   │   ├── user.py                # ClinicUser
│   │   ├── doctor.py              # Doctor
│   │   ├── patient.py             # Patient
│   │   ├── medical_record.py      # MedicalRecord
│   │   └── model_config.py        # ModelConfig (per-clinic AI settings)
│   │
│   ├── prompts/                   # LLM system prompts (externalized from business logic)
│   │   └── parser.py              # Lab report parsing prompts
│   │
│   ├── api/                       # FastAPI routers
│   │   ├── auth_router.py         # POST /api/auth/signup, /login; GET /me
│   │   ├── clinic_router.py       # CRUD /api/clinics
│   │   ├── doctor_api_router.py   # CRUD /api/clinics/{id}/doctors
│   │   ├── patient_router.py      # CRUD /api/clinics/{id}/patients + records timeline
│   │   ├── config_router.py       # GET/PUT /api/clinics/{id}/config + test
│   │   ├── classifier_router.py   # POST /classify (direct intent test)
│   │   ├── parser_router.py       # POST /parser/parse-report (lab PDF)
│   │   ├── scribe_router.py       # POST /scribe/consult (Jameel integration)
│   │   └── webhook_router.py      # POST /webhook/twilio + debug endpoints
│   │
│   ├── graph/                     # LangGraph agent graphs
│   │   ├── classifier.py          # Intent classifier graph
│   │   ├── router.py              # Top-level router (main WhatsApp entry point)
│   │   ├── booking.py             # Backward-compat shim → router_graph
│   │   │
│   │   ├── agents/                # Sub-agent graphs
│   │   │   ├── booking_agent.py   # Appointment booking/cancel/reschedule/status
│   │   │   ├── consultation_agent.py  # Active consultation buffer + closing detection
│   │   │   ├── emergency_agent.py # Emergency alert → 112 instructions
│   │   │   ├── lab_agent.py       # Lab report share (text; PDF handled in webhook)
│   │   │   ├── followup_agent.py  # Follow-up queries, prescription requests
│   │   │   └── after_hours_agent.py   # After-hours queuing
│   │   │
│   │   ├── scribe/                # SOAP generation pipeline (Jameel integration)
│   │   │   ├── state.py           # ScribeState TypedDict
│   │   │   ├── pipeline.py        # LangGraph: 7 nodes (transcribe → PDF output)
│   │   │   ├── nodes.py           # Node implementations
│   │   │   └── pdf_builder.py     # ReportLab SOAP PDF generation
│   │   │
│   │   └── parser/                # Lab report parsing pipeline
│   │       ├── state.py           # ReportState TypedDict
│   │       ├── pipeline.py        # LangGraph: 4 nodes (extract → summary)
│   │       └── nodes.py           # Node implementations
│   │
│   └── services/                  # Business logic & third-party integrations
│       ├── llm_factory.py         # Fernet encryption, LLM vendor factory, connectivity test
│       ├── store.py               # Redis session store (with in-memory fallback)
│       ├── identity.py            # Doctor identification from phone number
│       ├── doctor.py              # Doctor message handler (approvals, setup, lab review)
│       ├── doctor_directory.py    # Doctor profile management in store
│       ├── doctor_setup.py        # Doctor WhatsApp onboarding flow
│       ├── patient_service.py     # Patient CRUD, medical record persistence
│       ├── appointment_approval.py    # Doctor approval request/response workflow
│       ├── soap_approval.py       # SOAP note approval workflow
│       ├── consultation_service.py    # Finalize consultation, call Jameel API
│       ├── scribe_service.py      # Local SOAP pipeline (Jameel fallback)
│       ├── whatsapp.py            # Twilio: send_message, send_document, download_media
│       ├── pdf_service.py         # Lab PDF storage & serving
│       ├── clinical_scribe.py     # Doctor voice-note standalone scribe
│       ├── google_calendar.py     # Google Calendar availability & event creation
│       ├── scheduler.py           # APScheduler jobs (reminders, timeouts, insights)
│       ├── terminology.py         # SNOMED CT / RxNorm coding
│       └── async_runner.py        # Run async functions from sync contexts
│
├── scripts/
│   ├── flush_db.py                # Clear all DB tables (dev reset)
│   └── google_calendar_auth.py    # Google OAuth flow
│
├── dashboard/                     # Next.js management dashboard
├── generated/                     # Generated files
│   ├── lab_pdfs/
│   ├── soap_pdfs/
│   └── transcripts/
└── data/                          # Local data storage
```

---

## 4. Database Schema

All tables use UUID string primary keys and UTC-aware `created_at` timestamps.

### `clinics` — Multi-tenant root

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String | |
| `twilio_number` | String (unique) | WhatsApp number for this clinic |
| `timezone` | String | Default: `Asia/Kolkata` |
| `open_hour` | Integer | Default: 9 |
| `close_hour` | Integer | Default: 18 |
| `is_active` | Boolean | Soft delete |
| `created_at` | DateTime | |

### `clinic_users` — Dashboard authentication

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | String (unique, indexed) | |
| `hashed_password` | String | bcrypt |
| `full_name` | String | |
| `role` | Enum | `admin` \| `superadmin` |
| `clinic_id` | UUID FK → clinics | |
| `is_active` | Boolean | |
| `created_at` | DateTime | |

### `doctors` — Per-clinic doctor profiles

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK (indexed) | |
| `name` | String | |
| `specialty` | String | |
| `whatsapp_number` | String | |
| `working_hours_start` | Integer | Default: 9 |
| `working_hours_end` | Integer | Default: 18 |
| `appointment_duration_minutes` | Integer | Default: 30 |
| `buffer_minutes` | Integer | Default: 5 |
| `google_calendar_id` | String | Optional |
| `is_active` | Boolean | Soft delete |
| `created_at` | DateTime | |
| **Unique constraint** | | `(clinic_id, whatsapp_number)` |

### `model_configs` — Per-clinic AI model settings

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK (unique) | One config per clinic |
| `llm_vendor` | Enum | `groq` \| `anthropic` \| `openai` \| `google` |
| `llm_model` | String | Default: `llama-3.3-70b-versatile` |
| `stt_vendor` | String | Default: `groq` |
| `stt_model` | String | Default: `whisper-large-v3-turbo` |
| `groq_api_key_enc` | String | Fernet-encrypted, nullable |
| `anthropic_api_key_enc` | String | Fernet-encrypted, nullable |
| `openai_api_key_enc` | String | Fernet-encrypted, nullable |
| `google_api_key_enc` | String | Fernet-encrypted, nullable |
| `updated_at` | DateTime | Auto-updated |

### `patients` — Per-clinic patient profiles

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK (indexed) | |
| `phone_number` | String (indexed) | E.164 format |
| `name` | String | nullable |
| `age` | Integer | |
| `gender` | Enum | `male` \| `female` \| `other` |
| `blood_group` | String | |
| `allergies` | JSON | Array of strings |
| `chronic_conditions` | JSON | Array of strings |
| `current_medications` | JSON | Array of strings |
| `doctor_notes` | String (2000) | Free-text clinical notes |
| `is_active` | Boolean | |
| `created_at` | DateTime | |
| `last_visit_at` | DateTime | Nullable; updated per consultation |
| **Unique constraint** | | `(clinic_id, phone_number)` |

### `medical_records` — Consultation & lab history

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `patient_id` | UUID FK (indexed) | |
| `clinic_id` | UUID FK (indexed) | |
| `doctor_id` | UUID FK (indexed, nullable) | |
| `visit_date` | DateTime (indexed) | |
| `record_type` | Enum | `consultation` \| `lab_report` \| `booking` |
| `chief_complaint` | String | |
| `soap_subjective` | Text | S section |
| `soap_objective` | Text | O section |
| `soap_assessment` | Text | A section |
| `soap_plan` | Text | P section |
| `soap_confidence` | Float | 0.0–1.0 |
| `diagnoses` | JSON | `[{name, snomed_code, severity}]` |
| `medications` | JSON | `[{name, rxnorm_code, frequency}]` |
| `symptoms` | JSON | `[{name, severity, duration}]` |
| `lab_panel_type` | String | `CBC \| LFT \| KFT \| LIPID \| THYROID \| MIXED \| UNKNOWN` |
| `lab_results` | JSON | `{all_values, abnormals, criticals}` |
| `fhir_bundle` | JSON | HL7 FHIR R4 Bundle |
| `pdf_url` | String | |
| `created_at` | DateTime | |

---

## 5. REST API Endpoints

### Authentication — `/api/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/signup` | None | Create clinic + admin user + ModelConfig atomically; returns JWT |
| POST | `/api/auth/login` | None | Email/password → JWT (7-day expiry) |
| GET | `/api/auth/me` | JWT | Current user profile + clinic details |

### Clinic Management — `/api/clinics`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/` | superadmin | List all clinics |
| GET | `/api/clinics/{clinic_id}` | admin or superadmin | Clinic detail |
| PUT | `/api/clinics/{clinic_id}` | admin or superadmin | Update name, timezone, hours |
| DELETE | `/api/clinics/{clinic_id}` | superadmin | Soft-delete |

### Doctor Management — `/api/clinics/{clinic_id}/doctors`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/doctors/` | admin | List active doctors |
| POST | `/api/clinics/{clinic_id}/doctors/` | admin | Create doctor |
| GET | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | admin | Doctor detail |
| PUT | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | admin | Update doctor |
| DELETE | `/api/clinics/{clinic_id}/doctors/{doctor_id}` | admin | Soft-delete |

### Patient Management — `/api/clinics/{clinic_id}/patients`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/patients/` | admin | Paginated list; optional `?search=` by name/phone |
| GET | `/api/clinics/{clinic_id}/patients/by-phone/{phone}` | admin | Lookup by phone number |
| GET | `/api/clinics/{clinic_id}/patients/{patient_id}` | admin | Full patient profile |
| PUT | `/api/clinics/{clinic_id}/patients/{patient_id}` | admin | Update patient fields |
| GET | `/api/clinics/{clinic_id}/patients/{patient_id}/records` | admin | Medical records timeline; optional `?type=` filter |

### AI Model Configuration — `/api/clinics/{clinic_id}/config`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/clinics/{clinic_id}/config/` | admin | Current config (API keys returned as booleans, never plaintext) |
| PUT | `/api/clinics/{clinic_id}/config/` | admin | Update vendor, model, STT, API keys (Fernet-encrypted before save) |
| POST | `/api/clinics/{clinic_id}/config/test` | admin | Test LLM connectivity; returns `latency_ms` |

### Intent Classifier — `/classify`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/classify` | None | Direct intent classification test; returns intent, confidence, entities, bot_response |

### Lab Report Parser — `/parser`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/parser/health` | None | Parser health check |
| POST | `/parser/parse-report` | None | PDF upload → structured extraction |

### Clinical Scribe — `/scribe`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/scribe/consult` | None | Consultation bundle → SOAP result (Jameel API endpoint) |
| GET | `/scribe/pdf/{document_id}` | None | Serve generated SOAP PDF |

### WhatsApp Webhook — `/webhook`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/webhook/twilio` | Twilio signature | Main Twilio inbound handler (all WhatsApp traffic) |
| GET | `/webhook/twilio` | None | Webhook health check |
| GET | `/lab-report/pdf/{document_id}` | None | Serve lab report PDF |
| GET | `/debug/sessions` | Debug auth | All booking sessions |
| GET | `/debug/appointments` | Debug auth | All confirmed appointments |
| GET | `/debug/identity` | Debug auth | Configured doctor numbers |
| GET | `/debug/pending-approvals` | Debug auth | Pending doctor approvals |
| GET | `/debug/doctors` | Debug auth | Saved doctor profiles |
| GET | `/debug/consultations` | Debug auth | Active consultations |

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check + feature flags |
| GET | `/health` | Alias for `/` |
| GET | `/graph/nodes` | Graph node registry (testing) |

---

## 6. LangGraph Multi-Agent System

### Graph Hierarchy

```
CLASSIFIER GRAPH
    validate → preprocess → classify (Groq) → [fallback: Gemini] → postprocess
    Input: raw_message + clinic context
    Output: intent, confidence, entities, bot_response, all_intents

ROUTER GRAPH  (top-level orchestrator, one instance per clinic)
    after_hours_check → intent_node → session_node → dispatch
    MemorySaver checkpoint per patient (thread_id = phone_number)

    Sub-agents (dispatched from router):
    ├── BOOKING AGENT
    │   Intents: appointment_book, appointment_cancel, appointment_reschedule,
    │             appointment_status, general_query
    │   States: GREETING → NAME_COLLECTION → DATE_COLLECTION → TIME_COLLECTION
    │            → DOCTOR_SELECTION → CONFIRMATION → DOCTOR_APPROVAL_PENDING → CONFIRMED
    │   Integrations: Google Calendar slots, appointment_approval, APScheduler reminders
    │
    ├── CONSULTATION AGENT
    │   Intents: consultation_message OR journey_state=CONSULTATION_ACTIVE
    │   Buffers patient messages → ConsultationSession (Redis)
    │   Detects closing phrases (ok done, bye, khatam, take care...)
    │   On close: build bundle → POST to Jameel/local scribe → SOAP PDF → doctor WhatsApp
    │
    ├── LAB AGENT
    │   Intent: lab_report_share (text-only; PDFs handled directly in webhook)
    │   Action: prompt patient to send the PDF as WhatsApp attachment
    │
    ├── FOLLOWUP AGENT
    │   Intents: followup_query, prescription_request
    │   Also triggered for: journey_state ∈ {POST_CONSULT, FOLLOW_UP_PENDING}
    │   Access: previous SOAP, follow-up questions, medication history
    │
    ├── EMERGENCY AGENT
    │   Intent: emergency
    │   Actions: alert ALL doctors via WhatsApp, return 112 instructions to patient, clear session
    │
    └── AFTER_HOURS AGENT
        Pre-router check: if clinic closed → queue message in Redis → return ack
        Re-inject queued messages at open_hour via APScheduler flush job
```

### Classifier Graph — Node Detail

| Node | Responsibility |
|---|---|
| `validate_node` | Non-empty, <2000 chars |
| `preprocess_node` | Collapse whitespace, normalize unicode quotes |
| `classify_node` | Groq LLaMA 3.3 70B with system prompt + few-shot |
| `fallback_node` | If Groq fails → Gemini 2.5 Flash |
| `postprocess_node` | Set `is_emergency` flag if intent=emergency |
| `error_node` | Validation failure fallback |

### Recognized Intents

```
appointment_book       appointment_cancel      appointment_reschedule
appointment_status     consultation_message    lab_report_share
followup_query         prescription_request    emergency
general_query          greeting               after_hours
```

---

## 7. SOAP Scribe Pipeline

**Location:** `app/graph/scribe/pipeline.py`

**Entry:** `scribe_pipeline.invoke(ScribeState(...))`

### Pipeline Nodes (LangGraph)

```
transcribe_node
    ↓
soap_generator_node
    ↓
extract_entities_node
    ↓
fhir_coding_node
    ↓
grounding_check_node
    ↓
followup_generator_node
    ↓
pdf_output_node
```

| Node | Description |
|---|---|
| `transcribe_node` | Download audio from Twilio URLs → Groq Whisper large-v3 transcription |
| `soap_generator_node` | LLaMA 3.3 70B: transcript → S/O/A/P sections + per-section confidence 0–1 |
| `extract_entities_node` | Extract symptoms, diagnoses, medications as structured JSON with severity/frequency |
| `fhir_coding_node` | Map diagnoses → SNOMED CT codes; medications → RxNorm codes; build HL7 FHIR R4 Bundle |
| `grounding_check_node` | Verify SOAP statements are grounded in transcript; warn on ungrounded sections |
| `followup_generator_node` | Generate 2–3 patient-appropriate follow-up questions |
| `pdf_output_node` | ReportLab: SOAP PDF with confidence scores, diagnosis chips, medication chips, follow-up Qs |

### ScribeState Fields (TypedDict)

```python
transcript: str                   # Combined text + transcribed audio
audio_files: List[str]           # Twilio audio URLs
soap_subjective: str
soap_objective: str
soap_assessment: str
soap_plan: str
soap_confidence: Dict[str, float] # Per-section confidence
symptoms: List[dict]
diagnoses: List[dict]
medications: List[dict]
fhir_bundle: dict                 # HL7 FHIR R4 JSON
grounding_issues: List[str]
follow_up_questions: List[str]
soap_note_pdf_url: str
summary_for_whatsapp: str         # <300 chars for doctor WhatsApp
missing_sections: List[str]
```

### Outputs

- **`soap_note_pdf_url`** — Stored in `generated/soap_pdfs/`
- **`fhir_bundle`** — Stored in `MedicalRecord.fhir_bundle`
- **`summary_for_whatsapp`** — Sent to doctor via WhatsApp (<300 chars)
- **`follow_up_questions`** — Stored in `BookingSession` for future reference

---

## 8. Lab Report Parser Pipeline

**Location:** `app/graph/parser/pipeline.py`

**Entry:** `lab_report_pipeline.invoke(ReportState(...))`

### Pipeline Nodes

```
extract_text_node
    ↓
extract_all_node
    ↓
flag_abnormals_node
    ↓
generate_summary_node
```

| Node | Description |
|---|---|
| `extract_text_node` | pdfplumber to read PDF pages; Tesseract OCR fallback |
| `extract_all_node` | LLaMA 3.3 70B: parse demographics, all test parameters, detect panel type |
| `flag_abnormals_node` | Identify HIGH/LOW; flag CRITICAL by medical thresholds (Hb <7, TSH >100, K+ >6.5, etc.) |
| `generate_summary_node` | LLaMA: 3–5 sentence plain-English doctor summary |

### Detected Panel Types

`CBC | LFT | KFT | LIPID | THYROID | MIXED | UNKNOWN`

### ReportState Outputs

```python
patient_info: dict        # name, age, gender, DOB, lab name, report date, referring doctor
all_values: List[dict]    # All test rows with units, reference ranges, status
abnormals: List[dict]     # HIGH/LOW flagged subset
criticals: List[dict]     # CRITICAL threshold subset
doctor_summary: str       # Plain-text summary
```

---

## 9. Key Services & Integrations

### `app/services/llm_factory.py`

- **Fernet encryption/decryption** for per-clinic API keys stored in `ModelConfig`
- `get_llm_for_vendor(vendor, model, api_key)` → LangChain `BaseChatModel`
- Supported vendors: `groq`, `anthropic`, `openai`, `google`
- `test_llm_connection(llm)` → `{success, latency_ms, error}`

### `app/services/store.py` — Redis Session Store

Primary store: Redis. Falls back to in-memory dict (with printed warning) if Redis unavailable.

**Key schema** (all prefixed `clinicai:`):

| Key Pattern | TTL | Contents |
|---|---|---|
| `session:{phone}` | 24h | `BookingSession` JSON |
| `appt:{id}` | None | `AppointmentRecord` JSON |
| `appts_by_phone:{phone}` | None | Redis SET of appointment IDs |
| `approval:{id}` | None | Approval dict |
| `doctor_profile:{phone}` | None | Doctor profile dict |
| `consultation:{patient_phone}` | 4h | `ConsultationSession` JSON |
| `last_active:{phone}` | 7d | ISO timestamp |
| `after_hours_queue:{clinic_id}` | None | Redis LIST of queued messages |

### `app/services/identity.py` — Sender Identification

```
normalize_whatsapp_number()  →  Strip "whatsapp:" prefix, normalize to E.164

identify_sender(from_number) → SenderIdentity(phone_number, role, display_name)
    Lookup priority:
    1. env DOCTOR_WHATSAPP_NUMBERS (CSV: "Name:+91...,+91...")
    2. DB Doctor cache (refreshed on CRUD)
    3. Default: role=patient
```

### `app/services/whatsapp.py` — Twilio Integration

```python
send_whatsapp_message_async(to, body)           # Send text message
send_whatsapp_document_async(to, media_url, caption)  # Send PDF/media
send_whatsapp_interactive_buttons(to, body, buttons)  # Buttons (sandbox: bullet list)
download_media_bytes(media_url)                 # Download Twilio media (Basic Auth)
```

### `app/services/appointment_approval.py`

```
request_doctor_approval(appointment_id, patient_name, date, time, doctor_number)
    → Send WhatsApp to doctor with Approve/Reject/Suggest buttons

handle_appointment_button_reply(from_number, message_body)
    → Parse "YES APT{id}" / "NO APT{id}" / "SUGGEST {time}" from doctor

request_suggested_slot_approval(patient_number, suggested_time)
    → Doctor suggests alternate; patient confirms
```

### `app/services/soap_approval.py`

```
request_soap_approval(doctor_number, soap_pdf_url, consultation_id)
    → Send SOAP PDF to doctor with Approve/Reject buttons (Twilio Content Template)

handle_soap_approval_reply(from_number, message_body)
    → Parse "APPROVE RX{id}" / "REJECT RX{id}"
    → On approve: store MedicalRecord, notify patient
```

### `app/services/consultation_service.py`

```
build_consultation_bundle(ConsultationSession) → dict   # Jameel API format
_call_jameel(bundle) → scribe_result                    # POST to JAMEEL_SCRIBE_URL
finalize_and_send(patient_phone):
    1. Load ConsultationSession from Redis
    2. Call Jameel API (or local scribe if JAMEEL_SCRIBE_URL empty)
    3. Send summary_for_whatsapp to doctor
    4. Update BookingSession: journey_state=POST_CONSULT, store follow_up_questions
    5. Delete ConsultationSession from Redis
```

### `app/services/google_calendar.py` (Optional)

```
check_google_availability(doctor_id, date)  → List[datetime]
suggest_google_slots(doctor_id, date)       → List[str] (formatted time strings)
create_google_calendar_event(doctor_id, patient_name, datetime, duration)
```

OAuth setup: `scripts/google_calendar_auth.py` (initial token exchange only).

### `app/services/terminology.py` — Clinical Coding

- **SNOMED CT**: local `snomed_mappings.json` first; fallback to NLM API
- **RxNorm**: local `rxnorm_mappings.json`
- Called from `fhir_coding_node` in scribe pipeline

### `app/services/scheduler.py` — APScheduler Jobs

See [Section 15](#15-scheduler-apscheduler) for full detail.

---

## 10. Session & State Management

### BookingSession (Redis, TTL 24h)

Key: `clinicai:session:{phone_number}`

```python
from_number: str           # Patient phone (E.164)
clinic_id: str
state: str                 # FSM state (GREETING, NAME_COLLECTION, DATE_COLLECTION, ...)
patient_name: str
requested_date: str
requested_time: str
selected_doctor_id: str
last_bot_response: str     # Context for next intent classification
journey_state: str         # NEW_PATIENT | CONSULTATION_ACTIVE | POST_CONSULT | FOLLOW_UP_PENDING
follow_up_questions: List[str]
```

### ConsultationSession (Redis, TTL 4h)

Key: `clinicai:consultation:{patient_phone}`

```python
consultation_id: str       # CONS######
patient_number: str
doctor_number: str
doctor_name: str
messages: List[ConsultationMessage]   # {role, content, timestamp, message_type}
audio_files: List[str]    # Twilio audio URLs
is_active: bool
started_at: str
last_activity_at: str      # Used for timeout detection
```

### LangGraph MemorySaver

- One checkpoint per patient (thread_id = phone_number)
- Persists booking sub-graph state between messages
- **Limitation:** In-RAM only; lost on server restart (should migrate to RedisSaver)

---

## 11. Authentication & Authorization

### JWT-based Dashboard Auth

```
POST /api/auth/login
    Email + bcrypt password check
    → JWT (HS256, signed with SECRET_KEY, 7-day expiry)
    → Payload: {sub: user_id, clinic_id, role, exp}

GET protected routes
    → Authorization: Bearer <token>
    → Dependency chain:
        get_current_user(token) → ClinicUser from DB
        get_current_admin(user) → assert role ∈ {admin, superadmin}
        get_current_superadmin(user) → assert role == superadmin
```

### Clinic-Level Access Control

- Admin users can only access endpoints for their own `clinic_id`
- Superadmin can list/update/delete all clinics
- Cross-clinic access is blocked at the dependency level (not application-level guards)

### API Key Encryption

```
Write path:  plaintext_key → Fernet.encrypt() → stored in ModelConfig.*_key_enc
Read path:   ModelConfig.*_key_enc → Fernet.decrypt() → passed to llm_factory
API response: API keys never returned plaintext; config GET returns {groq_key_set: true/false}
Key source:  ENCRYPTION_KEY env var (Fernet-compatible base64, 32 bytes)
             Derived from SECRET_KEY if not explicitly set
```

### WhatsApp Role Detection

No cryptographic auth on WhatsApp side. Role is inferred from phone number:

1. Match against `DOCTOR_WHATSAPP_NUMBERS` env var (CSV)
2. Match against Doctor records in DB cache
3. Default: `role=patient`

---

## 12. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Groq API key (LLaMA + Whisper) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq LLM model |
| `WHISPER_MODEL` | No | `whisper-large-v3` | Groq STT model |
| `GEMINI_API_KEY` | Recommended | — | Google Gemini (classifier fallback) |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Google Gemini model |
| `TWILIO_ACCOUNT_SID` | **Yes** | — | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | **Yes** | — | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | **Yes** | — | Sender number e.g. `whatsapp:+14155238886` |
| `SOAP_APPROVAL_CONTENT_SID` | No | — | Twilio Content Template SID for SOAP approval buttons |
| `APPOINTMENT_APPROVAL_CONTENT_SID` | No | — | Twilio Content Template SID for appointment buttons |
| `DOCTOR_WHATSAPP_NUMBERS` | **Yes** | — | CSV e.g. `"Dr.Ali:+91980...,+91901..."` |
| `DATABASE_URL` | **Yes** | — | PostgreSQL async URL `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | **Yes** | `redis://localhost:6379` | Redis connection string |
| `SECRET_KEY` | **Yes** | (insecure default) | JWT signing key (min 32 chars) |
| `ENCRYPTION_KEY` | **Yes** | (derived from SECRET_KEY) | Fernet key for API key encryption |
| `PUBLIC_BASE_URL` | **Yes** | — | Publicly reachable base URL (auto-written by `dev_start.py`) |
| `DASHBOARD_URL` | No | `http://localhost:3000` | Dashboard origin for CORS |
| `CLINIC_NAME` | No | `ClinicAI` | Default clinic name |
| `CLINIC_OPEN_HOUR` | No | `9` | Clinic opening hour (24h) |
| `CLINIC_CLOSE_HOUR` | No | `20` | Clinic closing hour (24h) |
| `GOOGLE_CALENDAR_TIMEZONE` | No | `Asia/Kolkata` | Timezone for calendar & scheduler |
| `REMINDER_MINUTES_BEFORE` | No | `120` | Minutes before appointment for reminder (use `2` for demo) |
| `CONSULTATION_TIMEOUT_MINUTES` | No | `30` | Inactivity before consultation auto-closes (use `2` for demo) |
| `FOLLOWUP_DEFAULT_DAYS` | No | `2` | Days after consultation to send follow-up reminder |
| `JAMEEL_SCRIBE_URL` | No | (empty) | Remote scribe API URL; empty = use local scribe pipeline |
| `GOOGLE_CALENDAR_ENABLED` | No | `False` | Enable Google Calendar integration |
| `GOOGLE_CALENDAR_CREDENTIALS_FILE` | No | `google_credentials.json` | OAuth credentials path |
| `GOOGLE_CALENDAR_TOKEN_FILE` | No | `google_token.json` | OAuth token cache path |
| `GOOGLE_CALENDAR_ID` | No | `primary` | Google Calendar ID |
| `APPOINTMENT_DURATION_MINUTES` | No | `30` | Default appointment slot length |
| `SEED_DEMO_DOCTORS` | No | `false` | Seed demo doctor records on startup |
| `DEBUG_ENDPOINTS` | No | `false` | Enable unauthenticated debug routes (**NEVER in production**) |
| `DISABLE_SCHEDULER` | No | `false` | Disable APScheduler (set true on all but one worker in multi-worker deployment) |

---

## 13. End-to-End Data Flows

### Flow A: Patient Appointment Booking

```
1. Patient sends WhatsApp message
        ↓
2. POST /webhook/twilio (Twilio → ngrok → FastAPI)
        ↓
3. identify_sender() → role=patient, phone=+91...
        ↓
4. Router graph:
     after_hours_check → within hours? YES
     intent_node → classifier → intent=appointment_book
     session_node → load/create BookingSession from Redis
     dispatch → booking_agent_graph
        ↓
5. Booking agent (multi-turn):
     GREETING → collect name → collect date → collect time → select doctor → confirm
        ↓
6. request_doctor_approval() → WhatsApp to doctor (Approve/Reject/Suggest)
        ↓
7. Doctor replies "YES APT123"
     handle_appointment_button_reply() → save AppointmentRecord → confirm to patient
        ↓
8. schedule_reminder() → APScheduler job at (appointment_time - 120min)
        ↓ (at reminder time)
9. send_whatsapp_message_async(patient, "Reminder: appointment in 2 hours")
```

### Flow B: Consultation + SOAP Generation

```
1. Patient sends consultation messages over WhatsApp
        ↓
2. Router → intent=consultation_message → consultation_agent
     Append each message to ConsultationSession (Redis)
        ↓
3. Patient sends closing phrase: "ok done" / "bye" / "khatam"
        ↓
4. consultation_agent detects closing → finalize_and_send()
        ↓
5. build_consultation_bundle() → format for Jameel/local scribe
        ↓
6. If JAMEEL_SCRIBE_URL set → POST to Jameel API
   Else → scribe_service.process_consultation_bundle():
     a. Download/transcribe audio (Groq Whisper)
     b. Build combined transcript
     c. Run scribe_pipeline:
        transcribe → SOAP LLM → extract_entities → fhir_coding
        → grounding_check → followup_generator → pdf_output
        ↓
7. SOAP PDF generated → stored in generated/soap_pdfs/
        ↓
8. soap_approval.request_soap_approval() → PDF + buttons to doctor
        ↓
9. Doctor taps Approve → handle_soap_approval_reply()
     → INSERT MedicalRecord (PostgreSQL) with SOAP, FHIR, PDF URL
     → Update patient.last_visit_at
     → Send summary to patient
        ↓
10. Update BookingSession → journey_state=POST_CONSULT
    Delete ConsultationSession from Redis
```

### Flow C: Lab Report Upload

```
1. Patient sends PDF via WhatsApp
        ↓
2. Webhook detects MediaContentType=application/pdf
   download_media_bytes(MediaUrl0) → PDF bytes
        ↓
3. lab_report_pipeline.invoke():
     extract_text → extract_all → flag_abnormals → generate_summary
        ↓
4. Store PDF → generated/lab_pdfs/
   Register in Redis → MedicalRecord (lab_report type)
        ↓
5. send_whatsapp_document(doctor_number, pdf_url, doctor_summary)
        ↓
6. Doctor reviews. (Doctor can reply to add notes to patient record)
```

### Flow D: Doctor Voice-Note Scribe (Standalone)

```
1. Doctor sends audio note via WhatsApp
        ↓
2. Webhook detects sender=doctor, MediaContentType=audio/*
        ↓
3. clinical_scribe.handle_doctor_voice_note():
     a. Download + transcribe audio (Groq Whisper)
     b. Extract doctor name + patient name from context (last confirmed appointment)
     c. Run scribe_pipeline (same as consultation SOAP)
        ↓
4. SOAP PDF generated
        ↓
5. Send PDF + Approve/Reject buttons to doctor
        ↓
6. Doctor approves → forward SOAP summary to patient + INSERT MedicalRecord
```

### Flow E: After-Hours Message Queuing

```
1. Patient sends message outside clinic hours (e.g., 11 PM)
        ↓
2. after_hours_check_node detects closed → queue message in Redis list
   "clinicai:after_hours_queue:{clinic_id}"
        ↓
3. Reply to patient: "Clinic is closed. Message queued for morning."
        ↓ (at CLINIC_OPEN_HOUR next day)
4. APScheduler flush job runs:
     Pop all queued messages → re-inject into router graph
     Process as if received at opening time
```

---

## 14. Multi-Tenant Architecture

Each clinic is a completely isolated tenant:

```
Clinic A (Twilio: +1-415-XXXX)     Clinic B (Twilio: +1-415-YYYY)
────────────────────────────        ────────────────────────────
Twilio routes by From number         Twilio routes by From number
Clinic A doctors                     Clinic B doctors
Clinic A patients                    Clinic B patients
Clinic A ModelConfig (own keys)      Clinic B ModelConfig (own keys)
Clinic A sessions (keyed by phone    Clinic B sessions (same isolation)
  + clinic_id in session dict)
Clinic A medical records             Clinic B medical records
```

**Isolation points:**
- All DB queries include `WHERE clinic_id = ?`
- Sessions include `clinic_id` field; cross-clinic session collision prevented by unique phone+clinic
- Doctor phone numbers resolved per-clinic (DB lookup scoped to clinic)
- `ModelConfig` unique per clinic; each clinic can use different LLM vendor/model/API key

---

## 15. Scheduler (APScheduler)

**Location:** `app/services/scheduler.py`

**Backend:** APScheduler 3.10 with async executor. Persistent job store uses SQL if available, SQLite fallback.

**Important:** Only run on one worker in multi-worker deployments (set `DISABLE_SCHEDULER=true` on others).

### Registered Jobs

| Job | Trigger | Description |
|---|---|---|
| `appointment_reminder_{id}` | One-shot at `appointment_time - REMINDER_MINUTES_BEFORE` | WhatsApp reminder to patient |
| `consultation_timeout_{phone}` | One-shot at `last_activity + CONSULTATION_TIMEOUT_MINUTES` | Auto-close inactive consultation → finalize_and_send() |
| `afterhours_flush_{clinic_id}` | Daily at `open_hour:00` | Re-inject queued after-hours messages |
| `weekly_insights_{doctor_id}` | Every Monday 08:00 IST | Send doctor 7-day summary (appointments, no-show rate, busiest slot, top complaints) |

### Natural Language Date Resolution

`_resolve_appointment_datetime()` parses patient-provided dates:
- "kal" / "tomorrow" → next day
- "parso" → day after tomorrow
- "15th May" → May 15 of current/next year
- "Monday" → next Monday
- ISO date strings

---

## 16. How to Run Locally

### Option A: Full Docker Compose

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env: set GROQ_API_KEY, TWILIO_*, DOCTOR_WHATSAPP_NUMBERS, etc.

# 2. Start all services
docker compose up --build

# Access:
# API docs:  http://localhost:8000/docs
# Dashboard: http://localhost:3000
```

### Option B: Local Development (Recommended)

```bash
# 1. Start only data services
docker compose up postgres redis -d

# 2. Create and activate Python virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Run database migrations
alembic upgrade head

# 6. Start API server
uvicorn main:app --reload --port 8000

# 7. Start Next.js dashboard (separate terminal)
cd dashboard
npm install
npm run dev

# 8. Expose for Twilio webhooks (separate terminal)
python dev_start.py
# This auto-starts ngrok, writes PUBLIC_BASE_URL to .env, prints the webhook URL
# Set the printed URL as the webhook in Twilio Console
```

### Post-Setup Steps

1. Open `http://localhost:8000/docs` → verify all routes loaded
2. `POST /api/auth/signup` to create first clinic + admin user
3. Configure AI model via `PUT /api/clinics/{id}/config`
4. Add doctors via dashboard or `POST /api/clinics/{id}/doctors`
5. Set Twilio webhook to `{PUBLIC_BASE_URL}/webhook/twilio`
6. Send a test WhatsApp message to the Twilio sandbox number

---

## 17. Known Limitations & Technical Debt

| # | Issue | Impact | Recommended Fix |
|---|---|---|---|
| 1 | **LangGraph MemorySaver is in-RAM** | Booking sub-graph state lost on restart | Migrate to `RedisSaver` or `PostgresSaver` |
| 2 | **APScheduler jobs lost on restart** | Reminders and timeouts not re-scheduled after restart | Use persistent SQL job store |
| 3 | **No test suite** | Regressions undetected | Add pytest + httpx integration tests |
| 4 | **Twilio webhook signature not validated** | Any party can POST to `/webhook/twilio` | Validate `X-Twilio-Signature` header |
| 5 | **Debug endpoints unauthenticated** | Data exposure if `DEBUG_ENDPOINTS=true` in prod | Always `false` in production; add proper auth |
| 6 | **ngrok URL changes on restart** | Must manually update Twilio webhook each time | Use ngrok static domain (paid) or Railway/Render deployment |
| 7 | **No rate limiting** | Vulnerable to bot abuse | Add `slowapi` middleware |
| 8 | **Doctor-side consultation close not wired** | Doctor can't close consultation; patient or timeout only | Add doctor closing phrase detection |
| 9 | **No CI/CD pipeline** | Manual deployments | Add GitHub Actions (lint, test, Docker build, deploy) |
| 10 | **Single-worker assumed** | APScheduler job duplication in multi-worker | Use `DISABLE_SCHEDULER=true` on all but one worker OR use `rq-scheduler` / Celery Beat |

---

## 18. Debugging Guide

### Debug Endpoints

Enable with `DEBUG_ENDPOINTS=true` in `.env` (development only):

```
GET /debug/sessions        → All active booking sessions
GET /debug/appointments    → All confirmed appointments
GET /debug/identity        → Configured doctor phone numbers
GET /debug/pending-approvals → Pending doctor approval requests
GET /debug/doctors         → Doctor profiles in Redis
GET /debug/consultations   → Active consultation sessions
```

### Common Problems

| Symptom | Likely Cause | Fix |
|---|---|---|
| Twilio webhook not arriving | `PUBLIC_BASE_URL` outdated or ngrok restarted | Run `python dev_start.py`; update Twilio Console webhook URL |
| Wrong intent classified | Ambiguous message or missing context in `last_bot_response` | Test directly: `POST /classify` with message and context |
| Appointment reminder not sent | APScheduler not running or job stored in wrong backend | Check `scheduler.running` in startup logs; verify `DISABLE_SCHEDULER=false` |
| Doctor not receiving approval | Doctor number mismatch (env vs DB) | Check `GET /debug/identity`; verify `DOCTOR_WHATSAPP_NUMBERS` format |
| SOAP PDF not generated | Groq API key invalid or audio download failed | Check API key validity; check Twilio media auth (`TWILIO_AUTH_TOKEN`) |
| Redis unavailable warning | Redis not running or wrong URL | Start Redis: `docker compose up redis -d`; check `REDIS_URL` |
| LLM returning garbage JSON | Model too short on context or bad prompt | Check token limits; inspect raw LLM output in logs |
| Calendar slots not showing | `GOOGLE_CALENDAR_ENABLED=false` or OAuth token expired | Re-run `scripts/google_calendar_auth.py`; check token file |

### Useful Log Inspection Points

```bash
# Check which intents are being classified
grep "intent=" logs/app.log

# Check scribe pipeline outputs
grep "SOAP confidence" logs/app.log

# Check scheduler job registration
grep "Scheduled" logs/app.log

# Check Redis store fallback
grep "Redis unavailable" logs/app.log
```

---

## 19. Key Files to Read First

For a new developer onboarding to this codebase, read these files in order:

| Priority | File | Why |
|---|---|---|
| 1 | `main.py` | FastAPI app structure, lifespan hooks, middleware, all routers |
| 2 | `app/models/` (all) | Database schema — foundation of everything |
| 3 | `app/api/webhook_router.py` | Main entry point for all WhatsApp traffic |
| 4 | `app/graph/router.py` | Top-level orchestrator for WhatsApp message routing |
| 5 | `app/graph/classifier.py` | Intent classification — how messages are understood |
| 6 | `app/services/store.py` | Session & state management (Redis) — how context is maintained |
| 7 | `app/graph/agents/booking_agent.py` | Appointment booking FSM — most complex agent |
| 8 | `app/graph/agents/consultation_agent.py` | Consultation flow + closing detection |
| 9 | `app/graph/scribe/pipeline.py` | SOAP generation pipeline |
| 10 | `app/graph/parser/pipeline.py` | Lab report parsing pipeline |
| 11 | `app/services/consultation_service.py` | Jameel integration and finalize flow |
| 12 | `app/core/security.py` | JWT + bcrypt logic |
| 13 | `app/services/scheduler.py` | All background jobs |
| 14 | `.env` | All runtime configuration |

---

*End of KT Document — ClinicAI v1.0*
