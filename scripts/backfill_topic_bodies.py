"""
One-off: fetch and store article body text for non-Reddit topics that have an empty body.
Run from repo root: python3 scripts/backfill_topic_bodies.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from agents.shared.article_fetcher import fetch_article_body
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1


def main() -> None:
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))

    rows = execute_with_retry(
        sb.table("topics")
        .select("id, title, url")
        .neq("source_type", "reddit")
        .eq("body", "")
    ).data

    print(f"[backfill] {len(rows)} topics with empty body")

    updated = 0
    failed = 0
    for row in rows:
        body = fetch_article_body(row["url"])
        if body:
            execute_with_retry(
                sb.table("topics").update({"body": body}).eq("id", row["id"])
            )
            print(f"[backfill] ✓ {len(body)} chars — {row['title'][:70]}")
            updated += 1
        else:
            print(f"[backfill] ✗ no body — {row['title'][:70]}")
            failed += 1
        time.sleep(0.5)  # polite crawl rate

    print(f"[backfill] done. updated={updated} failed={failed}")


if __name__ == "__main__":
    main()
