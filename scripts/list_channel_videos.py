"""
List all videos on the YouTube channel linked to a niche, with their video IDs.
Usage: python3 -m scripts.list_channel_videos <niche_name_or_id>
"""
import sys
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from supabase import create_client
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_channel_videos(niche_query: str) -> None:
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))

    # Find niche by name or ID
    if len(niche_query) == 36 and niche_query.count("-") == 4:
        rows = execute_with_retry(
            sb.table("niches")
            .select("id, name, youtube_accounts(channel_id, token_json)")
            .eq("id", niche_query)
        ).data
    else:
        rows = execute_with_retry(
            sb.table("niches")
            .select("id, name, youtube_accounts(channel_id, token_json)")
            .ilike("name", f"%{niche_query}%")
        ).data

    if not rows:
        print(f"No niche found matching: {niche_query}")
        sys.exit(1)

    niche = rows[0]
    account = niche.get("youtube_accounts") or {}
    channel_id = account.get("channel_id")
    token_json = account.get("token_json")

    if not channel_id or not token_json:
        print(f"Niche '{niche['name']}' has no linked YouTube channel")
        sys.exit(1)

    print(f"Channel: {channel_id}  ({niche['name']})\n")

    creds = Credentials.from_authorized_user_info(token_json, SCOPES)
    yt = build("youtube", "v3", credentials=creds)

    # Get uploads playlist ID
    ch = yt.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_playlist = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Page through all videos
    videos = []
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]
            vid_id = snippet["resourceId"]["videoId"]
            title = snippet["title"]
            published = snippet["publishedAt"][:10]
            videos.append((published, title, vid_id))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos.sort(key=lambda x: x[0])

    print(f"{'Published':<12} {'Title':<65} {'Video ID'}")
    print("-" * 95)
    for published, title, vid_id in videos:
        print(f"{published:<12} {title[:64]:<65} {vid_id}")

    print(f"\n{len(videos)} videos total")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m scripts.list_channel_videos <niche_name_or_id>")
        sys.exit(1)
    get_channel_videos(" ".join(sys.argv[1:]))
