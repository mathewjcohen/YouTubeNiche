"""
Migrate existing Supabase thumbnail files to S3, update video rows, then delete
from Supabase so the storage quota is freed.

Usage:
  python3 scripts/migrate_thumbnails_to_s3.py            # dry run
  python3 scripts/migrate_thumbnails_to_s3.py --execute  # migrate and delete
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path
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
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/thumbnails/{filename}"


def migrate_thumbnail(sb, s3, video: dict, dry_run: bool) -> bool:
    url = video.get("thumbnail_path") or ""
    if not url or "supabase" not in url:
        return False

    filename = filename_from_url(url)
    new_url = s3_url(filename)

    if dry_run:
        print(f"  [dry-run] {video['id'][:8]}: {filename} → S3")
        return True

    try:
        data = sb.storage.from_("thumbnails").download(filename)
    except Exception as e:
        print(f"  ERROR downloading {filename}: {e}")
        return False

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        s3.upload_file(
            tmp_path,
            S3_BUCKET,
            f"thumbnails/{filename}",
            ExtraArgs={"ContentType": "image/jpeg"},
        )
    except Exception as e:
        print(f"  ERROR uploading {filename} to S3: {e}")
        os.unlink(tmp_path)
        return False
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    try:
        sb.table("videos").update({"thumbnail_path": new_url}).eq("id", video["id"]).execute()
        print(f"  migrated {video['id'][:8]}: {filename}")
    except Exception as e:
        print(f"  ERROR updating DB for {video['id'][:8]}: {e}")
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN — pass --execute to migrate ===\n")
    else:
        print("=== LIVE RUN — migrating Supabase thumbnails → S3 ===\n")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    s3 = boto3.client("s3", region_name=S3_REGION)

    videos = (
        sb.table("videos")
        .select("id, thumbnail_path")
        .execute()
        .data
    )

    supabase_videos = [
        v for v in videos
        if v.get("thumbnail_path") and "supabase" in v["thumbnail_path"]
    ]

    print(f"Videos with Supabase thumbnails: {len(supabase_videos)}\n")

    migrated = 0
    errors = 0
    supabase_files_to_delete: list[str] = []

    for video in supabase_videos:
        url = video.get("thumbnail_path") or ""
        filename = filename_from_url(url)
        ok = migrate_thumbnail(sb, s3, video, dry_run)
        if ok:
            migrated += 1
            supabase_files_to_delete.append(filename)
        else:
            errors += 1

    print()

    if supabase_files_to_delete and not dry_run:
        print(f"Deleting {len(supabase_files_to_delete)} file(s) from Supabase thumbnails bucket...")
        chunk = 100
        deleted = 0
        for i in range(0, len(supabase_files_to_delete), chunk):
            batch = supabase_files_to_delete[i : i + chunk]
            try:
                sb.storage.from_("thumbnails").remove(batch)
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
