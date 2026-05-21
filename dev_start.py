import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = 8000
ENV_FILE = Path(".env")


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_ngrok_url(retries: int = 20, delay: float = 1.0) -> str | None:
    """Poll ngrok's local dashboard API until the HTTPS tunnel URL appears."""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
                data = json.loads(resp.read())
                for tunnel in data.get("tunnels", []):
                    if tunnel.get("proto") == "https":
                        return tunnel["public_url"].rstrip("/")
        except Exception:
            pass
        print(f"  Waiting for ngrok... ({attempt}/{retries})")
        time.sleep(delay)
    return None


def update_env_key(key: str, value: str) -> None:
    """Update an existing key or append a new one in .env."""
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = content.splitlines()
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.split("=")[0].strip()
        if stripped == key:
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def banner(title: str, lines: list[str]) -> None:
    width = max(len(l) for l in [title] + lines) + 4
    print("\n" + "=" * width)
    print(f"  {title}")
    print("-" * width)
    for line in lines:
        print(f"  {line}")
    print("=" * width + "\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Start ngrok
    print("Starting ngrok tunnel on port", PORT, "...")
    ngrok_proc = subprocess.Popen(
        ["ngrok", "http", str(PORT), "--log=stdout"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 2. Get public URL
    public_url = get_ngrok_url()
    if not public_url:
        ngrok_proc.terminate()
        print("\nERROR: Could not get ngrok URL after waiting.")
        print("Possible fixes:")
        print("  1. Authenticate ngrok:  ngrok config add-authtoken <token>")
        print("     (Get free token at https://dashboard.ngrok.com)")
        print("  2. Make sure port 4040 isn't blocked")
        sys.exit(1)

    # 3. Write to .env
    update_env_key("PUBLIC_BASE_URL", public_url)
    print(f"Updated .env  →  PUBLIC_BASE_URL={public_url}")

    # 4. Print setup info for Twilio console
    banner(
        "TWILIO SETUP — paste these URLs in your Twilio Sandbox",
        [
            f"Webhook (incoming messages):  {public_url}/webhook/twilio",
            f"Status callback (optional):   {public_url}/webhook/twilio",
            "",
            "Twilio console:  https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn",
        ],
    )

    # 5. Start uvicorn
    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn",
        "main:app",
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--reload",
    ]
    print(f"Starting FastAPI on http://localhost:{PORT}\n")
    try:
        subprocess.run(uvicorn_cmd)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down ngrok...")
        ngrok_proc.terminate()
        ngrok_proc.wait()
        print("Done.")


if __name__ == "__main__":
    main()
