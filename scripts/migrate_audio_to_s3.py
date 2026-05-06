"""
Migrate existing Supabase voiceover files to S3, update video rows, then delete
from Supabase so the storage quota is freed.

Usage:
  python3 scripts/migrate_audio_to_s3.py            # dry run
  python3 scripts/migrate_audio_to_s3.py --execute  # migrate and delete
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import boto3
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
S3_BUCKET = os.environ["AWS_S3_BUCKET"]
S3_REGION = os.environ["REMOTION_REGION"]


def filename_from_url(url: str) -> str:
    return urlparse(url).path.split("/")[-1]


def s3_url(filename: str) -> str:
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/audio/{filename}"


def migrate_file(sb, s3, video: dict, field: str, dry_run: bool) -> Optional[str]:
    """Download one file from Supabase, upload to S3, return new S3 URL (or None on error)."""
    url = video.get(field) or ""
    if not url or "supabase" not in url:
        return None

    filename = filename_from_url(url)
    content_type = "audio/mpeg" if filename.endswith(".mp3") else "application/octet-stream"
    new_url = s3_url(filename)

    if dry_run:
        print(f"  [dry-run] {field}: {filename} → S3")
        return new_url

    # Download from Supabase into a temp file
    try:
        data = sb.storage.from_("voiceovers").download(filename)
    except Exception as e:
        print(f"  ERROR downloading {filename}: {e}")
        return None

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        s3.upload_file(
            tmp_path,
            S3_BUCKET,
            f"audio/{filename}",
            ExtraArgs={"ContentType": content_type},
        )
    except Exception as e:
        print(f"  ERROR uploading {filename} to S3: {e}")
        os.unlink(tmp_path)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return new_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN — pass --execute to migrate ===\n")
    else:
        print("=== LIVE RUN — migrating Supabase audio → S3 ===\n")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    s3 = boto3.client("s3", region_name=S3_REGION)

    videos = (
        sb.table("videos")
        .select("id, audio_path, srt_path")
        .execute()
        .data
    )

    supabase_videos = [
        v for v in videos
        if (v.get("audio_path") and "supabase" in v["audio_path"])
        or (v.get("srt_path") and "supabase" in (v.get("srt_path") or ""))
    ]

    print(f"Videos with Supabase audio/srt: {len(supabase_videos)}\n")

    migrated = 0
    errors = 0
    supabase_files_to_delete: list[str] = []

    for video in supabase_videos:
        vid_id = video["id"]
        updates: dict[str, str] = {}

        for field in ("audio_path", "srt_path"):
            url = video.get(field) or ""
            if not url or "supabase" not in url:
                continue
            filename = filename_from_url(url)
            new_url = migrate_file(sb, s3, video, field, dry_run)
            if new_url:
                updates[field] = new_url
                supabase_files_to_delete.append(filename)
            else:
                errors += 1

        if updates and not dry_run:
            try:
                sb.table("videos").update(updates).eq("id", vid_id).execute()
                print(f"  updated video {vid_id[:8]} DB URLs")
                migrated += 1
            except Exception as e:
                print(f"  ERROR updating DB for {vid_id[:8]}: {e}")
                errors += 1
        elif updates:
            migrated += 1

    print()

    # Delete from Supabase after all DB updates succeed
    if supabase_files_to_delete and not dry_run:
        print(f"Deleting {len(supabase_files_to_delete)} file(s) from Supabase voiceovers bucket...")
        chunk = 100
        deleted = 0
        for i in range(0, len(supabase_files_to_delete), chunk):
            batch = supabase_files_to_delete[i : i + chunk]
            try:
                sb.storage.from_("voiceovers").remove(batch)
                deleted += len(batch)
            except Exception as e:
                print(f"  WARN: batch delete failed: {e}")
        print(f"  {deleted} file(s) deleted from Supabase")
    elif supabase_files_to_delete:
        print(f"[dry-run] would delete {len(supabase_files_to_delete)} file(s) from Supabase after migration")

    print()
    print("=== Summary ===")
    print(f"  migrated  {migrated}")
    print(f"  errors    {errors}")
    if dry_run:
        print("\nRe-run with --execute to apply.")


if __name__ == "__main__":
    main()
