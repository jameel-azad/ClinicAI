from pathlib import Path
import os

from dotenv import load_dotenv

from app.services.google_calendar import SCOPES

load_dotenv()


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise SystemExit(
            "Missing google-auth-oauthlib. Run: pip install -r requirements.txt"
        ) from exc

    credentials_file = Path(os.getenv("GOOGLE_CALENDAR_CREDENTIALS_FILE", "google_credentials.json"))
    token_file = Path(os.getenv("GOOGLE_CALENDAR_TOKEN_FILE", "google_token.json"))

    if not credentials_file.exists():
        raise SystemExit(
            f"Credentials file not found: {credentials_file}\n"
            "Download OAuth client credentials from Google Cloud Console and save it there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"Google Calendar token saved to {token_file}")


if __name__ == "__main__":
    main()
