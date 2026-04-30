import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import boto3
import requests as http_requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from supabase import Client

from agents.shared.gate_client import GateClient
from agents.shared.db_retry import execute_with_retry

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def build_youtube_service(token_dict: Optional[Dict] = None):
    """Build YouTube API service.

    If token_dict is provided (from Supabase), use it directly.
    Otherwise fall back to token file / CI env var.
    """
    if token_dict:
        creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("youtube", "v3", credentials=creds)

    token_path = Path(os.getenv("YOUTUBE_TOKEN_PATH", "config/youtube_token.json"))
    secrets_path = Path(os.getenv("YOUTUBE_CLIENT_SECRETS_PATH", "config/youtube_oauth_secrets.json"))

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
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


class YouTubeUploader:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client
        self._yt: Optional[object] = None  # built lazily per niche

    def _fetch_to_tempfile(self, url: str, suffix: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        dest = Path(tmp.name)
        if ".amazonaws.com/" in url:
            bucket = os.environ.get("AWS_S3_BUCKET", "")
            region = os.environ.get("REMOTION_REGION")
            key = url.split(".amazonaws.com/", 1)[1]
            boto3.client("s3", region_name=region).download_file(bucket, key, str(dest))
        else:
            resp = http_requests.get(url, timeout=300)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return dest

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
            try:
                thumb_media = MediaFileUpload(str(local_thumb), mimetype="image/jpeg")
                self._yt.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            except Exception as thumb_err:
                print(f"[uploader] thumbnail set skipped for {video_id}: {thumb_err}")

        local_video.unlink(missing_ok=True)
        if local_thumb:
            local_thumb.unlink(missing_ok=True)

        return video_id

    def _delete_supabase_assets(self, video: dict) -> None:
        """Delete voiceover, SRT, thumbnail, and b-roll from Supabase Storage."""

        def _remove(bucket: str, keys: List[str]) -> None:
            if not keys:
                return
            try:
                self._sb.storage.from_(bucket).remove(keys)
                for k in keys:
                    print(f"[uploader] deleted {bucket}/{k}")
            except Exception as e:
                print(f"[uploader] {bucket} cleanup FAILED — video record: {video}")
                raise

        def _key_from_url(url: Optional[str], bucket: str) -> Optional[str]:
            if not url:
                return None
            marker = f"/{bucket}/"
            idx = url.find(marker)
            return url[idx + len(marker):] if idx != -1 else None

        for field in ("audio_path", "srt_path"):
            key = _key_from_url(video.get(field), "voiceovers")
            if key:
                _remove("voiceovers", [key])

        key = _key_from_url(video.get("thumbnail_path"), "thumbnails")
        if key:
            _remove("thumbnails", [key])

        # B-roll count varies with number of [BROLL:] tags in the script — discover by prefix
        video_id = video.get("id", "")
        video_type = video.get("video_type", "")
        if video_id and video_type:
            prefix = f"broll_{video_id[:8]}_{video_type}_remotion_"
            try:
                items = self._sb.storage.from_("broll").list("", {"search": prefix})
                keys = [item["name"] for item in (items or []) if item.get("name", "").startswith(prefix)]
                _remove("broll", keys)
            except Exception as e:
                print(f"[uploader] broll list FAILED — video record: {video}")
                raise

    def _delete_s3_video(self, video_path: str) -> None:
        bucket = os.environ.get("AWS_S3_BUCKET")
        region = os.environ.get("REMOTION_REGION")
        if not bucket or ".amazonaws.com/" not in video_path:
            return
        key = video_path.split(".amazonaws.com/", 1)[1]
        try:
            boto3.client("s3", region_name=region).delete_object(Bucket=bucket, Key=key)
            print(f"[uploader] deleted s3://{bucket}/{key}")
        except Exception as e:
            print(f"[uploader] s3 cleanup failed (non-fatal): {e}")

    def _build_service_for_niche(self, niche_id: str) -> bool:
        """Load per-niche token from Supabase. Returns False if no channel linked."""
        niche_rows = execute_with_retry(
            self._sb.table("niches")
            .select("youtube_account_id, channel_state")
            .eq("id", niche_id)
            .limit(1)
        ).data
        if not niche_rows or niche_rows[0].get("channel_state") != "linked":
            return False
        account_id = niche_rows[0]["youtube_account_id"]
        account_rows = execute_with_retry(
            self._sb.table("youtube_accounts")
            .select("token_json, channel_id")
            .eq("id", account_id)
            .limit(1)
        ).data
        if not account_rows:
            return False
        channel_id = account_rows[0]["channel_id"]
        print(f"[uploader] niche {niche_id} → channel {channel_id}")
        token_dict = account_rows[0]["token_json"]
        self._yt = build_youtube_service(token_dict=token_dict)
        # Persist refreshed token back to Supabase
        creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._sb.table("youtube_accounts").update(
                {"token_json": json.loads(creds.to_json())}
            ).eq("id", account_id).execute()
        return True

    def _get_long_yt_id(self, script_id: str) -> Optional[str]:
        """Return the youtube_video_id of the uploaded long-form video for a script, if any."""
        rows = execute_with_retry(
            self._sb.table("videos")
            .select("youtube_video_id")
            .eq("script_id", script_id)
            .eq("video_type", "long")
            .not_.is_("youtube_video_id", "null")
            .limit(1)
        ).data
        return rows[0]["youtube_video_id"] if rows else None

    def process_approved_videos(self, niche_id: str) -> None:
        if not self._build_service_for_niche(niche_id):
            print(f"[uploader] niche {niche_id} has no linked YouTube channel — skipping upload")
            return

        videos = execute_with_retry(
            self._sb.table("videos")
            .select("*, scripts(youtube_title, youtube_description, youtube_tags)")
            .eq("niche_id", niche_id)
            .eq("gate6_state", "approved")
            .eq("status", "approved")
        ).data

        # Always upload longs before shorts so the link is available
        videos.sort(key=lambda v: 0 if v["video_type"] == "long" else 1)

        # Track long video IDs uploaded this run: script_id → youtube_video_id
        long_yt_ids: Dict[str, str] = {}

        for video in videos:
            script = video.get("scripts")
            if not script:
                print(f"[uploader] video {video['id']} has no linked script, skip")
                continue
            try:
                description = script["youtube_description"] or ""

                if video["video_type"] == "short":
                    long_yt_id = long_yt_ids.get(video["script_id"]) or self._get_long_yt_id(video["script_id"])
                    if long_yt_id:
                        link_line = f"Watch the full video: https://www.youtube.com/watch?v={long_yt_id}"
                        if "\n\n⚠️ DISCLAIMER:" in description:
                            pre, post = description.split("\n\n⚠️ DISCLAIMER:", 1)
                            description = pre.rstrip() + f"\n\n{link_line}\n\n⚠️ DISCLAIMER:" + post
                        else:
                            description = description.rstrip() + f"\n\n{link_line}"

                yt_id = self.upload(
                    video_path=video["video_path"],
                    thumbnail_path=video["thumbnail_path"],
                    title=script["youtube_title"],
                    description=description,
                    tags=script.get("youtube_tags", []),
                    is_short=video["video_type"] == "short",
                )

                if video["video_type"] == "long":
                    long_yt_ids[video["script_id"]] = yt_id

                execute_with_retry(
                    self._sb.table("videos").update(
                        {"youtube_video_id": yt_id, "status": "uploaded"}
                    ).eq("id", video["id"])
                )
                self._delete_s3_video(video["video_path"])
                self._delete_supabase_assets(video)
                print(f"[uploader] uploaded {yt_id} ({video['video_type']})")
            except Exception as e:
                print(f"[uploader] failed for video {video['id']}: {e}")
