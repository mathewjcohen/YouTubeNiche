"""
Cross-reference published_videos rows against the actual YouTube channel
and delete any rows whose video has been removed from YouTube.

Usage:
  python3 scripts/purge_removed_videos.py                        # dry run (safe)
  python3 scripts/purge_removed_videos.py --execute              # actually delete
  python3 scripts/purge_removed_videos.py --channel <channel_id> # specific channel only
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from supabase import create_client

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_channel_video_ids(youtube) -> set[str]:
    """Return all video IDs currently in the channel's uploads playlist."""
    # Get the uploads playlist ID for this channel
    ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids: set[str] = set()
    page_token = None
    while True:
        pl_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in pl_resp.get("items", []):
            video_ids.add(item["contentDetails"]["videoId"])
        page_token = pl_resp.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete rows (default: dry run)")
    parser.add_argument("--channel", help="Only process this channel_id (default: all channels)")
    args = parser.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    # Load all youtube_accounts (optionally filtered)
    query = sb.table("youtube_accounts").select("id, channel_id, token_json")
    if args.channel:
        query = query.eq("channel_id", args.channel)
    accounts = query.execute().data

    total_removed = 0

    for account in accounts:
        channel_id = account["channel_id"]
        token_json = account["token_json"]
        print(f"\n--- Channel: {channel_id} ---")

        # Build YouTube service for this account
        creds = Credentials.from_authorized_user_info(token_json, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds)

        # Get all video IDs currently on YouTube
        live_ids = get_channel_video_ids(youtube)
        print(f"  YouTube: {len(live_ids)} videos currently live")

        # Get all published_videos rows for this channel's niches
        niches = sb.table("niches").select("id").eq("youtube_account_id", account["id"]).execute().data
        niche_ids = [n["id"] for n in niches]
        if not niche_ids:
            print("  No niches linked — skipping")
            continue

        db_rows = sb.table("published_videos").select("id, youtube_video_id, video_type, niche_id") \
            .in_("niche_id", niche_ids).execute().data
        print(f"  DB: {len(db_rows)} published_videos rows")

        # Find rows whose video_id is not on YouTube anymore
        orphaned = [r for r in db_rows if r["youtube_video_id"] not in live_ids]
        print(f"  Orphaned (removed from YouTube): {len(orphaned)}")

        for r in orphaned:
            print(f"    {'DELETE' if args.execute else 'WOULD DELETE'} published_videos row {r['id']} "
                  f"({r['video_type']}) yt={r['youtube_video_id']}")

        if args.execute and orphaned:
            orphaned_ids = [r["id"] for r in orphaned]
            sb.table("published_videos").delete().in_("id", orphaned_ids).execute()
            print(f"  Deleted {len(orphaned)} rows")

        total_removed += len(orphaned)

    print(f"\n{'Deleted' if args.execute else 'Would delete'} {total_removed} total orphaned rows.")
    if not args.execute:
        print("Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
