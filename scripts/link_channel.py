"""
Link a YouTube Brand Account to a niche.

Usage:
  python3 scripts/link_channel.py --niche "Insurance Explained"

Runs an interactive OAuth flow, fetches the channel's ID and handle from
the YouTube API, then stores the token in Supabase and marks the niche as
channel_state='linked'.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from supabase import create_client

from agents.shared.config_loader import get_env

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

SECRETS_PATH = Path(os.getenv("YOUTUBE_CLIENT_SECRETS_PATH", "config/youtube_oauth_secrets.json"))


def run_oauth() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_PATH), SCOPES)
    return flow.run_local_server(port=0)


def fetch_channel_info(creds: Credentials) -> tuple[str, str, str]:
    yt = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for this account. Create a Brand Account first.")
    channel = items[0]
    channel_id = channel["id"]
    snippet = channel["snippet"]
    handle = snippet.get("customUrl", "")
    title = snippet.get("title", "")
    return channel_id, handle, title


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", required=True, help="Exact niche name, e.g. 'Insurance Explained'")
    args = parser.parse_args()

    sb = create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))

    # Resolve niche
    result = sb.table("niches").select("id, name, channel_state").ilike("name", args.niche).limit(1).execute()
    if not result.data:
        all_niches = sb.table("niches").select("name, status").order("name").execute()
        names = [f"  {r['name']} ({r['status']})" for r in all_niches.data]
        print(f"[error] No niche found matching '{args.niche}'. Available niches:")
        print("\n".join(names))
        sys.exit(1)
    niche = result.data[0]

    print(f"\nLinking channel for niche: {niche['name']}")
    print("Opening browser for YouTube OAuth...\n")

    creds = run_oauth()
    channel_id, handle, channel_title = fetch_channel_info(creds)

    token_dict = json.loads(creds.to_json())

    # Upsert youtube_accounts row
    account_result = (
        sb.table("youtube_accounts")
        .upsert(
            {
                "channel_id": channel_id,
                "channel_name": channel_title,
                "handle": handle,
                "token_json": token_dict,
            },
            on_conflict="channel_id",
        )
        .execute()
    )
    account_id = account_result.data[0]["id"]

    # Update niche
    sb.table("niches").update({
        "youtube_account_id": account_id,
        "channel_state": "linked",
    }).eq("id", niche["id"]).execute()

    print(f"[ok] Channel linked!")
    print(f"     Channel Name : {channel_title}")
    print(f"     Channel ID   : {channel_id}")
    print(f"     Handle       : {handle}")
    print(f"     Account ID   : {account_id}")
    print(f"     Niche        : {niche['name']}")


if __name__ == "__main__":
    main()
