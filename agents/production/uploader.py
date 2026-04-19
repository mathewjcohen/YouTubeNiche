import os
import tempfile
from pathlib import Path
from typing import List

import requests as http_requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from supabase import Client

from agents.shared.gate_client import GateClient
from agents.shared.db_retry import execute_with_retry

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def build_youtube_service():
    token_path = Path(os.getenv("YOUTUBE_TOKEN_PATH", "config/youtube_token.json"))
    secrets_path = Path(os.getenv("YOUTUBE_CLIENT_SECRETS_PATH", "config/youtube_oauth_secrets.json"))

    # In CI: token JSON is provided via env var
    token_json_env = os.getenv("YOUTUBE_TOKEN_JSON")
    if token_json_env and not token_path.exists():
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token_json_env)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Interactive flow — only works locally
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


class YouTubeUploader:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client
        self._yt = build_youtube_service()

    def _fetch_to_tempfile(self, url: str, suffix: str) -> Path:
        resp = http_requests.get(url, timeout=300)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(resp.content)
        tmp.close()
        return Path(tmp.name)

    def upload(
        self,
        video_path: str,
        thumbnail_path: str,
        title: str,
        description: str,
        tags: List[str],
        is_short: bool = False,
    ) -> str:
        local_video = self._fetch_to_tempfile(video_path, ".mp4")
        local_thumb = self._fetch_to_tempfile(thumbnail_path, ".jpg") if thumbnail_path else None

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(str(local_video), chunksize=-1, resumable=True, mimetype="video/mp4")
        request = self._yt.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]

        if local_thumb:
            thumb_media = MediaFileUpload(str(local_thumb), mimetype="image/jpeg")
            self._yt.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()

        local_video.unlink(missing_ok=True)
        if local_thumb:
            local_thumb.unlink(missing_ok=True)

        return video_id

    def process_approved_videos(self, niche_id: str) -> None:
        videos = execute_with_retry(
            self._sb.table("videos")
            .select("*, scripts(youtube_title, youtube_description, youtube_tags)")
            .eq("niche_id", niche_id)
            .eq("gate6_state", "approved")
            .eq("status", "approved")
        ).data
        for video in videos:
            script = video.get("scripts")
            if not script:
                print(f"[uploader] video {video['id']} has no linked script, skip")
                continue
            try:
                yt_id = self.upload(
                    video_path=video["video_path"],
                    thumbnail_path=video["thumbnail_path"],
                    title=script["youtube_title"],
                    description=script["youtube_description"],
                    tags=script.get("youtube_tags", []),
                    is_short=video["video_type"] == "short",
                )
                execute_with_retry(
                    self._sb.table("videos").update(
                        {"youtube_video_id": yt_id, "status": "uploaded"}
                    ).eq("id", video["id"])
                )
                print(f"[uploader] uploaded {yt_id} ({video['video_type']})")
            except Exception as e:
                print(f"[uploader] failed for video {video['id']}: {e}")
