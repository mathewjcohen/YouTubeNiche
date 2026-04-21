"""
One-off: strip [B-ROLL: ...] tags from existing scripts in the DB.
Safe to re-run — skips rows with no tags.

Run: python3 -m agents.production.strip_broll
"""

import re
from supabase import create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1

_BROLL = re.compile(r'\[B-ROLL:.*?\]\n?', re.IGNORECASE | re.DOTALL)


def _strip(text: str | None) -> str | None:
    if not text:
        return text
    return re.sub(r'\n{3,}', '\n\n', _BROLL.sub('', text)).strip()


def main() -> None:
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))

    scripts = execute_with_retry(
        sb.table("scripts").select("id, long_form_text, short_text")
    ).data

    patched = 0
    for script in scripts:
        new_long = _strip(script["long_form_text"])
        new_short = _strip(script["short_text"])

        if new_long == script["long_form_text"] and new_short == script["short_text"]:
            continue

        execute_with_retry(
            sb.table("scripts")
            .update({"long_form_text": new_long, "short_text": new_short})
            .eq("id", script["id"])
        )
        patched += 1
        print(f"[strip-broll] patched {script['id'][:8]}")

    print(f"\n[strip-broll] done — {patched} script(s) patched, {len(scripts) - patched} already clean")


if __name__ == "__main__":
    main()
