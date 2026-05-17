"""
One-time script queue purge.

Scores all approved+pending scripts against the latest content patterns
from the insights table. Dry-run by default; use --execute to apply.
"""

import argparse
import json
import sys

from supabase import create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared import anthropic_client

BATCH_SIZE = 15


class ScriptPurge:
    def __init__(self):
        self._sb = patch_postgrest_http1(
            create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))
        )
        self._content_patterns = self._load_patterns()

    def _load_patterns(self):
        resp = execute_with_retry(
            self._sb.table("insights")
            .select("stats_json")
            .order("generated_at", desc=True)
            .limit(1)
        )
        rows = resp.data or []
        if not rows:
            return None
        return (rows[0].get("stats_json") or {}).get("content_patterns")

    def _build_prompt(self, scripts: list[dict]) -> str:
        winning = "; ".join(self._content_patterns.get("winning_angles", []))
        avoid = "; ".join(self._content_patterns.get("avoid", []))
        scripts_json = json.dumps(
            [{"id": s["id"], "title": s["youtube_title"]} for s in scripts],
            indent=2,
        )

        return f"""You are a YouTube content strategist evaluating video scripts for a channel.

Proven winning content angles: {winning}
Patterns that underperform on this channel: {avoid}

Evaluate each script below by its title. Keep scripts that match winning angles or have clear viewer value.
Reject scripts that match underperforming patterns or are off-brand.

Scripts to evaluate:
{scripts_json}

Return ONLY valid JSON — an array with one object per script, in the same order:
[
  {{"id": "<id>", "keep": true, "reason": null}},
  {{"id": "<id>", "keep": false, "reason": "One sentence reason for rejection"}}
]"""

    def _score_batch(self, scripts: list[dict]) -> list[dict]:
        prompt = self._build_prompt(scripts)
        try:
            raw = anthropic_client.complete_sonnet(prompt, max_tokens=2048)
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            results = json.loads(clean)
            if not isinstance(results, list):
                raise ValueError("expected list")
            return results
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[purge] batch parse error: {e} — keeping all in this batch")
            return [{"id": s["id"], "keep": True, "reason": None} for s in scripts]

    def run(self, execute: bool = False):
        if not self._content_patterns:
            print("[purge] ERROR: no content patterns found — run insights agent first")
            sys.exit(1)

        print(f"[purge] loaded patterns: {self._content_patterns}")

        scripts = execute_with_retry(
            self._sb.table("scripts")
            .select("id, youtube_title, niche_id")
            .eq("gate3_state", "approved")
            .eq("status", "pending")
        ).data or []

        print(f"[purge] {len(scripts)} scripts to evaluate")

        to_reject: list[dict] = []
        to_keep: list[dict] = []

        for i in range(0, len(scripts), BATCH_SIZE):
            batch = scripts[i:i + BATCH_SIZE]
            print(f"[purge] scoring batch {i // BATCH_SIZE + 1} ({len(batch)} scripts)")
            results = self._score_batch(batch)

            id_map = {s["id"]: s for s in batch}
            for r in results:
                script = id_map.get(r.get("id", ""))
                if script:
                    if r.get("keep"):
                        to_keep.append(script)
                    else:
                        to_reject.append({**script, "reason": r.get("reason", "No reason given")})

        print(f"\n{'DRY RUN — ' if not execute else ''}Results:")
        print(f"  Keep:   {len(to_keep)}")
        print(f"  Reject: {len(to_reject)}")

        if to_reject:
            print("\nScripts to reject:")
            for s in to_reject:
                print(f"  [{s['id'][:8]}] {(s['youtube_title'] or '')[:60]} — {s['reason']}")

        if execute and to_reject:
            print(f"\n[purge] applying {len(to_reject)} rejections...")
            for s in to_reject:
                execute_with_retry(
                    self._sb.table("scripts")
                    .update({
                        "gate3_state": "rejected",
                        "rejection_reason": f"[Purge] {s['reason']}",
                    })
                    .eq("id", s["id"])
                )
            print("[purge] done.")
        elif not execute:
            print("\nRun with --execute to apply rejections.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply rejections (default: dry run)")
    args = parser.parse_args()
    ScriptPurge().run(execute=args.execute)
