"""Retry setting thumbnails for published videos where the initial set failed.

Triggered manually via workflow_dispatch after quota resets (next calendar day).
Queries published_videos rows where thumbnail_path IS NOT NULL, attempts to set
the thumbnail on YouTube, then clears the field and deletes the stored file.
"""

from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.uploader import YouTubeUploader, _is_quota_exceeded


def main() -> None:
    print("[thumbnail_retry] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)

    rows = execute_with_retry(
        sb.table("published_videos")
        .select("id, niche_id, youtube_video_id, thumbnail_path, video_type")
        .not_.is_("thumbnail_path", "null")
    ).data

    if not rows:
        print("[thumbnail_retry] no pending thumbnail retries")
        return

    print(f"[thumbnail_retry] {len(rows)} video(s) need thumbnail retry")

    uploader = YouTubeUploader(supabase=sb, gate_client=gate)
    current_niche: str = ""

    for row in rows:
        niche_id = row["niche_id"]
        yt_id = row["youtube_video_id"]
        thumb_url = row["thumbnail_path"]

        if niche_id != current_niche:
            if not uploader._build_service_for_niche(niche_id):
                print(f"[thumbnail_retry] niche {niche_id[:8]} has no linked channel — skipping")
                continue
            current_niche = niche_id

        print(f"[thumbnail_retry] setting thumbnail for {yt_id} ({row['video_type']})")
        try:
            local_thumb = uploader._fetch_to_tempfile(thumb_url, ".jpg")
            from googleapiclient.http import MediaFileUpload
            thumb_media = MediaFileUpload(str(local_thumb), mimetype="image/jpeg")
            uploader._yt.thumbnails().set(videoId=yt_id, media_body=thumb_media).execute()
            local_thumb.unlink(missing_ok=True)

            # Clear the retry field and delete the source file
            execute_with_retry(
                sb.table("published_videos")
                .update({"thumbnail_path": None})
                .eq("id", row["id"])
            )
            uploader._delete_s3_video(thumb_url)
            # If it was in Supabase storage, delete via storage API
            if ".amazonaws.com/" not in thumb_url:
                marker = "/thumbnails/"
                idx = thumb_url.find(marker)
                if idx != -1:
                    key = thumb_url[idx + len(marker):]
                    try:
                        sb.storage.from_("thumbnails").remove([key])
                        print(f"[thumbnail_retry] deleted thumbnails/{key}")
                    except Exception as e:
                        print(f"[thumbnail_retry] thumbnail storage delete failed (non-fatal): {e}")

            print(f"[thumbnail_retry] done — {yt_id}")
        except Exception as exc:
            local_thumb_path = locals().get("local_thumb")
            if local_thumb_path:
                try:
                    local_thumb_path.unlink(missing_ok=True)
                except Exception:
                    pass
            print(f"[thumbnail_retry] failed for {yt_id}: {exc}")
            if _is_quota_exceeded(exc):
                print("[thumbnail_retry] YouTube quota exhausted — stopping")
                break

    print("[thumbnail_retry] done")


if __name__ == "__main__":
    main()
