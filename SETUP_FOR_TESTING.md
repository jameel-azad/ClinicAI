# ClinicAI — Tester Setup Guide

This document walks you through setting up ClinicAI locally for end-to-end testing, including the WhatsApp bot, backend API, and management dashboard.

---

## Table of Contents

1. [What You're Testing](#1-what-youre-testing)
2. [Prerequisites](#2-prerequisites)
3. [Get the Code](#3-get-the-code)
4. [Environment Configuration](#4-environment-configuration)
5. [Run the Stack](#5-run-the-stack)
6. [Twilio WhatsApp Setup](#6-twilio-whatsapp-setup)
7. [Seed Initial Data](#7-seed-initial-data)
8. [Testing Flows](#8-testing-flows)
9. [Debug Endpoints](#9-debug-endpoints)
10. [Common Issues](#10-common-issues)

---

## 1. What You're Testing

ClinicAI is a multi-tenant AI front-desk system for clinics, built on WhatsApp. It has three layers:

| Layer | What it does | How to access |
|---|---|---|
| **WhatsApp Bot** | Patient-facing appointment booking, consultation, emergencies | Via Twilio sandbox (WhatsApp) |
| **Doctor Bot** | Doctor receives appointment approvals, SOAP note review on WhatsApp | Via Twilio sandbox (WhatsApp) |
| **Dashboard** | Web UI for clinic admins to manage doctors, patients, AI config | `http://localhost:3000` |

---

## 2. Prerequisites

Install the following before starting:

| Tool | Version | Download |
|---|---|---|
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop |
| Python | 3.11+ | https://www.python.org/downloads/ |
| Node.js | 18+ | https://nodejs.org/ |
| ngrok | Latest | https://ngrok.com/download |
| Git | Any | https://git-scm.com/ |

**Accounts needed:**

- **Twilio** — Free trial account at https://www.twilio.com/try-twilio
- **Groq** — Free API key at https://console.groq.com (used for LLM + speech-to-text)

> **Note:** Gemini API key is optional but improves the intent classifier. Get one free at https://aistudio.google.com/app/apikey

---

## 3. Get the Code

```bash
git clone <repo-url>
cd ClinicAI
```

---

## 4. Environment Configuration

### 4.1 Copy the example env file

```bash
cp .env.example .env
```

### 4.2 Generate required secret keys

**SECRET_KEY** (JWT signing, 32+ characters):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**ENCRYPTION_KEY** (Fernet key for encrypting API keys in the DB):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> If `cryptography` is not installed yet: `pip install cryptography`

### 4.3 Fill in `.env`

Open `.env` and set these values:

```env
# ── Database & Cache ──────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://clinicai:password@localhost:5432/clinicai
REDIS_URL=redis://localhost:6379

# ── Secrets (paste your generated values here) ───────────────
SECRET_KEY=<paste-your-32-char-key>
ENCRYPTION_KEY=<paste-your-fernet-key>

# ── LLM (Required) ────────────────────────────────────────────
GROQ_API_KEY=<your-groq-api-key>
GROQ_MODEL=llama-3.3-70b-versatile
WHISPER_MODEL=whisper-large-v3

# ── LLM (Optional but recommended) ───────────────────────────
GEMINI_API_KEY=<your-gemini-api-key>

# ── Twilio WhatsApp ───────────────────────────────────────────
TWILIO_ACCOUNT_SID=<your-account-sid>
TWILIO_AUTH_TOKEN=<your-auth-token>
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# ── Clinic Defaults ───────────────────────────────────────────
CLINIC_OPEN_HOUR=9
CLINIC_CLOSE_HOUR=20

# ── Demo Timing (keep short for testing) ─────────────────────
REMINDER_MINUTES_BEFORE=2
CONSULTATION_TIMEOUT_MINUTES=2
FOLLOWUP_DEFAULT_DAYS=2

# ── Development ───────────────────────────────────────────────
DEBUG_ENDPOINTS=true
PUBLIC_BASE_URL=http://localhost:8000    # updated automatically by dev_start.py
```

### 4.4 Where to find Twilio credentials

1. Log in to https://console.twilio.com
2. On the home page, copy **Account SID** and **Auth Token**
3. `TWILIO_WHATSAPP_FROM` stays as `whatsapp:+14155238886` (Twilio sandbox number)

---

## 5. Run the Stack

Choose **Option A** (Docker, easiest) or **Option B** (Local, for active development).

---

### Option A — Full Docker Compose (Recommended for testers)

This starts PostgreSQL, Redis, the API, and the dashboard in one command.

```bash
docker compose up --build
```

Wait for the log line:
```
Application startup complete.
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Dashboard | http://localhost:3000 |

> **Windows note:** If Docker can't bind port 5432, stop any local PostgreSQL service first.

To stop:
```bash
docker compose down
```

To stop and wipe the database:
```bash
docker compose down -v
```

---

### Option B — Local (Without Docker for API)

**Step 1 — Start data services via Docker:**

```bash
docker compose up postgres redis -d
```

**Step 2 — Backend:**

```bash
python -m venv venv
.\venv\Scripts\activate          # Windows
# source venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Step 3 — Dashboard:**

```bash
cd dashboard
npm install
npm run dev
```

**Step 4 — Expose to internet (needed for Twilio webhook):**

```bash
# In a new terminal, from the project root:
python dev_start.py
```

This starts ngrok, writes the public URL to `.env`, and prints your Twilio webhook URL:
```
Webhook URL: https://xxxx.ngrok-free.app/webhook/twilio
```

Copy that URL — you'll need it in the next section.

---

## 6. Twilio WhatsApp Setup

Twilio uses a sandbox number for testing. You need to:

1. Register your phone number with the sandbox
2. Point the webhook at your running server

### 6.1 Join the Twilio sandbox

1. Go to https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
2. Follow the on-screen instructions — send a WhatsApp message like `join <your-keyword>` to `+1 415 523 8886`
3. You'll get a confirmation: *"You are now connected to the sandbox"*

### 6.2 Set the webhook URL

1. In Twilio Console, go to **Messaging → Try it out → Send a WhatsApp message**
2. Under **Sandbox settings**, set:
   - **When a message comes in:** `https://xxxx.ngrok-free.app/webhook/twilio` (your ngrok URL + `/webhook/twilio`)
   - Method: `HTTP POST`
3. Save.

> **Every time you restart `dev_start.py`, the ngrok URL changes.** Update the Twilio webhook URL each time.

### 6.3 Register a doctor's number

For the doctor flows to work, the doctor's WhatsApp number must be registered in the system. This is done through the dashboard (see Section 7).

---

## 7. Seed Initial Data

Before testing, you need at least one clinic, one doctor, and the dashboard login.

### 7.1 Create a dashboard account

Open http://localhost:3000 and register a new account (or use the signup API at `POST /api/auth/signup`).

### 7.2 Create a clinic

In the dashboard, go through the **Clinic Setup Wizard**:

1. **Clinic Details** — Name, timezone, working hours
2. **Twilio Number** — Enter `+14155238886` (the sandbox number)
3. **AI Config** — Enter your Groq API key; select `llama-3.3-70b-versatile`
4. **Doctor Setup** — Add at least one doctor with their WhatsApp number (your test phone)
5. **Review & Save**

### 7.3 Verify setup via health check

```bash
curl http://localhost:8000/
```

Expected response includes:
```json
{
  "status": "healthy",
  "features": { ... }
}
```

---

## 8. Testing Flows

All WhatsApp tests are done by sending messages from your phone to the Twilio sandbox number (`+1 415 523 8886`).

> **Tip:** Use two phones — one as the "patient", one as the "doctor". Or use separate WhatsApp accounts on the same phone.

---

### Flow 1 — Patient Books an Appointment

Send these messages **as the patient** to `+1 415 523 8886`:

| Step | Message to send | Expected bot reply |
|---|---|---|
| 1 | `Hello` or `I want to book an appointment` | Greeting + asks for name/details |
| 2 | Provide name when asked | Confirmation, lists available doctors |
| 3 | Select a doctor (by number or name) | Shows available slots |
| 4 | Pick a time slot | Asks for confirmation |
| 5 | `Yes` to confirm | "Appointment requested, waiting for doctor approval" |

**As the doctor** (on the other phone):
- You receive a WhatsApp message with appointment details and two buttons: **Approve** / **Decline**
- Tap **Approve**

**Back as the patient:**
- You receive: "Your appointment has been confirmed for [date/time]"

---

### Flow 2 — Patient Cancels an Appointment

| Step | Message | Expected |
|---|---|---|
| 1 | `Cancel my appointment` | Lists upcoming appointments |
| 2 | Confirm cancellation | "Your appointment has been cancelled" |

---

### Flow 3 — Emergency

| Step | Message | Expected |
|---|---|---|
| 1 | `I'm having chest pain` or `Emergency` | Immediate response with 112 instructions + notifies doctor |

---

### Flow 4 — Doctor Approves SOAP Note (After Consultation)

After a consultation is completed, the doctor receives a SOAP note PDF on WhatsApp with approval buttons.

- Tap **Approve** to finalize the record
- Tap **Reject** to discard and redo

Or send text commands:
- `APPROVE RX<id>` — approve
- `REJECT RX<id>` — reject

---

### Flow 5 — Dashboard Testing

Open http://localhost:3000 and verify:

| Page | What to check |
|---|---|
| Patients list | Patient created by WhatsApp flow appears here |
| Patient detail | Medical history timeline, contact info |
| Doctors | Add / edit / deactivate a doctor |
| AI Config | Save API key, click "Test Connection" → should return green |
| Lab Reports | Upload a PDF and check parsed results |

---

### Flow 6 — After Hours

Set `CLINIC_OPEN_HOUR` and `CLINIC_CLOSE_HOUR` in `.env` so the current time is outside working hours (e.g., set `CLINIC_OPEN_HOUR=23`). Restart the server.

Send any booking message — the bot should respond: *"We're currently closed. Your message has been noted and a doctor will get back to you during working hours."*

---

## 9. Debug Endpoints

When `DEBUG_ENDPOINTS=true` is set in `.env`, these read-only endpoints are available:

| Endpoint | What it shows |
|---|---|
| `GET /debug/sessions` | All active booking sessions (Redis) |
| `GET /debug/appointments` | All confirmed appointments |
| `GET /debug/identity` | Registered doctor phone numbers |
| `GET /debug/pending-approvals` | Appointment approvals waiting for doctor |
| `GET /debug/doctors` | Saved doctor profiles |
| `GET /debug/consultations` | Active and recent consultation sessions |

Example:
```bash
curl http://localhost:8000/debug/sessions
```

> These endpoints require a valid JWT token. Get one from `POST /api/auth/login` first, then pass it as `Authorization: Bearer <token>`.

---

## 10. Common Issues

### Bot doesn't respond to WhatsApp messages

- Check that the ngrok URL in Twilio's sandbox settings matches your current ngrok session
- Check the API logs: `docker compose logs api -f` or your terminal running uvicorn
- Make sure a clinic with `twilio_number = +14155238886` exists in the database

### `ENCRYPTION_KEY` error on startup

- Make sure the value in `.env` is a valid Fernet key (44 characters, ends with `=`)
- Regenerate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Database connection refused

- Make sure Docker is running: `docker compose up postgres redis -d`
- For local setup, verify `DATABASE_URL` uses `localhost:5432` not `postgres:5432`

### ngrok URL keeps changing

- ngrok free tier generates a new URL on every restart
- After restarting `dev_start.py`, update the webhook URL in Twilio Console (Section 6.2)
- Alternatively, sign up for a free ngrok account and use a static domain

### Dashboard shows blank / API errors

- Check that `NEXT_PUBLIC_API_URL` in the dashboard matches your API address
- For Docker: it should be `http://localhost:8000`
- Check browser console for CORS errors

### LLM responses are slow or failing

- Verify `GROQ_API_KEY` is valid at https://console.groq.com
- Check rate limits — free Groq tier has limits per minute
- Fallback: set `GEMINI_API_KEY` in `.env` as backup

---

## Quick Reference

| Thing | Value |
|---|---|
| Twilio sandbox number | `+1 415 523 8886` |
| API URL | `http://localhost:8000` |
| API Docs | `http://localhost:8000/docs` |
| Dashboard | `http://localhost:3000` |
| Health check | `GET http://localhost:8000/health` |
| Twilio Console | https://console.twilio.com |

---

*For questions, contact the developer on the project channel.*
