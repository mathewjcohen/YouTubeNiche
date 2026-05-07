"""One-off runner: upload all approved shorts that are waiting in the backlog.

Triggered manually via workflow_dispatch. Skips voiceover/thumbnail/assembly —
only runs the uploader with video_type='short'. Longs are left untouched.
"""

from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.uploader import YouTubeUploader


def main() -> None:
    print("[shorts_cleanup] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)

    niches = execute_with_retry(
        sb.table("niches")
        .select("id, name, channel_state")
        .in_("status", ["promoted", "testing"])
        .eq("channel_state", "linked")
    ).data
    print(f"[shorts_cleanup] {len(niches)} linked niche(s)")

    for niche in niches:
        niche_id = niche["id"]
        name = niche.get("name", niche_id)

        pending = execute_with_retry(
            sb.table("videos")
            .select("id", count="exact")
            .eq("niche_id", niche_id)
            .eq("video_type", "short")
            .eq("gate6_state", "approved")
            .eq("status", "approved")
        ).count or 0

        if pending == 0:
            print(f"[shorts_cleanup]   '{name}' — no pending shorts")
            continue

        print(f"[shorts_cleanup]   '{name}' — {pending} short(s) pending")
        try:
            uploader = YouTubeUploader(supabase=sb, gate_client=gate)
            uploader.process_approved_videos(niche_id, video_type_filter="short")
        except Exception as exc:
            print(f"[shorts_cleanup]   '{name}' failed: {exc}")

    print("[shorts_cleanup] done")


if __name__ == "__main__":
    main()
