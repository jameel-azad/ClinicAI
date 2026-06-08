# Deploying ClinicAI to a single VPS

Full stack — FastAPI API + Next.js dashboard + Postgres + Redis + Caddy
(automatic HTTPS) — on one small server via Docker Compose.

No custom domain is needed: we use **sslip.io**, which turns your server's IP
into a hostname (`api.<IP>.sslip.io`) so Caddy can issue free Let's Encrypt
certificates. Swap to a real domain later by changing two lines in `.env`.

---

## ⚠️ Before you start: rotate secrets

The committed-locally `.env` contains live Groq, Gemini, and Twilio credentials.
**Rotate all three** before going live and put the new values only in the
server's `.env` (it is gitignored and never enters a Docker image):

- Groq API key — https://console.groq.com/keys
- Gemini API key — https://aistudio.google.com/apikey
- Twilio auth token — Twilio Console → Account → API keys & tokens

---

## A. Provision the server (one-time)

1. Create a VPS — Hetzner CX22 (~€4/mo) or DigitalOcean basic droplet, **Ubuntu 24.04**.
   Note its **public IPv4** (call it `<IP>`, e.g. `203.0.113.5`).
2. SSH in and install Docker + the compose plugin:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Allow only SSH + web traffic:
   ```bash
   ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable
   ```

## B. Get the code & secrets onto the server

4. Clone the repo:
   ```bash
   git clone <your-repo-url> clinicai && cd clinicai
   ```
5. Create the env file from the template and edit it:
   ```bash
   cp .env.example .env
   nano .env
   ```
   Set every value, paying attention to (replace `203.0.113.5` with your `<IP>`,
   keeping the dots):
   - `API_HOST=api.203.0.113.5.sslip.io`
   - `APP_HOST=app.203.0.113.5.sslip.io`
   - `NEXT_PUBLIC_API_URL=https://api.203.0.113.5.sslip.io`
   - `PUBLIC_BASE_URL=https://api.203.0.113.5.sslip.io`
   - `DASHBOARD_URL=https://app.203.0.113.5.sslip.io`
   - `POSTGRES_PASSWORD=` a strong password
   - `DATABASE_URL=` use the same password (compose also injects this automatically)
   - `SECRET_KEY=` ≥32 random chars
   - `ENCRYPTION_KEY=` generate with:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - The **rotated** `GROQ_API_KEY`, `GEMINI_API_KEY`, `TWILIO_AUTH_TOKEN`, plus the
     other `TWILIO_*` values and content SIDs.
6. Upload the Google OAuth files (they're gitignored, so copy them manually from
   your machine):
   ```bash
   scp google_credentials.json google_token.json root@<IP>:~/clinicai/
   ```

## C. Launch

7. Build and start everything:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
8. Watch the API come up:
   ```bash
   docker compose -f docker-compose.prod.yml logs -f api
   ```
   Expect: DB tables created, "APScheduler ready", "Loaded N doctor(s) from DB".
   Caddy may take 10–30s to obtain TLS certs on first run.

## D. Wire up external services

9. **Twilio** Console → your WhatsApp sender/sandbox → set the inbound webhook to:
   ```
   https://api.<IP>.sslip.io/webhook/twilio
   ```
10. **Google Calendar** — if the uploaded token has expired, re-auth (run locally,
    then re-upload `google_token.json`):
    ```bash
    python scripts/google_calendar_auth.py
    ```

## E. Verify

- `curl https://api.<IP>.sslip.io/health` → `{"status":"ok", ...}` with feature flags true.
- Open `https://app.<IP>.sslip.io` → dashboard loads; sign up / log in works; browser
  network calls go to `https://api.<IP>.sslip.io` with no CORS errors.
- Persistence: `docker compose -f docker-compose.prod.yml restart api`, then confirm
  your clinic/doctors are still there.
- WhatsApp end-to-end: message the Twilio number → bot replies; complete a scribe/lab
  flow → the returned PDF link downloads.
- No leaked secrets in the image:
  `docker compose -f docker-compose.prod.yml exec api ls /app` shows **no** `.env` or `.venv`.

---

## Updating after a code change

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## Database schema changes

Fresh deploys get their full schema from the app's startup `create_all`. The single
Alembic migration is an `ALTER` for **pre-existing** databases only and is **not** run
at container start (it would fail on a fresh DB where the table doesn't exist yet). If
you are upgrading an older DB that predates the `google_calendar_id` column, run it once
manually:
```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```
For future schema changes, prefer adding Alembic migrations and stamping the baseline
(`alembic stamp head`) so create_all and Alembic stay consistent.

## Moving to a real domain later

1. Point `A` records `api.yourclinic.com` and `app.yourclinic.com` at `<IP>`.
2. In `.env`, change `API_HOST`/`APP_HOST` to the new hostnames and the three full
   URLs (`NEXT_PUBLIC_API_URL`, `PUBLIC_BASE_URL`, `DASHBOARD_URL`).
3. `docker compose -f docker-compose.prod.yml up -d --build` and update the Twilio webhook.

## Backups (recommended follow-up)

```bash
# Daily Postgres dump (add to cron):
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U clinicai clinicai > backup_$(date +%F).sql
```
The `generated_data` Docker volume holds generated PDFs — include it in your backup routine.

## Local development (unchanged)

The original `docker-compose.yml` still works for local dev (direct ports, no TLS).
Use `docker-compose.prod.yml` only on the server.
