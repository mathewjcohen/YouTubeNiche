"""
Delete storage files in broll/voiceovers/thumbnails buckets that are not
referenced by any row in the videos table.

These accumulate when pipeline runs crash or fail mid-assembly — broll clips
get downloaded, render fails, no videos row is ever completed, and cleanup
never runs because there is nothing to upload.

Usage:
  python3 scripts/purge_orphaned_assets.py            # dry run (safe)
  python3 scripts/purge_orphaned_assets.py --execute  # actually delete
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

BUCKETS = ["broll", "voiceovers", "thumbnails"]


def key_from_url(url: str) -> str:
    return urlparse(url).path.split("/")[-1]


def list_bucket(sb, bucket: str) -> list[str]:
    """List all file names in a bucket (handles pagination via limit)."""
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


def referenced_keys(videos: list[dict]) -> dict[str, set[str]]:
    """Build per-bucket sets of keys that are actively referenced."""
    keys: dict[str, set[str]] = {b: set() for b in BUCKETS}
    for v in videos:
        for field in ("audio_path", "srt_path"):
            if v.get(field):
                keys["voiceovers"].add(key_from_url(v[field]))
        if v.get("thumbnail_path"):
            keys["thumbnails"].add(key_from_url(v["thumbnail_path"]))
        # broll identified by prefix — collect known prefixes instead of filenames
        # handled separately below
    return keys


def referenced_broll_prefixes(videos: list[dict]) -> set[str]:
    """Return the broll filename prefixes for all current videos rows."""
    prefixes = set()
    for v in videos:
        if v.get("id") and v.get("video_type"):
            prefixes.add(f"broll_{v['id'][:8]}_{v['video_type']}_remotion_")
    return prefixes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN — pass --execute to actually delete ===\n")
    else:
        print("=== LIVE RUN — deleting orphaned files ===\n")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    videos = sb.table("videos").select("id, video_type, audio_path, srt_path, thumbnail_path").execute().data
    print(f"Active videos rows: {len(videos)}\n")

    ref_keys = referenced_keys(videos)
    broll_prefixes = referenced_broll_prefixes(videos)

    totals: dict[str, int] = {b: 0 for b in BUCKETS}

    for bucket in BUCKETS:
        print(f"--- {bucket} ---")
        try:
            all_files = list_bucket(sb, bucket)
        except Exception as e:
            print(f"  ERROR listing bucket: {e}")
            continue

        print(f"  {len(all_files)} file(s) in bucket")

        orphans: list[str] = []
        for name in all_files:
            if bucket == "broll":
                # orphaned if no current videos row has a matching prefix
                if not any(name.startswith(p) for p in broll_prefixes):
                    orphans.append(name)
            else:
                if name not in ref_keys[bucket]:
                    orphans.append(name)

        print(f"  {len(orphans)} orphaned file(s)")

        for name in orphans:
            if dry_run:
                print(f"  [dry-run] would delete {bucket}/{name}")
            else:
                try:
                    sb.storage.from_(bucket).remove([name])
                    print(f"  deleted {bucket}/{name}")
                    totals[bucket] += 1
                except Exception as e:
                    print(f"  WARN: {bucket}/{name} — {e}")
        print()

    if not dry_run:
        print("=== Summary ===")
        for bucket, count in totals.items():
            print(f"  {bucket:<12} {count} deleted")
    else:
        print("Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
