"""One-off: append niche-specific disclaimers to existing scripts that lack one."""
from supabase import create_client
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.scriptwriter import get_disclaimer


def main() -> None:
    print("Connecting to Supabase...", flush=True)
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))

    print("Fetching scripts...", flush=True)
    rows = execute_with_retry(
        sb.table("scripts")
        .select("id, youtube_description, niche_id, niches(category)")
    ).data
    print(f"Found {len(rows)} scripts.", flush=True)

    updated = 0
    skipped = 0
    for row in rows:
        desc = row.get("youtube_description") or ""
        if "DISCLAIMER" in desc:
            skipped += 1
            continue

        category = (row.get("niches") or {}).get("category", "")
        disclaimer = get_disclaimer(category)
        execute_with_retry(
            sb.table("scripts")
            .update({"youtube_description": desc + disclaimer})
            .eq("id", row["id"])
        )
        updated += 1
        print(f"[backfill] updated {row['id'][:8]}… (category: {category or 'unknown'})")

    print(f"\nDone. {updated} updated, {skipped} already had disclaimer.")


if __name__ == "__main__":
    main()
