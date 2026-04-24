"""Run once locally to generate a fresh YouTube OAuth token with updated scopes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

SECRETS = Path("config/youtube_oauth_secrets.json")
TOKEN = Path("config/youtube_token.json")

if TOKEN.exists():
    TOKEN.unlink()

flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS), SCOPES)
creds = flow.run_local_server(port=0)
TOKEN.write_text(creds.to_json())

print("\n=== Copy everything between the lines into YOUTUBE_TOKEN_JSON ===\n")
print("---")
print(TOKEN.read_text())
print("---")
