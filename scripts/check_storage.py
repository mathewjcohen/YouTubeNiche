"""
Audit Supabase Storage usage across all buckets.

Usage:
  python3 scripts/check_storage.py

Prints file counts and total size per bucket (voiceovers, thumbnails, broll),
plus a breakdown of the videos table (uploaded vs pending vs awaiting review).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

BUCKETS = ["voiceovers", "thumbnails", "broll"]


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def audit_bucket(name: str) -> None:
    files = sb.storage.from_(name).list()
    count = len(files)
    total_bytes = sum(f.get("metadata", {}).get("size", 0) for f in files if f.get("metadata"))
    print(f"  {name:15s}  {count:4d} files   {fmt_bytes(total_bytes)}")


print("=== Supabase Storage ===")
for bucket in BUCKETS:
    try:
        audit_bucket(bucket)
    except Exception as e:
        print(f"  {bucket:15s}  ERROR: {e}")

print()
print("=== videos table ===")

total = sb.table("videos").select("id", count="exact").execute()
uploaded = sb.table("videos").select("id", count="exact").not_.is_("youtube_video_id", "null").execute()
pending = sb.table("videos").select("id", count="exact").is_("youtube_video_id", "null").execute()
awaiting = sb.table("videos").select("id", count="exact").eq("gate6_state", "awaiting_review").execute()
no_path = sb.table("videos").select("id", count="exact").is_("video_path", "null").execute()

print(f"  total rows        {total.count}")
print(f"  uploaded to YT    {uploaded.count}")
print(f"  not yet uploaded  {pending.count}")
print(f"    awaiting review {awaiting.count}")
print(f"    no video_path   {no_path.count}")
