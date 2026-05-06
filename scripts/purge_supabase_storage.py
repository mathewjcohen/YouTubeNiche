"""
Clear Supabase storage buckets now that assets have moved to S3.

Voiceovers: delete any file whose video row has an S3 audio_path (amazonaws.com).
            Files still referenced by Supabase audio_path URLs are kept.
            Files with no matching video row (true orphans) are also deleted.

Thumbnails: delete thumbnails for videos already uploaded to YouTube
            (youtube_video_id IS NOT NULL). Thumbnails for pending videos are kept
            so the uploader can still set them.

Usage:
  python3 scripts/purge_supabase_storage.py            # dry run (safe)
  python3 scripts/purge_supabase_storage.py --execute  # actually delete
"""
import argparse
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def filename_from_url(url: str) -> str:
    return urlparse(url).path.split("/")[-1]


def list_bucket(sb, bucket: str) -> list[str]:
    files = []
    offset = 0
    limit = 1000
    while True:
        batch = sb.storage.from_(bucket).list("", {"limit": limit, "offset": offset})
        if not batch:
            break
        files.extend(f["name"] for f in batch if f.get("name"))
        if len(batch) < limit:
            break
        offset += limit
    return files


def delete_batch(sb, bucket: str, names: list[str], dry_run: bool) -> int:
    if dry_run:
        for name in names:
            print(f"  [dry-run] would delete {bucket}/{name}")
        return len(names)
    deleted = 0
    chunk = 100
    for i in range(0, len(names), chunk):
        batch = names[i : i + chunk]
        try:
            sb.storage.from_(bucket).remove(batch)
            for name in batch:
                print(f"  deleted {bucket}/{name}")
            deleted += len(batch)
        except Exception as e:
            print(f"  WARN: batch delete failed: {e}")
    return deleted


def purge_voiceovers(sb, dry_run: bool) -> int:
    print("--- voiceovers ---")
    all_files = list_bucket(sb, "voiceovers")
    print(f"  {len(all_files)} file(s) in bucket")

    videos = (
        sb.table("videos")
        .select("audio_path, srt_path")
        .execute()
        .data
    )

    # Keep files where the video still references them via a Supabase URL
    supabase_kept: set[str] = set()
    for v in videos:
        for field in ("audio_path", "srt_path"):
            url = v.get(field) or ""
            if "supabase" in url:
                supabase_kept.add(filename_from_url(url))

    to_delete = [f for f in all_files if f not in supabase_kept]
    print(f"  {len(supabase_kept)} file(s) still referenced via Supabase URL (kept)")
    print(f"  {len(to_delete)} file(s) to delete (S3-migrated or orphaned)")
    return delete_batch(sb, "voiceovers", to_delete, dry_run)


def purge_thumbnails(sb, dry_run: bool) -> int:
    print("--- thumbnails ---")
    all_files = list_bucket(sb, "thumbnails")
    print(f"  {len(all_files)} file(s) in bucket")

    # Keep thumbnails for videos not yet uploaded to YouTube
    pending = (
        sb.table("videos")
        .select("thumbnail_path")
        .is_("youtube_video_id", "null")
        .execute()
        .data
    )

    pending_thumbs: set[str] = set()
    for v in pending:
        url = v.get("thumbnail_path") or ""
        if url:
            pending_thumbs.add(filename_from_url(url))

    to_delete = [f for f in all_files if f not in pending_thumbs]
    print(f"  {len(pending_thumbs)} file(s) for pending (not-yet-uploaded) videos (kept)")
    print(f"  {len(to_delete)} file(s) to delete (uploaded videos or orphaned)")
    return delete_batch(sb, "thumbnails", to_delete, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN — pass --execute to actually delete ===\n")
    else:
        print("=== LIVE RUN — deleting files ===\n")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    v_deleted = purge_voiceovers(sb, dry_run)
    print()
    t_deleted = purge_thumbnails(sb, dry_run)
    print()

    if not dry_run:
        print("=== Summary ===")
        print(f"  voiceovers  {v_deleted} deleted")
        print(f"  thumbnails  {t_deleted} deleted")
    else:
        print("Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
