"""
Delete all storage files associated with videos already uploaded to YouTube.

Cleans:
  - Supabase `thumbnails` bucket
  - Supabase `voiceovers` bucket (MP3 + SRT)
  - Supabase `broll` bucket
  - AWS S3 (final video files)

Does NOT delete DB rows by default. Pass --delete-rows to also remove
the videos/scripts rows from the database.

Usage:
  python3 scripts/cleanup_uploaded.py            # dry run (safe)
  python3 scripts/cleanup_uploaded.py --execute  # actually delete
  python3 scripts/cleanup_uploaded.py --execute --delete-rows
"""
import argparse
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
AWS_BUCKET = os.environ.get("AWS_S3_BUCKET", "")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def storage_key_from_url(url: str) -> str:
    """Extract the object key (filename) from a Supabase Storage public URL."""
    return urlparse(url).path.split("/")[-1]


def s3_key_from_url(url: str) -> str:
    """Extract S3 object key from an S3 URL."""
    return urlparse(url).path.lstrip("/")


def delete_from_bucket(sb, bucket: str, keys: list[str], dry_run: bool) -> int:
    if not keys:
        return 0
    if dry_run:
        for k in keys:
            print(f"  [dry-run] would delete {bucket}/{k}")
        return len(keys)
    deleted = 0
    for key in keys:
        try:
            sb.storage.from_(bucket).remove([key])
            print(f"  deleted {bucket}/{key}")
            deleted += 1
        except Exception as e:
            print(f"  WARN: {bucket}/{key} — {e}")
    return deleted


def delete_from_s3(s3, keys: list[str], dry_run: bool) -> int:
    if not keys or not AWS_BUCKET:
        if keys:
            print(f"  WARN: AWS_S3_BUCKET not set — skipping {len(keys)} S3 file(s)")
        return 0
    if dry_run:
        for k in keys:
            print(f"  [dry-run] would delete s3://{AWS_BUCKET}/{k}")
        return len(keys)
    deleted = 0
    for key in keys:
        try:
            s3.delete_object(Bucket=AWS_BUCKET, Key=key)
            print(f"  deleted s3://{AWS_BUCKET}/{key}")
            deleted += 1
        except NoCredentialsError:
            print(f"  WARN: no AWS credentials — skipping S3 deletions")
            return deleted
        except ClientError as e:
            print(f"  WARN: s3://{AWS_BUCKET}/{key} — {e}")
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete (default: dry run)")
    parser.add_argument("--delete-rows", action="store_true", help="Also delete DB rows")
    args = parser.parse_args()

    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN — pass --execute to actually delete ===\n")
    else:
        print("=== LIVE RUN — deleting files ===\n")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    s3 = boto3.client("s3", region_name=AWS_REGION) if AWS_BUCKET else None

    # Fetch all uploaded videos (audio_path/srt_path are on the videos table)
    rows = (
        sb.table("videos")
        .select("id, video_type, video_path, thumbnail_path, audio_path, srt_path")
        .not_.is_("youtube_video_id", "null")
        .execute()
        .data
    )

    if not rows:
        print("No uploaded videos found.")
        return

    print(f"Found {len(rows)} uploaded video(s) to clean up.\n")

    # Collect all broll keys up front so we can match by prefix
    print("Listing broll bucket...")
    try:
        all_broll = [f["name"] for f in sb.storage.from_("broll").list()]
    except Exception as e:
        print(f"  WARN: could not list broll bucket — {e}")
        all_broll = []
    print(f"  {len(all_broll)} broll file(s) in bucket\n")

    totals = {"thumbnails": 0, "voiceovers": 0, "broll": 0, "s3": 0, "rows": 0}

    for video in rows:
        vid_id = video["id"]
        vid_type = video["video_type"]
        prefix = f"broll_{vid_id[:8]}_{vid_type}_remotion_"

        print(f"--- {vid_id[:8]} ({vid_type}) ---")

        # Thumbnail
        thumb_keys = []
        if video.get("thumbnail_path"):
            thumb_keys.append(storage_key_from_url(video["thumbnail_path"]))
        totals["thumbnails"] += delete_from_bucket(sb, "thumbnails", thumb_keys, dry_run)

        # Voiceover MP3 + SRT
        vo_keys = []
        if video.get("audio_path"):
            vo_keys.append(storage_key_from_url(video["audio_path"]))
        if video.get("srt_path"):
            vo_keys.append(storage_key_from_url(video["srt_path"]))
        totals["voiceovers"] += delete_from_bucket(sb, "voiceovers", vo_keys, dry_run)

        # B-roll (all files matching this video's prefix)
        broll_keys = [k for k in all_broll if k.startswith(prefix)]
        totals["broll"] += delete_from_bucket(sb, "broll", broll_keys, dry_run)

        # S3 final video
        s3_keys = []
        if video.get("video_path") and video["video_path"].startswith("https://"):
            s3_keys.append(s3_key_from_url(video["video_path"]))
        if s3 and s3_keys:
            totals["s3"] += delete_from_s3(s3, s3_keys, dry_run)
        elif s3_keys and dry_run:
            totals["s3"] += delete_from_s3(None, s3_keys, dry_run)

        # DB rows
        if args.delete_rows and not dry_run:
            sb.table("videos").delete().eq("id", vid_id).execute()
            print(f"  deleted videos row {vid_id[:8]}")
            totals["rows"] += 1

    print(f"\n=== Summary ({'dry run' if dry_run else 'live'}) ===")
    print(f"  thumbnails  {totals['thumbnails']}")
    print(f"  voiceovers  {totals['voiceovers']}")
    print(f"  broll       {totals['broll']}")
    print(f"  s3 videos   {totals['s3']}")
    if args.delete_rows:
        print(f"  db rows     {totals['rows']}")

    if dry_run:
        print("\nRe-run with --execute to apply.")


if __name__ == "__main__":
    main()
