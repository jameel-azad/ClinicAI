# ClinicAI — Complete Engineering Report
**Version:** 2.0.0 (Sprint 2, Multi-Agent)
**Date:** 2026-05-27
**Prepared from:** Live codebase at `D:\ClinicAI`

---

## 1. Project Overview

ClinicAI is a WhatsApp-native clinical front-desk assistant built on FastAPI + LangGraph. It handles the full patient lifecycle — from first contact through appointment booking, day-of consultation orchestration, and post-visit follow-up — entirely over WhatsApp using Twilio as the messaging layer.

**Core premise:** A patient sends a WhatsApp message. ClinicAI classifies intent using a Groq-hosted LLaMA 3.3 70B model, routes to a specialist agent, manages multi-turn state in Redis, and replies with a contextually appropriate response. Doctors interact with the same WhatsApp interface to approve appointments, receive SOAP notes, and close consultations.

**Sprint 1 scope:** Intent classification, multi-turn booking flow, appointment approval workflow, reminder + no-show recovery via APScheduler, clinical scribe (voice note → SOAP note PDF via Whisper + LLM + ReportLab), lab report parsing (PDF → LLM summary via pdfplumber + Groq).

**Sprint 2 scope:** Full multi-agent refactor. RouterAgent dispatches to six specialist sub-agents. Net-new: ConsultationAgent (real-time doctor-patient consultation buffering with Jameel integration contract), AfterHoursAgent (message queue with morning flush), enhanced EmergencyAgent (doctor-side WhatsApp alert), FollowUpAgent, LabAgent. All Sprint 1 flows preserved through agent decomposition.

**Stack:**
- Runtime: Python 3.12, FastAPI, uvicorn
- Agent framework: LangGraph 0.x (`StateGraph`, `MemorySaver`)
- LLM: Groq LLaMA 3.3 70B (`llama-3.3-70b-versatile`), Gemini 2.5 Flash fallback
- STT: Groq Whisper Large v3
- Storage: Redis (primary), Python dicts (in-memory fallback)
- Messaging: Twilio WhatsApp Business API
- Scheduling: APScheduler BackgroundScheduler
- PDF: ReportLab (generation), pdfplumber (extraction)

---

## 2. End-to-End Flow

### Patient message path

```
Patient WhatsApp message
    ↓
Twilio webhook POST /webhook/twilio  [app/api/webhook_router.py:33]
    ↓
identify_sender()  [app/services/identity.py]
    determines role: "doctor" | "patient"
    ↓
[if patient + text]
router_graph.invoke(state_update, config={"configurable": {"thread_id": from_number}})
    ↓
RouterAgent: after_hours_check_node
    → is_clinic_open()? [app/graph/agents/after_hours_agent.py]
    → NO: queue_after_hours_message() → ack → END
    → YES: continue
    ↓
intent_node
    → classifier_graph.invoke() [app/graph/classifier.py]
    → Groq LLaMA 3.3 70B → intent + confidence + entities
    ↓
session_node
    → get_session() from Redis [app/services/store.py]
    → create BookingSession if new
    ↓
route_after_session() conditional edge [app/graph/router.py:222]
    → intent == "emergency"           → emergency_dispatch_node
    → journey_state == CONSULTATION_ACTIVE
      OR intent == "consultation_message" → consultation_dispatch_node
    → intent == "lab_report_share"    → lab_dispatch_node
    → intent in followup/prescription → followup_dispatch_node
    → everything else                 → booking_dispatch_node
    ↓
sub-agent graph executes → returns reply_message
    ↓
webhook_router persists last_bot_response to Redis [webhook_router.py:98–106]
    ↓
send_whatsapp_message(to=From, body=reply) [app/services/whatsapp.py]
    ↓
TwiML empty <Response/> returned to Twilio [webhook_router.py:118]
```

### Doctor message path

```
Doctor WhatsApp message (identified by phone number in DOCTOR_WHATSAPP_NUMBERS env)
    ↓
[if audio media] → handle_doctor_voice_note() [app/services/clinical_scribe.py:36]
    → _try_buffer_doctor_audio() — scans Redis for active ConsultationSession
        → if found: buffer audio_url as ConsultationMessage(sender_role="doctor")
        → if not found: run scribe pipeline (Whisper → SOAP → PDF → approval buttons)
[if text/button] → handle_doctor_message() [app/services/doctor.py]
    → button tap → SOAP or appointment approval
    → APPROVE/REJECT {id} → soap_approval or appointment_approval
    → "setup doctor" → doctor_setup onboarding
    → YES/NO → appointment_approval.handle_doctor_approval_reply()
```

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  Twilio WhatsApp Business API                                         │
│  POST /webhook/twilio                                                 │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │ webhook_router  │  app/api/webhook_router.py
              │ identify_sender │
              └────┬────────────┘
                   │ patient text
        ┌──────────▼──────────────────────────────────────────────┐
        │                    RouterAgent                           │
        │                app/graph/router.py                       │
        │                                                          │
        │  START → after_hours_check → intent_node → session_node │
        │                             ↓                            │
        │          route_after_session() conditional edge          │
        └──────┬────────┬───────┬─────────┬────────┬─────────────┘
               │        │       │         │        │
        ┌──────▼──┐ ┌───▼───┐ ┌─▼────┐ ┌─▼─────┐ ┌▼──────────┐
        │Booking  │ │Consult│ │Lab   │ │Follow │ │Emergency  │
        │Agent    │ │Agent  │ │Agent │ │Up     │ │Agent      │
        └─────────┘ └───────┘ └──────┘ └───────┘ └───────────┘

        classifier_graph (all intents run through this)
        app/graph/classifier.py
        validate → preprocess → classify(Groq) → postprocess|fallback(Gemini)

        ┌──────────────────────┐  ┌──────────────────────────────┐
        │ ScribePipeline       │  │ ParserPipeline               │
        │ app/graph/scribe/    │  │ app/graph/parser/            │
        │ Whisper→LLaMA→PDF    │  │ pdfplumber→Groq→summary      │
        └──────────────────────┘  └──────────────────────────────┘

        ┌────────────────────────────────────────────────────────┐
        │  APScheduler BackgroundScheduler                        │
        │  app/services/scheduler.py                              │
        │  · reminder_{appt_id}           DateTrigger            │
        │  · noshow_1hr_{appt_id}         DateTrigger            │
        │  · noshow_24hr_{appt_id}        DateTrigger            │
        │  · consult_timeout_{patient}    DateTrigger            │
        │  · afterhours_flush_{doctor}    CronTrigger daily      │
        └────────────────────────────────────────────────────────┘

        ┌────────────────────────────────────────────────────────┐
        │  Redis (clinicai: namespace)                            │
        │  session:{phone}      TTL 86400s                       │
        │  appt:{id}            no TTL                           │
        │  approval:{id}        no TTL                           │
        │  soap:{id}            TTL 604800s                      │
        │  lab:{id}             TTL 604800s                      │
        │  consult:{phone}      TTL 14400s  (Sprint 2)           │
        │  afterhours:{doctor}  TTL 129600s (Sprint 2)           │
        └────────────────────────────────────────────────────────┘
```

---

## 4. Codebase Breakdown

### Entry point

**`main.py`** — FastAPI application factory. Uses `_optional_attr()` to load modules gracefully (any missing module is skipped, not a startup crash). Lifespan context manager starts APScheduler, calls `schedule_afterhours_flush(doc_num)` for every configured doctor, logs Sprint 2 agent names. Includes `classifier_router`, `webhook_router`, `parser_router` in sequence. Exposes `GET /` health check and `GET /graph/nodes` debug endpoint.

### API layer (`app/api/`)

**`webhook_router.py`** — All Twilio interactions. Receives `From`, `Body`, `NumMedia`, `MediaUrl0`, `MediaContentType0`, `ButtonPayload` via Form parameters. Routing priority: doctor+audio → voice note scribe; doctor+text → doctor command handler; patient+PDF → lab report parser; patient+text → `router_graph.invoke()`. After invocation, serializes `last_bot_response` back to Redis for context-aware classification on the next turn. Debug endpoints at `/debug/sessions`, `/debug/appointments`, `/debug/identity`, `/debug/pending-approvals`, `/debug/doctors`, `/debug/consultations`. PDF download at `/lab-report/pdf/{id}` and `/scribe/pdf/{id}`.

**`classifier_router.py`** — Direct HTTP interface for testing the classifier. `POST /classify` accepts `ClassifyRequest`, runs `classifier_graph.invoke()`, returns `ClassifyResponse`. Not used in the WhatsApp flow.

**`parser_router.py`** — Direct upload interface for lab PDFs. `POST /parse-lab-report`.

**`scribe_router.py`** — Jameel's scribe API endpoint. `POST /scribe/consult` accepts a `ConsultationBundleRequest` (patient_id, doctor_id, messages, audio_files), calls `scribe_service.process_consultation_bundle()`, and returns `ScribeResult` (soap_note_pdf_url, follow_up_questions, missing_sections, summary_for_whatsapp). When the two services are eventually deployed independently, `JAMEEL_SCRIBE_URL` is set to point here and the integration switches from local function call to HTTP without any other code change.

### Graph layer (`app/graph/`)

**`classifier.py`** — Intent classification pipeline. 6-node LangGraph: `validate_node` (empty/too-short rejection) → `preprocess_node` (strip whitespace, normalize) → `classify_node` (Groq LLaMA 3.3 70B, temperature=0.1, max_tokens=512) → `postprocess_node` (normalize output) | `fallback_node` (Gemini 2.5 Flash if Groq fails or returns invalid JSON). State type: `ClassifierState`. Context-aware: passes `context_message` (previous bot response) as part of the system prompt so the LLM can see the conversational context. `_sanitise_multi_result()` handles both `{"intent": "..."}` (legacy) and `{"intents": [...]}` (new multi-intent) formats. Compiled once at import as `classifier_graph`.

**`router.py`** — RouterAgent, the top-level orchestrator. 8 nodes: `after_hours_check_node`, `intent_node`, `session_node`, `booking_dispatch_node`, `consultation_dispatch_node`, `emergency_dispatch_node`, `lab_dispatch_node`, `followup_dispatch_node`. Uses `MemorySaver()` for per-thread checkpointing (thread_id = patient phone number). Consultation agent is imported lazily inside `consultation_dispatch_node` to break the circular import chain. `_invoke_sub_agent(graph, state)` normalizes the full BookingState dict before passing to sub-agent to prevent KeyError on missing fields. Compiled as `router_graph`.

**`booking.py`** — Backward-compatibility shim. Single line: `from app.graph.router import router_graph as booking_graph`. Any external code importing `booking_graph` still works.

**`agents/booking_agent.py`** — Core multi-turn booking state machine. Nodes: `off_topic_node`, `flow_node`, `confirm_node`, `cancel_node`, `reschedule_node`, `appointment_status_node`. Receives pre-classified intent from the router — no internal classifier call. `flow_node` is the main workhorse: reads `session.state` and advances through GREETING → COLLECTING_INFO → COLLECT_DATE_TIME → CONFIRM_SLOT → WAITING_DOCTOR_APPROVAL → BOOKED using `MSG_*` string templates and entity extraction via `BOOKING_ENTITY_PROMPT`. When slot is confirmed, calls `appointment_approval.request_doctor_approval()`. Compiled without MemorySaver — state threading is the router's responsibility.

**`agents/consultation_agent.py`** — Sprint 2 core. `CLOSING_PHRASES` set with 14 Hindi/English terms. `start_or_resume_node`: loads or creates `ConsultationSession`, buffers incoming patient message as `ConsultationMessage(sender_role="patient")`, calls `schedule_consultation_timeout()`, sets `journey_state = CONSULTATION_ACTIVE` on `BookingSession`. `detect_end_node`: checks `session.is_active` (may have been set False by timeout job) and `_is_closing_phrase()`. `finalize_node`: calls `finalize_and_send(patient_number)` via `asyncio.run()` in a `ThreadPoolExecutor` to handle the case where FastAPI's event loop is already running. `ack_node`: in-progress acknowledgement to patient. Graph: START → start_or_resume → detect_end → [finalize | ack] → END.

**`agents/emergency_agent.py`** — Stateless one-shot. Sends "Call 112" response to patient. Loops `all_doctor_numbers()` and sends emergency alert WhatsApp message to each doctor.

**`agents/after_hours_agent.py`** — `is_clinic_open()` reads `CLINIC_OPEN_HOUR` and `CLINIC_CLOSE_HOUR` env vars, checks `datetime.now(ZoneInfo("Asia/Kolkata")).hour`. `queue_node` calls `queue_after_hours_message()`. `ack_node` returns a templated closed-clinic message with computed hours.

**`agents/followup_agent.py`** — Handles `followup_query` and `prescription_request` intents. Checks `session.journey_state == "POST_CONSULT"` for context-appropriate response. Falls back to `bot_response` from classifier or generic "book an appointment" message.

**`agents/lab_agent.py`** — Thin wrapper for when `lab_report_share` intent arrives but no PDF is attached. Prompts patient to forward the PDF.

**`scribe/`** — LangGraph pipeline for clinical SOAP generation. `pipeline.py` compiles: `transcribe_node` (Groq Whisper API) → `soap_generator_node` (LLaMA 3.3 70B) → `grounding_check_node` → `followup_generator_node` → `pdf_output_node` (ReportLab). State in `state.py` as `ScribeState` TypedDict.

**`parser/`** — LangGraph pipeline for lab report extraction. `pipeline.py` compiles: PDF text extraction (pdfplumber) → LLM summary (Groq). State in `state.py`.

### Service layer (`app/services/`)

**`store.py`** — Dual persistence layer. Attempts Redis connection at import (`_connect_redis()`); falls back silently to in-memory dicts. All public functions have identical signatures regardless of backend. Key prefix `clinicai:`. Sprint 2 adds `_consultations: dict` and `_after_hours_queues: dict` in-memory fallbacks, plus 7 new public functions for consultation and after-hours queue management.

**`scheduler.py`** — APScheduler BackgroundScheduler. Sprint 1: reminder jobs (`reminder_{id}` via DateTrigger), no-show jobs (`noshow_1hr_{id}`, `noshow_24hr_{id}` via DateTrigger). Sprint 2: consultation timeout jobs (`consult_timeout_{patient}` via DateTrigger, `replace_existing=True` so `reset_consultation_timeout()` just calls `schedule_consultation_timeout()` again), after-hours flush jobs (`afterhours_flush_{doctor}` via CronTrigger at `CLINIC_OPEN_HOUR:00 IST`). `_resolve_appointment_datetime()` handles today/aaj, tomorrow/kal, parso, and explicit month+day with year.

**`consultation_service.py`** — New in Sprint 2. `build_consultation_bundle()` serializes the `ConsultationSession` into Jameel's integration contract (patient_id, doctor_id, messages array, audio_files array). `_call_jameel()` dispatches based on `JAMEEL_SCRIBE_URL`: if set, POSTs the bundle to the external API (60s timeout); if empty, calls `scribe_service.process_consultation_bundle()` directly in-process — no stub, no HTTP hop, the real pipeline runs. `finalize_and_send()` orchestrates: load session → build bundle → call `_call_jameel()` → compose doctor summary → send via WhatsApp → set `journey_state = "POST_CONSULT"` on `BookingSession` → delete `ConsultationSession` from Redis. Returns patient-facing reply string.

**`scribe_service.py`** — New (Jameel's side). The full consultation-to-SOAP pipeline:
1. Downloads every audio file from the bundle via httpx (Twilio basic auth)
2. Transcribes each file using Groq Whisper (`asyncio.to_thread` to avoid blocking FastAPI's event loop)
3. `_build_combined_transcript()` merges all messages in order, prefixing each line with `PATIENT:` or `DOCTOR:` so the LLM understands who spoke
4. Calls `soap_generator_node` → `grounding_check_node` → `followup_generator_node` → `pdf_output_node` directly (these are plain functions, no need to re-run the full LangGraph pipeline)
5. Stores the PDF via `store_scribe_pdf()` and builds the public URL
6. Returns `{soap_note_pdf_url, follow_up_questions, missing_sections, summary_for_whatsapp}`
Cleans up all temp audio files regardless of success or failure.

**`clinical_scribe.py`** — Doctor voice note handler. Sprint 2 added pre-check: `_try_buffer_doctor_audio()` scans `clinicai:consult:*` Redis keys, matches `session.doctor_number == doctor_number`, buffers audio as `ConsultationMessage(sender_role="doctor")` and appends to `session.audio_files`. If active consultation found, returns ack and skips local scribe pipeline. Local scribe pipeline: download audio (httpx with Twilio auth) → `_run_scribe_pipeline()` → extract patient number from caption or appointment lookup → save pending SOAP → send PDF + approval buttons to doctor.

**`appointment_approval.py`** — Approval workflow. `request_doctor_approval()` generates `APT{5-char}` approval ID, checks slot availability via Google Calendar or local scan, sends Twilio Content Template (interactive buttons) or text fallback. `handle_doctor_approval_reply()` parses `YES APT{id}` / `NO APT{id}` text. `handle_appointment_button_reply()` handles `apt_approve` / `apt_reject` payloads. `_approve()` creates `AppointmentRecord`, schedules reminder and no-show jobs, notifies patient. `_reject()` prompts patient for new slot.

**`soap_approval.py`** — SOAP approval workflow. `handle_soap_approval_reply()` parses `APPROVE RX{id}` / `REJECT RX{id}`. `handle_soap_button_reply()` handles `soap_approve` / `soap_reject`. On approve: sends PDF to patient via `send_whatsapp_media_sync()`.

**`identity.py`** — Sender identity resolution. Reads `DOCTOR_WHATSAPP_NUMBERS` env var (format: `"Dr Name:+91xxx,Dr Name2:+91xxx2"`). `identify_sender()` normalizes the raw Twilio `From` field and returns `SenderIdentity(phone_number, role, display_name)`. `find_doctor_number()` does fuzzy name match. `find_doctor_name()` does reverse lookup. `all_doctor_numbers()` returns list of all configured phone numbers.

**`doctor.py`** — Doctor command router. Priority order: button taps → SOAP/appointment approval; text pattern SOAP approval; "setup doctor" → doctor_setup; `OK LAB{id}` → lab review; `YES`/`NO` → appointment_approval; help/today's appointments/pending approvals; greetings.

**`doctor_setup.py`** — 5-step doctor onboarding via WhatsApp: name, google email, working hours, appointment duration, buffer. Stored as `doctor_profile` dict under `clinicai:doctor_profile:{number}`.

**`whatsapp.py`** — Three send functions. `send_whatsapp_message_sync(to, body)`: normalizes to `whatsapp:+...` format, creates `TwilioClient` with env creds, mock mode if no creds. `send_whatsapp_media_sync(to, body, media_url)`: same + `media_url` parameter. `send_whatsapp_template_sync(to, content_sid, content_variables)`: Twilio Content Templates (interactive buttons). All have `async` wrappers that run sync version in thread executor.

**`google_calendar.py`** — `calendar_enabled()` checks `GOOGLE_CALENDAR_ENABLED=True`. `check_google_availability()` queries Google Calendar API for conflicts. `create_google_calendar_event()` creates event on doctor's calendar. `suggest_google_slots()` finds nearest available slots. Entire module is no-op when `GOOGLE_CALENDAR_ENABLED=False`.

**`pdf_service.py`** — Lab report PDF handler. `handle_incoming_pdf(media_url, from_number)`: downloads PDF (Twilio auth), runs parser pipeline, stores result, sends LLM summary to patient, creates pending lab review for doctor notification.

### Schema layer (`app/schemas/__init__.py`)

All type definitions in one file:
- `ClassifierState` (TypedDict) — LangGraph state for classification pipeline
- `BookingState` (TypedDict) — LangGraph state for all booking/routing pipelines; `pipeline_log` uses `Annotated[list, operator.add]` so each node appends rather than replaces
- `BookingSession` (Pydantic v2 BaseModel) — per-patient Redis session
- `AppointmentRecord` (Pydantic v2 BaseModel) — confirmed appointment
- `ClassifyRequest/Response`, `Entities`, `IntentResult` — API request/response types
- `ConsultationMessage` (Pydantic v2 BaseModel) — single message with `sender_role: Literal["doctor", "patient"]`
- `ConsultationSession` (Pydantic v2 BaseModel) — full consultation with messages buffer, audio_files, is_active flag, ended_reason
- `BOOKING_FLOW_STATES` (list of 10) — granular booking sub-flow states
- `PATIENT_JOURNEY_STATES` (list of 7) — high-level patient lifecycle states
- `ALL_INTENTS` (list of 10) — full intent taxonomy

### Prompt layer (`app/prompts/__init__.py`)

**`CLASSIFIER_SYSTEM_PROMPT`** — ~150-line prompt. Security section: explicit injection detection rules, flags messages with role instructions or prompt overrides. Taxonomy: 10 intents with examples, Hinglish handling (bilingual), relational terms exclusion (`mummy ki appointment` maps to patient booking intent, not a different patient). Entity extraction rules: `requested_date` relative terms (today/aaj, tomorrow/kal, parso), `requested_time` with 12/24hr, `symptoms_mentioned` as list. Output format: `{"intents": [{"intent": ..., "confidence": ..., "entities": {...}, "bot_response": ...}]}`. Context awareness: if `context_message` provided, uses it to disambiguate incomplete follow-up messages.

**`CLASSIFIER_FEW_SHOT`** — 9 few-shot examples covering: emergency in Hinglish, multi-intent booking+followup, relational terms, consultation messages during active session, injection attempt.

**`BOOKING_ENTITY_PROMPT`** — Entity extraction for booking: date normalization, time normalization, doctor name extraction, "same day"/"usi din" resolution.

---

## 5. Backend Execution Flow

### Detailed flow: New patient books appointment

```
1. Patient: "Hi, I want to see Dr Jameel tomorrow at 10am"

2. webhook_router.py:33 — POST /webhook/twilio
   identify_sender("+919876543210") → role=patient

3. router_graph.invoke({"from_number": "+919876543210", "incoming_message": "..."})
   thread_id = "+919876543210"  (MemorySaver checkpoint key)

4. after_hours_check_node [router.py:47]
   is_clinic_open() → True (9am–8pm IST check)
   → pipeline_log: ["router: clinic open — continuing"]

5. intent_node [router.py:73]
   get_session("+919876543210") → None (new patient)
   context_message = None
   classifier_graph.invoke({...})
     validate_node: len("Hi I want...") > 0 → is_valid=True
     preprocess_node: strip/normalize
     classify_node: Groq LLaMA3.3-70B call
       → intent="appointment_book", confidence=0.94
       → entities={patient_name: None, doctor_name: "Dr Jameel",
                   requested_date: "tomorrow", requested_time: "10am"}
   → state: intent="appointment_book", extracted_entities={...}

6. session_node [router.py:112]
   get_session("+919876543210") → None
   → creates BookingSession(from_number="+919876543210", state="GREETING", journey_state="NEW_PATIENT")
   → save_session() → Redis clinicai:session:+919876543210 TTL 86400s
   → is_new_session=True, current_booking_state="GREETING"

7. route_after_session [router.py:222]
   intent="appointment_book" → booking_dispatch_node

8. booking_dispatch_node [router.py:163]
   _invoke_sub_agent(booking_agent_graph, state)
   booking_agent_graph.invoke({...})
     route_from_start(): intent="appointment_book", state="GREETING"
       → flow_node
     flow_node:
       session.state = "GREETING"
       → asks patient name (MSG_GREETING_BOOK)
       → state transitions to COLLECTING_INFO
       → save_session()
   reply_message = "Welcome to ClinicAI! I'm happy to help you book..."

9. webhook_router.py:98–106
   sess_dict["last_bot_response"] = reply[:300]
   save_session(BookingSession(**sess_dict))

10. send_whatsapp_message(to="whatsapp:+919876543210", body=reply)
    Twilio API call → patient receives message
```

### Detailed flow: Consultation lifecycle

```
1. Patient sends: "doctor mujhe sir dard ho raha hai"
   → classifier: intent="consultation_message", confidence=0.89

2. session.journey_state == "NEW_PATIENT"
   route_after_session → intent == "consultation_message"
   → consultation_dispatch_node

3. consultation_agent.start_or_resume_node:
   get_consultation(patient_number) → None (no existing session)
   get_latest_appointment_for_patient(patient_number)
     → AppointmentRecord(doctor_name="Dr Jameel")
   find_doctor_number("Dr Jameel") → "+919801581020"
   ConsultationSession created:
     consultation_id = "CONS" + 6-char uuid
     patient_number = from_number
     doctor_number = "+919801581020"
     messages = [ConsultationMessage(sender_role="patient", text="doctor mujhe...")]
   save_consultation(patient_number, new_session)
   schedule_consultation_timeout(patient_number, consultation_id)
     → APScheduler job: consult_timeout_{patient_number}
     → fires at now + CONSULTATION_TIMEOUT_MINUTES (2 min in demo, 30 min in prod)
   booking.journey_state = "CONSULTATION_ACTIVE"
   save_session(booking)

4. consultation_agent.detect_end_node:
   session.is_active = True
   _is_closing_phrase("doctor mujhe sir dard...") = False
   → no action

5. route_after_detect: session.is_active=True → ack_node
   → reply_message = "Message received — consultation in progress. 🩺\nThe doctor will respond shortly."

--- Doctor sends voice note during consultation ---

6. Doctor voice note received at webhook:
   handle_doctor_voice_note(media_url, "audio/ogg", "+919801581020", "Dr Jameel")

7. _try_buffer_doctor_audio(media_url, "+919801581020"):
   scan Redis clinicai:consult:*
   find clinicai:consult:+919876543210
   session.doctor_number == "+919801581020" ✓
   ConsultationMessage(sender_role="doctor", audio_url=media_url) appended
   session.audio_files.append({"url": media_url, "duration_secs": None})
   save_consultation(patient_number, session)
   return "🎙️ Voice note received and added to the active consultation buffer..."

--- Doctor sends "ok done" ---

8. Doctor text "ok done" at webhook:
   handle_doctor_message("ok done", "Dr Jameel", "+919801581020")
   → handle_doctor_message routes to... (does not recognize as consultation close — doctor closing is currently in consultation_agent via patient-side message in demo mode)

NOTE: In current implementation, closing phrase detection runs on patient messages.
      Doctor close via text goes through handle_doctor_message, which does not yet
      route to consultation_agent. For demo, patient sends "ok done" to trigger close.

9. Patient sends: "ok done"
   → classifier: intent="consultation_message" (or general_query)
   → consultation_dispatch_node again

10. start_or_resume_node: existing session found, buffer patient message

11. detect_end_node:
    session.is_active = True
    _is_closing_phrase("ok done") = True
    session.ended_reason = "closing_phrase"
    session.is_active = False
    save_consultation()
    cancel_consultation_timeout(patient_number)

12. route_after_detect: session.is_active=False → finalize_node

13. finalize_node:
    asyncio.get_event_loop().is_running() = True (FastAPI context)
    → ThreadPoolExecutor: asyncio.run(finalize_and_send(patient_number))

14. finalize_and_send [consultation_service.py:78]:
    session = get_consultation(patient_number)
    bundle = build_consultation_bundle(session)
      → {patient_id, doctor_id, messages: [2 items], audio_files: [1 item]}
    result = await _call_jameel(bundle)
      → JAMEEL_SCRIBE_URL="" → scribe_service.process_consultation_bundle(bundle)
        → _download_audio(audio_url) [Twilio auth, httpx]
        → asyncio.to_thread(_transcribe_audio, path) [Groq Whisper]
        → _build_combined_transcript(messages, audio_transcripts)
            "PATIENT: sir dard ho raha\nDOCTOR: <transcription of voice note>"
        → soap_generator_node(state) [LLaMA 3.3 70B → SOAP JSON]
        → grounding_check_node(state) [LLaMA → verify sentences against transcript]
        → followup_generator_node(state) [LLaMA → 2-3 follow-up questions]
        → pdf_output_node(state) [ReportLab → PDF file]
        → store_scribe_pdf(pdf_path) → document_id
        → returns {soap_note_pdf_url, follow_up_questions, missing_sections, summary_for_whatsapp}
    doctor_summary = "📋 ClinicAI — Consultation Summary\n\nPatient: +919876543210\n..."
    send_whatsapp_message_sync("+919801581020", doctor_summary)
    booking_session.journey_state = "POST_CONSULT"
    save_session(booking_session)
    delete_consultation(patient_number)
    return "Your consultation has been recorded..."

15. reply_message → patient receives confirmation
    Doctor receives: WhatsApp message with summary + follow-up questions + PDF link
```

### Detailed flow: Consultation bundle → scribe pipeline (scribe_service.py)

```
Input: consultation_bundle = {
  patient_id: "+919876543210",
  doctor_id:  "+919801581020",
  messages: [
    {sender_role: "patient", text: "sir dard ho raha", audio_url: null},
    {sender_role: "doctor",  text: null, audio_url: "https://api.twilio.com/..."},
  ],
  audio_files: [{url: "https://api.twilio.com/...", duration_secs: null}]
}

Step 1 — Download each audio file [scribe_service._download_audio()]:
  httpx.AsyncClient.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
  response.headers["content-type"] → "audio/ogg" → suffix=".ogg"
  tempfile.mkstemp(suffix=".ogg") → /tmp/tmpXXXX.ogg

Step 2 — Transcribe [scribe_service._transcribe_audio() via asyncio.to_thread]:
  Groq(api_key).audio.transcriptions.create(
    model="whisper-large-v3",
    file=("tmpXXXX.ogg", bytes),
    response_format="verbose_json",
    prompt="clinic in India, Hinglish, medical abbreviations..."
  )
  → "Patient hai Suresh, BP thoda high hai, amlodipine start karte hain"
  audio_transcripts[url] = "Patient hai Suresh..."

Step 3 — Build combined transcript [_build_combined_transcript()]:
  message[0]: sender_role=patient, text="sir dard ho raha"
    → "PATIENT: sir dard ho raha"
  message[1]: sender_role=doctor, audio_url=url
    → audio_transcripts[url] = "Patient hai Suresh, BP thoda high hai..."
    → "DOCTOR: Patient hai Suresh, BP thoda high hai..."
  combined = "PATIENT: sir dard ho raha\nDOCTOR: Patient hai Suresh, BP thoda high hai..."

Step 4 — SOAP generation [soap_generator_node()]:
  ScribeState = {transcript: combined, doctor_name: "Dr Jameel", clinic_name: "ClinicAI"}
  LLaMA 3.3 70B with SOAP_SYSTEM prompt
  → soap_note = {
      patient_name: "Suresh",
      subjective: {content: "Patient Suresh presents with headache...", confidence: 0.75},
      objective:  {content: "BP 140/90 mmHg", confidence: 0.9},
      assessment: {content: "Hypertension stage 1", confidence: 0.85},
      plan:       {content: "Amlodipine 5mg OD. Follow-up 2 weeks.", confidence: 0.95}
    }
  missing_sections: []

Step 5 — Grounding check [grounding_check_node()]:
  LLaMA checks every SOAP sentence against the transcript
  → grounding_report: [{sentence: "BP 140/90", transcript_segment: "BP thoda high", is_grounded: true}, ...]
  → ungrounded_flags: [] (all grounded)

Step 6 — Follow-up questions [followup_generator_node()]:
  LLaMA generates patient-friendly questions from assessment + plan
  → follow_up_questions: [
      "How are you feeling? Has the headache reduced?",
      "Have you been taking the BP tablet every day?",
      "Have you checked your blood pressure at home?"
    ]
  → summary_for_whatsapp: "Suresh | Dx: Hypertension stage 1 | Rx: Amlodipine 5mg OD"

Step 7 — PDF generation [pdf_output_node() → pdf_builder.build_soap_pdf()]:
  ReportLab builds A4 PDF:
    Header: "ClinicAI  |  Dr. Jameel  |  27 May 2026"
    Patient bar: "Patient: Suresh  |  Generated: 27 May 2026, 14:32"
    4 SOAP sections (colour-coded by confidence: green≥75%, amber≥50%, red<50%)
    Grounding report appendix table
    Transcript appendix
    Footer: "Generated by FellowAI Clinical Scribe · DPDP Act 2023 Compliant"
  pdf_path = "/tmp/tmpSOAP.pdf"

Step 8 — Store PDF + build URL:
  store_scribe_pdf("/tmp/tmpSOAP.pdf")
    → document_id = str(uuid4())
    → copies to generated/scribe_pdfs/{document_id}.pdf
    → _pdf_store[document_id] = path
  soap_note_pdf_url = "{PUBLIC_BASE_URL}/scribe/pdf/{document_id}"

Step 9 — Cleanup:
  os.remove("/tmp/tmpXXXX.ogg")

Output: {
  soap_note_pdf_url: "https://...ngrok.../scribe/pdf/abc-123",
  follow_up_questions: ["How are you feeling?", ...],
  missing_sections: [],
  summary_for_whatsapp: "Suresh | Dx: Hypertension stage 1 | Rx: Amlodipine 5mg OD"
}
```

### Detailed flow: After-hours message + morning flush

```
1. Patient messages at 9:30 PM IST:
   after_hours_check_node: is_clinic_open()
     now.hour = 21 >= CLINIC_CLOSE_HOUR(20) → False
   after_hours_agent_graph.invoke({...})
     queue_node: queue_after_hours_message(doctor_number, from_number, message)
       → Redis: clinicai:afterhours:{doctor_number} = [..., {from_number, body, queued_at}]
       → TTL: 129600s (36h)
     ack_node: "ClinicAI is closed right now (9 AM – 8 PM IST)..."
   route_after_hours: reply_message set → END (skips intent_node)

2. Next morning at 9:00 AM IST:
   _flush_afterhours_job(doctor_number) fires (CronTrigger)
   get_after_hours_queue(doctor_number) → [patient message dict]
   clear_after_hours_queue(doctor_number)
   for item in queued:
     router_graph.invoke({"from_number": item["from_number"], "incoming_message": item["body"]})
     → full normal routing → booking flow continues
```

---

## 6. Database & Storage

### Redis key schema

All keys prefixed `clinicai:`. Connection: `REDIS_URL=redis://localhost:6379`. On failure, silently falls back to in-memory Python dicts (process-lifetime only, no cross-restart persistence).

| Key Pattern | Value Type | TTL | Purpose |
|---|---|---|---|
| `session:{phone}` | JSON (BookingSession) | 86400s (24h) | Per-patient multi-turn booking state |
| `appt:{id}` | JSON (AppointmentRecord) | None | Confirmed appointments |
| `appts_by_phone:{phone}` | Redis SET of appt IDs | None | Reverse index for patient→appointments |
| `approval:{id}` | JSON dict | None | Pending doctor appointment approvals |
| `approvals_waiting:{doctor}` | Redis SET of approval IDs | None | Index for doctor's pending approvals |
| `doctor_profile:{phone}` | JSON dict | None | Doctor onboarding profile |
| `doctor_setup:{phone}` | JSON dict | 3600s (1h) | In-progress doctor setup session |
| `greeted:{phone}` | `"1"` | 2592000s (30d) | Greeting suppression flag |
| `slot_suggestions:{phone}` | JSON list | 86400s (24h) | Calendar slot suggestion cache |
| `soap:{id}` | JSON dict | 604800s (7d) | Pending SOAP note approvals |
| `lab:{id}` | JSON dict | 604800s (7d) | Pending lab review notifications |
| `last_active:{phone}` | ISO timestamp string | 604800s (7d) | No-show check: last patient activity |
| `consult:{phone}` | JSON (ConsultationSession) | 14400s (4h) | Active consultation session buffer |
| `afterhours:{doctor}` | JSON list of message dicts | 129600s (36h) | After-hours message queue |

### In-memory fallback stores (when Redis unavailable)

```python
_sessions: dict[str, BookingSession]
_appointments: dict[str, AppointmentRecord]
_pending_approvals: dict[str, dict]
_greeted_numbers: set[str]
_doctor_profiles: dict[str, dict]
_doctor_setup_sessions: dict[str, dict]
_slot_suggestions: dict[str, list[dict]]
_pending_soaps: dict[str, dict]
_pending_lab_reviews: dict[str, dict]
_consultations: dict[str, ConsultationSession]    # Sprint 2
_after_hours_queues: dict[str, list[dict]]        # Sprint 2
```

All in-memory stores are process-lifetime only. A server restart loses all state.

### LangGraph MemorySaver

`router_graph` uses `MemorySaver()` as its checkpointer. This stores LangGraph thread state in-process memory (not Redis). Thread ID = patient phone number. This is separate from Redis sessions — the MemorySaver holds LangGraph's internal graph checkpoint, while Redis holds the application-level `BookingSession` data.

---

## 7. Infrastructure & Deployment

### Local development

```
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or directly: `python main.py` which calls `uvicorn.run("main:app", ...)`.

**External tunnel:** ngrok required for Twilio webhook callbacks. `PUBLIC_BASE_URL` in `.env` is the current ngrok URL. Must be updated on every ngrok session restart.

**Redis:** `docker run -p 6379:6379 redis` or local Redis service. If unavailable, falls back to in-memory (no restart persistence).

**Dependencies (inferred from imports):**
- `fastapi`, `uvicorn`
- `langchain-core`, `langchain-groq`, `langchain-google-genai`, `langgraph`
- `pydantic` (v2)
- `redis`
- `apscheduler`
- `httpx`
- `twilio`
- `python-dotenv`
- `groq` (for Whisper API)
- `reportlab`
- `pdfplumber`
- `zoneinfo` (Python 3.9+ stdlib)

### Environment configuration

All configuration via `.env` file. Key variables:

```ini
# LLM
GROQ_API_KEY=...                    # Groq Cloud API key
GEMINI_API_KEY=...                  # Google Generative AI key (fallback LLM)
GROQ_MODEL=llama-3.3-70b-versatile  # Primary classifier model
GEMINI_MODEL=gemini-2.5-flash       # Fallback model
WHISPER_MODEL=whisper-large-v3      # Voice transcription model

# Twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
SOAP_APPROVAL_CONTENT_SID=HX...    # Twilio Content Template SID (SOAP approval buttons)
APPOINTMENT_APPROVAL_CONTENT_SID=HX...  # Twilio Content Template SID (appt approval buttons)

# Doctor configuration
DOCTOR_WHATSAPP_NUMBERS=Dr Jameel:+919801581020   # Comma-separated "Name:number" pairs

# Clinic settings
CLINIC_NAME=ClinicAI
CLINIC_OPEN_HOUR=9                  # After-hours window start (IST)
CLINIC_CLOSE_HOUR=20                # After-hours window end (IST)
REMINDER_MINUTES_BEFORE=2           # Demo: 2 min; Prod: 120 min
CONSULTATION_TIMEOUT_MINUTES=2      # Demo: 2 min; Prod: 30 min

# Integration
JAMEEL_SCRIBE_URL=                  # Empty = stub mode; set when Jameel API is live
REDIS_URL=redis://localhost:6379
PUBLIC_BASE_URL=https://...ngrok-free.app  # For PDF public URLs in WhatsApp

# Google Calendar (optional)
GOOGLE_CALENDAR_ENABLED=False
GOOGLE_CALENDAR_CREDENTIALS_FILE=google_credentials.json
GOOGLE_CALENDAR_TOKEN_FILE=google_token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_CALENDAR_TIMEZONE=Asia/Kolkata
APPOINTMENT_DURATION_MINUTES=30
```

### No Docker, no CI/CD

Current deployment is fully local development. No Dockerfile, no docker-compose, no CI pipeline exists in the repository. Manual startup + ngrok for external access.

---

## 8. Features Implemented So Far

### Sprint 1

**Intent classification (10 intents):**
- `appointment_book` — multi-turn booking with entity extraction
- `appointment_cancel` — cancel by appointment ID or latest
- `appointment_reschedule` — collect new date/time, re-submit for approval
- `appointment_status` — show current booking status
- `followup_query` — post-visit follow-up handling
- `lab_report_share` — lab PDF processing trigger
- `prescription_request` — prescription handling
- `general_query` — off-topic catch-all with graceful response
- `emergency` — emergency alert to patient + doctor
- `consultation_message` — Sprint 2 consultation session trigger

**Multi-turn booking flow:**
- GREETING → COLLECTING_INFO → COLLECT_DATE_TIME → CONFIRM_SLOT → WAITING_DOCTOR_APPROVAL → BOOKED state machine
- Context-aware classification using `last_bot_response`
- Hinglish date/time understanding (today/aaj, tomorrow/kal, parso, explicit month+day)

**Doctor approval workflow:**
- Twilio Content Templates (interactive buttons) for approve/reject
- Text-based `YES APT{id}` / `NO APT{id}` fallback
- `APT{5-char-uuid}` approval IDs
- Google Calendar slot availability check (when enabled)

**Appointment reminder:**
- APScheduler DateTrigger at `appointment_time - REMINDER_MINUTES_BEFORE`
- Dynamic time label: "2 minutes" / "2 hours" based on `REMINDER_MINUTES_BEFORE` value
- Early appointment safeguard: if < `REMINDER_MINUTES_BEFORE` away, fires in 30 seconds

**No-show recovery:**
- Two-attempt system: +1hr and +24hr after appointment time
- Activity check: skips recovery if patient was active after appointment time (`last_active` Redis key)

**Clinical scribe (SOAP notes):**
- Doctor sends voice note → Whisper transcription → LLaMA SOAP generation → ReportLab PDF
- Doctor approval buttons (Twilio Content Template) before sending to patient
- `APPROVE RX{id}` / `REJECT RX{id}` text commands
- PDF served at `/scribe/pdf/{id}` via FileResponse

**Lab report parsing:**
- Patient sends PDF → pdfplumber extraction → Groq LLM summary → patient receives summary
- Doctor notification with `OK LAB{id}` acknowledgement command
- PDF served at `/lab-report/pdf/{id}`

**Doctor onboarding:**
- 5-step setup: name, google email, working hours, appointment duration, buffer
- `doctor_profile` stored in Redis

### Sprint 2

**Multi-agent architecture:**
- RouterAgent as top-level orchestrator (8 nodes)
- 6 specialist sub-agents dispatched via intent + journey_state routing
- All Sprint 1 booking flows preserved through BookingAgent

**ConsultationAgent:**
- Creates ConsultationSession in Redis with 4h TTL
- Buffers all patient messages as `ConsultationMessage(sender_role="patient")`
- Doctor voice notes buffered as `ConsultationMessage(sender_role="doctor")` via `_try_buffer_doctor_audio()`
- Inactivity timeout via APScheduler (configurable, default 30 min)
- Closing phrase detection (14 Hindi/English phrases)
- Two termination paths: closing phrase → immediate finalize; timeout job → finalize
- `finalize_and_send()` builds consultation bundle → calls `scribe_service.process_consultation_bundle()` (local) or external `JAMEEL_SCRIBE_URL` (when set)
- Doctor receives consultation summary + PDF link via WhatsApp within 60s of close
- `journey_state` transitions: NEW_PATIENT → CONSULTATION_ACTIVE → POST_CONSULT

**Jameel integration contract:**
```json
{
  "patient_id": "+919876543210",
  "doctor_id": "+919801581020",
  "messages": [
    {"sender_role": "patient", "text": "sir dard ho raha", "audio_url": null, "timestamp": "..."},
    {"sender_role": "doctor", "text": null, "audio_url": "https://api.twilio.com/...", "timestamp": "..."}
  ],
  "audio_files": [{"url": "https://...", "duration_secs": null}]
}
```

**AfterHoursAgent:**
- `is_clinic_open()` check at router entry
- Message queued to Redis list with 36h TTL
- Morning flush via `CronTrigger(hour=CLINIC_OPEN_HOUR, minute=0)`
- Re-injects queued messages into router_graph on open

**EmergencyAgent:**
- "Call 112" response to patient
- Emergency alert to all configured doctor numbers

**FollowUpAgent:**
- POST_CONSULT context-aware responses
- Prescription request handling

**LabAgent:**
- Lab report intent with no PDF attached → prompts for PDF

**Jameel Scribe Pipeline (`scribe_service.py`):**
- Accepts `consultation_bundle` (patient_id, doctor_id, messages, audio_files)
- Downloads all doctor audio files from Twilio media URLs (basic auth)
- Transcribes each file via Groq Whisper (`asyncio.to_thread` — non-blocking)
- Builds combined consultation transcript with `PATIENT:` / `DOCTOR:` role labels
- Runs `soap_generator_node` → `grounding_check_node` → `followup_generator_node` → `pdf_output_node` (same nodes as single-voice-note scribe, called as plain functions)
- Stores PDF in `generated/scribe_pdfs/`, returns public URL at `/scribe/pdf/{id}`
- Returns full integration contract response: `{soap_note_pdf_url, follow_up_questions, missing_sections, summary_for_whatsapp}`

**Scribe API endpoint (`scribe_router.py`):**
- `POST /scribe/consult` — HTTP interface for the scribe pipeline
- Accepts `ConsultationBundleRequest`, returns `ScribeResult`
- Deployment path: when services split to separate servers, set `JAMEEL_SCRIBE_URL` → this endpoint. No other code changes needed.

**Debug API:**
- `GET /debug/consultations` → all active ConsultationSession objects
- All existing Sprint 1 debug endpoints preserved

---

## 9. Sequence Diagram (Text Format)

### End-to-end appointment + consultation

```
Patient        Twilio        webhook_router      RouterAgent      BookingAgent     APScheduler      Doctor
   |              |                |                  |                |                |              |
   |---"I want appointment"------> |                  |                |                |              |
   |              |                |--router_graph.invoke()---------> |                |              |
   |              |                |                  |--intent_node--|                |              |
   |              |                |                  |    (Groq LLM) |                |              |
   |              |                |                  |--session_node-|                |              |
   |              |                |                  |--booking_dispatch_node-------> |              |
   |              |                |                  |                |--flow_node--> |              |
   |              |                |                  |                |   (GREETING→COLLECTING)      |
   | <--"What's your name?"------- |                  |                |                |              |
   |              |                |                  |                |                |              |
   [multiple turns: name, date, time, doctor]
   |              |                |                  |                |                |              |
   | <--"Confirm: Dr Jameel, tomorrow 10am"---------- |                |                |              |
   |---"Yes confirm"-------------> |                  |                |                |              |
   |              |                |--router_graph--> |--booking-----> |--confirm_node  |              |
   |              |                |                  |                |--request_doctor_approval()    |
   |              |                |                  |                |                |----APT001--> |
   | <--"Waiting for approval"---- |                  |                |                |              |
   |              |                |                  |                |                |              |
   |              |                |                  |                |    Doctor taps "Approve"      |
   |              |                | <--ButtonPayload=apt_approve:APT001------------------------------ |
   |              |                |--handle_doctor_message()          |                |              |
   |              |                |   appointment_approval._approve() |                |              |
   |              |                |   schedule_reminder(+2min)------> |                |              |
   |              |                |   schedule_no_show_check()------> |                |              |
   | <--"Appointment confirmed"--- |                  |                |                |              |
   |              |                |                  |                |                |              |
   [2 minutes later]
   |              |                |                  |                |--_send_reminder_job()         |
   | <--"Reminder: Dr Jameel in 2 minutes"----------- |                |                |              |
   |              |                |                  |                |                |              |
   [During appointment — patient sends message]
   |---"mujhe sir dard hai"------> |                  |                |                |              |
   |              |                |--router_graph--> |--intent:consultation_message    |              |
   |              |                |                  |--consultation_dispatch_node      |              |
   |              |                |                  |   start_or_resume_node           |              |
   |              |                |                  |   ConsultationSession created    |              |
   |              |                |                  |   schedule_consultation_timeout()|              |
   | <--"Message received — consultation in progress" |                |                |              |
   |              |                |                  |                |                |              |
   [Doctor sends voice note]
   |              |                | <--audio/ogg---------------------------------------------------------|
   |              |                |--handle_doctor_voice_note()       |                |              |
   |              |                |   _try_buffer_doctor_audio()      |                |              |
   |              |                |   finds active ConsultationSession|                |              |
   |              |                |   buffers audio_url               |                |              |
   | (no message to patient — audio silently buffered)                 |                |              |
   |              |                |    <---"🎙️ Voice note received..."----------------------->       |
   |              |                |                  |                |                |              |
   [Patient sends "ok done"]
   |---"ok done"-----------------> |                  |                |                |              |
   |              |                |--router_graph--> |--consultation_dispatch          |              |
   |              |                |                  |   detect_end: closing phrase    |              |
   |              |                |                  |   session.is_active = False     |              |
   |              |                |                  |   cancel_consultation_timeout() |              |
   |              |                |                  |   finalize_node                 |              |
   |              |                |                  |   finalize_and_send()           |              |
   |              |                |                  |   build_consultation_bundle()   |              |
   |              |                |                  |   _call_jameel()                |              |
   |              |                |                  |     scribe_service              |              |
   |              |                |                  |       download audio            |              |
   |              |                |                  |       Whisper transcribe        |              |
   |              |                |                  |       SOAP generation (LLaMA)   |              |
   |              |                |                  |       grounding check           |              |
   |              |                |                  |       follow-up questions       |              |
   |              |                |                  |       PDF (ReportLab)           |              |
   |              |                |                  |    <---{pdf_url, follow_ups, summary}-------->|
   |              |                |                  |   journey_state=POST_CONSULT    |              |
   |              |                |                  |   delete_consultation()         |              |
   | <--"Consultation recorded. Doctor will send prescriptions shortly."               |              |
```

---

## 10. API Documentation

### Health

**`GET /`**
- Returns: `{status, service, version, features: {classifier, whatsapp_webhook, booking_graph, scheduler}, endpoints: {...}}`
- Purpose: Feature flag check, endpoint discovery

**`GET /graph/nodes`**
- Returns: `{nodes, classifier_graph, booking_graph, description}`
- Purpose: Debug — shows compiled graph nodes

### WhatsApp

**`POST /webhook/twilio`** (Form parameters)
- Params: `From`, `Body`, `NumMedia`, `MediaUrl0`, `MediaContentType0`, `ButtonPayload`
- Returns: TwiML `<Response/>` (always 200 to Twilio)
- Purpose: Main Twilio webhook — all WhatsApp message handling

**`GET /webhook/twilio`**
- Returns: `{status: "ok", message: "..."}`
- Purpose: Twilio webhook health check

### Classification (direct HTTP)

**`POST /classify`**
- Body: `{"from_number": "+91...", "message": "..."}`
- Returns: `ClassifyResponse {intent, confidence, entities, bot_response, is_multi_intent, all_intents, raw_message, flagged_as_injection, pipeline_trace}`
- Purpose: Test classifier without WhatsApp

### Clinical Scribe API (Jameel-side)

**`POST /scribe/consult`**
- Body:
  ```json
  {
    "patient_id": "+919876543210",
    "doctor_id": "+919801581020",
    "messages": [
      {"sender_role": "patient", "text": "...", "audio_url": null, "timestamp": "..."},
      {"sender_role": "doctor",  "text": null,  "audio_url": "https://...", "timestamp": "..."}
    ],
    "audio_files": [{"url": "https://...", "duration_secs": null}]
  }
  ```
- Returns:
  ```json
  {
    "soap_note_pdf_url": "https://.../scribe/pdf/{id}",
    "follow_up_questions": ["How are you feeling?", "Are you taking the medicine?"],
    "missing_sections": [],
    "summary_for_whatsapp": "Suresh | Dx: Hypertension | Rx: Amlodipine 5mg OD"
  }
  ```
- Purpose: Full consultation-to-SOAP pipeline. Downloads + transcribes audio, generates SOAP note, returns PDF URL.
- Called by: `consultation_service._call_jameel()` — directly (in-process) when `JAMEEL_SCRIBE_URL` is empty, or via HTTP when URL is set.

### PDF downloads

**`GET /scribe/pdf/{document_id}`**
- Returns: PDF file (FileResponse)
- Status 404 if not found
- Purpose: Public URL for SOAP PDF (served to Twilio for doctor WhatsApp delivery)

**`GET /lab-report/pdf/{document_id}`**
- Returns: PDF file (FileResponse)
- Status 404 if not found
- Purpose: Lab report PDF download

### Debug endpoints

**`GET /debug/sessions`** — All active `BookingSession` objects from Redis
**`GET /debug/appointments`** — All `AppointmentRecord` objects
**`GET /debug/identity`** — Configured doctor phone numbers
**`GET /debug/pending-approvals`** — All pending appointment approval records
**`GET /debug/doctors`** — All saved doctor profiles
**`GET /debug/consultations`** — All active/recent `ConsultationSession` objects (Sprint 2)

---

## 11. Dependency Graph

```
main.py
├── app.api.classifier_router
│   └── app.graph.classifier
│       ├── app.schemas (ClassifierState, ClassifyRequest, ClassifyResponse)
│       └── app.prompts (CLASSIFIER_SYSTEM_PROMPT, CLASSIFIER_FEW_SHOT)
│
├── app.api.webhook_router
│   ├── app.graph.router (router_graph)
│   │   ├── app.graph.classifier (classifier_graph)
│   │   ├── app.graph.agents.after_hours_agent
│   │   │   └── app.services.store
│   │   ├── app.graph.agents.booking_agent
│   │   │   ├── app.services.store
│   │   │   ├── app.services.appointment_approval
│   │   │   │   ├── app.services.store
│   │   │   │   ├── app.services.whatsapp
│   │   │   │   ├── app.services.scheduler
│   │   │   │   └── app.services.google_calendar
│   │   │   └── app.prompts (BOOKING_ENTITY_PROMPT)
│   │   ├── app.graph.agents.emergency_agent
│   │   │   ├── app.services.identity
│   │   │   └── app.services.whatsapp
│   │   ├── app.graph.agents.lab_agent
│   │   ├── app.graph.agents.followup_agent
│   │   │   └── app.services.store
│   │   └── app.graph.agents.consultation_agent  ← lazy import
│   │       ├── app.services.store
│   │       ├── app.services.scheduler
│   │       ├── app.services.consultation_service
│   │       │   ├── app.services.store
│   │       │   ├── app.services.whatsapp
│   │       │   └── app.services.scribe_service  ← lazy import (when JAMEEL_SCRIBE_URL empty)
│   │       │       ├── app.graph.scribe.nodes (Groq Whisper, LLaMA)
│   │       │       ├── app.graph.scribe.pdf_builder (ReportLab)
│   │       │       ├── app.services.clinical_scribe (store_scribe_pdf)
│   │       │       └── app.services.identity (find_doctor_name)
│   │       └── app.schemas (ConsultationSession, ConsultationMessage)
│   │
│   ├── app.services.clinical_scribe
│   │   ├── app.graph.scribe.pipeline
│   │   │   ├── app.graph.scribe.nodes (Whisper, Groq)
│   │   │   ├── app.graph.scribe.state
│   │   │   └── app.graph.scribe.pdf_builder (ReportLab)
│   │   ├── app.services.store
│   │   ├── app.services.whatsapp
│   │   └── app.services.soap_approval
│   │       └── app.services.store
│   │
│   ├── app.services.pdf_service
│   │   ├── app.graph.parser.pipeline
│   │   │   ├── app.graph.parser.nodes (pdfplumber, Groq)
│   │   │   └── app.graph.parser.state
│   │   ├── app.services.store
│   │   └── app.services.whatsapp
│   │
│   ├── app.services.doctor
│   │   ├── app.services.appointment_approval
│   │   ├── app.services.soap_approval
│   │   ├── app.services.doctor_setup
│   │   │   └── app.services.store
│   │   └── app.services.whatsapp
│   │
│   └── app.services.identity
│
├── app.api.parser_router
│   └── app.graph.parser.pipeline
│
├── app.api.scribe_router
│   └── app.services.scribe_service
│
└── app.services.scheduler (lifespan startup)
    └── app.services.identity (for all_doctor_numbers())
```

**Circular import prevention:**
- `router.py` does NOT import `consultation_agent` at module level — import is inside `consultation_dispatch_node()` function body
- `scheduler.py` does NOT import `router_graph` at module level — import is inside `_flush_afterhours_job()` function body
- `consultation_service.py` does NOT import `scribe_service` at module level — import is inside `_call_jameel()` function body (only executed when a consultation ends)
- `scribe_service.py` does NOT import any agent or router modules — it only imports scribe nodes, identity, and clinical_scribe helpers

---

## 12. Missing Pieces / TODOs

### Critical for production

**1. ~~Jameel API integration~~ DONE — scribe pipeline is fully implemented locally**
`JAMEEL_SCRIBE_URL` is empty in `.env`. `consultation_service._call_jameel()` now calls `scribe_service.process_consultation_bundle()` directly — the full Whisper → SOAP → PDF pipeline runs locally. No stub. When Jameel's service is hosted independently, set `JAMEEL_SCRIBE_URL` to `POST /scribe/consult` and it switches to HTTP without any code changes. The `POST /scribe/consult` endpoint (`scribe_router.py`) is already live in the running app.

**2. Doctor-side consultation close not fully implemented**
`detect_end_node` in `consultation_agent.py` checks if the *incoming patient message* is a closing phrase. In the current implementation, closing a consultation via a doctor typing "ok done" goes through `handle_doctor_message()` → `doctor.py`, which does not route to `consultation_agent`. For demo, the patient sends the closing phrase. For production, doctor close should trigger `finalize_and_send()` directly from `doctor.py` or via a doctor consultation webhook branch.

**3. No persistence of MemorySaver across restarts**
`router_graph` uses in-process `MemorySaver()`. A server restart loses all LangGraph thread checkpoints. For production: replace with `langgraph.checkpoint.redis.RedisSaver` or `langgraph.checkpoint.sqlite.SqliteSaver`.

**4. Demo-mode `.env` values not reverted**
`REMINDER_MINUTES_BEFORE=2` (should be `120` in production) and `CONSULTATION_TIMEOUT_MINUTES=2` (should be `30` in production). Risk: 2-minute consultation timeout in prod would auto-close consultations after 2 minutes of silence.

**5. ngrok URL hardcoded in `.env`**
`PUBLIC_BASE_URL` is a specific ngrok URL that changes on every ngrok restart. PDF links in WhatsApp messages break when ngrok URL changes. For production: use a stable domain.

**6. No authentication on debug endpoints**
All `GET /debug/*` endpoints are publicly accessible. They return full session data, appointment records, and consultation content. Must be removed or gated behind auth for production.

### Functional gaps

**7. Multi-intent handling partially implemented**
`classifier_graph` returns `all_intents` and `is_multi_intent=True` when multiple intents are detected. `router.py` `route_after_session()` only routes on the primary (highest confidence) intent. Secondary intents are discarded.

**8. Follow-up questions not delivered to patient**
`finalize_and_send()` receives `follow_up_questions` from Jameel's stub/API and attaches them to the doctor summary, but does NOT send them to the patient or schedule a follow-up message. `FollowUpAgent` responds to `followup_query` intent but has no proactive delivery mechanism.

**9. Lab agent is a stub**
`lab_agent.py` only handles the case where `lab_report_share` intent fires but no PDF is attached. The actual `pdf_service.handle_incoming_pdf()` is called directly in `webhook_router.py` for PDF attachments and bypasses the router entirely.

**10. Google Calendar not tested**
`GOOGLE_CALENDAR_ENABLED=False` in `.env`. The `google_calendar.py` module implements OAuth2 flow for slot availability and event creation, but has never been run in this environment. `google_credentials.json` is required but not present.

**11. No rate limiting**
`POST /webhook/twilio` has no rate limiting. A malicious actor could flood the webhook with messages, consuming Groq API quota. Twilio does provide sender verification which partially mitigates this.

**12. Whisper transcription is synchronous in single-voice-note flow**
`_run_scribe_pipeline()` in `clinical_scribe.py` calls `scribe_pipeline.invoke()` synchronously inside an `async` function — this blocks the FastAPI event loop for large audio files. The new `scribe_service.py` (consultation bundle flow) already fixes this by wrapping `_transcribe_audio` with `asyncio.to_thread`. The fix should be backported to `clinical_scribe.py` as well.

**13. No `.gitignore` check for `.env`**
`.env` file contains live API keys (Groq, Gemini, Twilio). If committed to a public repository this would expose credentials.

**14. After-hours flush: no state recovery edge case**
`_flush_afterhours_job()` re-injects messages into `router_graph`. If the patient's `BookingSession` already has a doctor-approved appointment and they sent an after-hours message about a different topic, the re-injected message may route to the wrong sub-agent depending on current `journey_state`.

---

## 13. Questions About the Codebase

**Q1: Why does `router_graph` use `MemorySaver()` but `booking_agent_graph` does not?**

`router_graph` is the entry point for every patient message. Its `MemorySaver` checkpoint (keyed by `thread_id = patient phone number`) is what makes LangGraph aware of conversation continuity — `add_messages` on the state's `messages` field accumulates across turns. `booking_agent_graph` is a stateless sub-agent that receives a fully-populated `BookingState` dict from the router and processes one turn. Session persistence across turns for the booking agent is handled by the application-level `BookingSession` in Redis, not LangGraph checkpoints.

**Q2: Why is `consultation_agent_graph` imported lazily inside `consultation_dispatch_node()`?**

`router.py` imports `booking_agent_graph`, `emergency_agent_graph`, etc. at module level. `consultation_agent.py` imports `consultation_service.py` which imports `store.py` and `whatsapp.py`. If `router.py` imported `consultation_agent` at module level, the Python import system would form the chain `router → consultation_agent → consultation_service → store → schemas → ...`, which would work, but is deferred to avoid a potential circular import where a module in the chain imports back from `router.py` (specifically `scheduler.py`'s `_flush_afterhours_job` importing `router_graph`). The lazy import breaks this dependency at the one point where it could cycle.

**Q3: Why does `_consultation_timeout_job()` call `asyncio.run()` directly in the scheduler thread, while `finalize_node` in the agent uses `ThreadPoolExecutor`?**

APScheduler jobs run in a `BackgroundScheduler` thread pool — there is no running event loop in that thread, so `asyncio.run()` works directly. LangGraph nodes run in the FastAPI request context, where `asyncio.get_event_loop().is_running()` returns `True`. Calling `asyncio.run()` inside an already-running event loop raises `RuntimeError`. The `ThreadPoolExecutor` spawns a new thread (no running loop), where `asyncio.run()` works. The code at `consultation_agent.py:193–198` detects this case explicitly.

**Q4: What happens if two different patients are both in active consultation with the same doctor simultaneously, and the doctor sends a voice note?**

`_try_buffer_doctor_audio()` in `clinical_scribe.py` scans all `clinicai:consult:*` Redis keys and finds the first active session where `session.doctor_number == doctor_number`. If two patients are in active consultation with the same doctor, only the first match (Redis scan order, which is not deterministic) receives the buffered audio. This is a known limitation — the system assumes a doctor handles one consultation at a time.

**Q5: How is Twilio webhook authenticity verified?**

It is not verified in the current implementation. `webhook_router.py` accepts any POST to `/webhook/twilio` without signature validation. Twilio provides `X-Twilio-Signature` header for webhook authenticity. The `twilio` Python library has `RequestValidator` for this check. This should be added before production deployment.

**Q6: What is `APPOINTMENT_SLOT_CANDIDATES` in `.env` and where is it used?**

The `.env` file has `APPOINTMENT_SLOT_CANDIDATES=` (empty). This appears to be a configuration variable for predefined available time slots to suggest when calendar availability is checked (`suggest_google_slots()` in `google_calendar.py`). When empty, the system falls back to computing slots from the appointment duration and buffer time set in the doctor profile.

**Q7: What happens to the `all_intents` list in `ClassifyResponse` — is it used downstream?**

`classify_node` in `classifier.py` returns `all_intents: list[dict]` and `is_multi_intent: bool`. These are stored on `ClassifierState` and propagated through `postprocess_node`. In `router.py`'s `intent_node`, `all_intents` from the classifier result is not currently extracted into `BookingState`. `BookingState` has `extracted_entities` and `bot_response` but no `all_intents` field. Secondary intents are effectively lost at the router boundary. The `ClassifyResponse` returned by `POST /classify` does include all intents for API consumers.

**Q8: Why does `send_whatsapp_message_sync` exist alongside an async wrapper?**

Many call sites are inside synchronous LangGraph nodes (e.g., `emergency_agent.py`, `scheduler.py` job functions, `clinical_scribe._try_buffer_doctor_audio()`), where `await` cannot be used. `send_whatsapp_message_sync()` uses the synchronous `twilio.rest.Client` directly. The `async send_whatsapp_message()` wraps the sync version in `asyncio.get_event_loop().run_in_executor(None, ...)` for use in FastAPI route handlers.

**Q9: What is the relationship between `BookingSession.state` and `BookingSession.journey_state`?**

`state` is the granular booking sub-flow state — it tracks where in the appointment booking dialog the patient is (one of 10 `BOOKING_FLOW_STATES` like GREETING, COLLECTING_INFO, CONFIRM_SLOT). `journey_state` is the high-level patient lifecycle state — it tracks the patient's overall relationship with the clinic (one of 7 `PATIENT_JOURNEY_STATES` like NEW_PATIENT, BOOKED, CONSULTATION_ACTIVE, POST_CONSULT). The router uses `journey_state` for sub-agent dispatch. The booking agent uses `state` for internal dialog management.

**Q10: How does the context-aware classification work in practice?**

After every successful routing, `webhook_router.py` saves `reply_message[:300]` as `session.last_bot_response`. On the next message from the same patient, `intent_node` in the router reads `session.last_bot_response` and passes it as `context_message` to `classifier_graph`. The classifier's system prompt explicitly instructs the LLM: "If `context_message` is provided, use it to disambiguate the patient's reply." For example, if the bot asked "What time works for you?" and the patient replies "3pm", without context this could be classified as `general_query`. With context, it is correctly classified as `appointment_book` continuation with `requested_time="3pm"`.

---

*Report generated from live codebase. Verified against actual file contents at `D:\ClinicAI` on 2026-05-27.*
