"""
Reconciler: compares youtube_video_id values in the DB against the YouTube
Data API to detect videos deleted from YouTube. Deletes those video rows and
returns their scripts to the review queue for a full re-run of the pipeline.
"""

from supabase import Client, create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.uploader import build_youtube_service, SCOPES

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import json

BATCH_SIZE = 50


class Reconciler:
    def __init__(self, supabase: Client):
        self._sb = supabase

    def _build_service_for_account(self, account_id: str):
        rows = execute_with_retry(
            self._sb.table("youtube_accounts")
            .select("token_json, channel_id")
            .eq("id", account_id)
            .limit(1)
        ).data
        if not rows:
            return None
        token_dict = rows[0]["token_json"]
        creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            execute_with_retry(
                self._sb.table("youtube_accounts")
                .update({"token_json": json.loads(creds.to_json())})
                .eq("id", account_id)
            )
        return build_youtube_service(token_dict=json.loads(creds.to_json()) if creds.expired else token_dict)

    def _check_batch(self, yt, video_ids: list[str]) -> set[str]:
        """Returns the subset of video_ids that still exist on YouTube."""
        try:
            resp = yt.videos().list(part="id", id=",".join(video_ids)).execute()
            return {item["id"] for item in resp.get("items", [])}
        except Exception as e:
            print(f"[reconciler] videos.list failed: {e}")
            return set(video_ids)  # assume all live on error to avoid false resets

    def _reset_deleted(self, deleted_rows: list[dict], all_db_videos: list[dict], live_ids: set[str]) -> None:
        # Scripts that still have at least one other live upload — treat deletion as a duplicate cleanup
        live_script_ids = {
            v["script_id"] for v in all_db_videos if v["youtube_video_id"] in live_ids
        }

        orphans = [r for r in deleted_rows if r["script_id"] in live_script_ids]
        needs_reset = [r for r in deleted_rows if r["script_id"] not in live_script_ids]

        execute_with_retry(
            self._sb.table("published_videos").delete().in_("id", [r["id"] for r in deleted_rows])
        )

        if orphans:
            print(f"[reconciler] {len(orphans)} duplicate row(s) removed — other uploads still live, script untouched")

        if needs_reset:
            script_ids = list({r["script_id"] for r in needs_reset})
            execute_with_retry(
                self._sb.table("scripts")
                .update({
                    "gate3_state": "awaiting_review",
                    "status": "pending",
                    "rejection_reason": "YouTube video was deleted — returned for review",
                })
                .in_("id", script_ids)
            )

    def run(self) -> None:
        niches = execute_with_retry(
            self._sb.table("niches")
            .select("id, name, youtube_account_id, channel_state")
            .eq("channel_state", "linked")
        ).data

        total_reset = 0
        for niche in niches:
            account_id = niche.get("youtube_account_id")
            if not account_id:
                continue

            yt = self._build_service_for_account(account_id)
            if not yt:
                print(f"[reconciler] no token for niche {niche['name']} — skipping")
                continue

            db_videos = execute_with_retry(
                self._sb.table("published_videos")
                .select("id, script_id, youtube_video_id, video_type")
                .eq("niche_id", niche["id"])
            ).data

            if not db_videos:
                continue

            id_map = {v["youtube_video_id"]: v for v in db_videos}
            yt_ids = list(id_map.keys())

            live_ids: set[str] = set()
            for i in range(0, len(yt_ids), BATCH_SIZE):
                batch = yt_ids[i : i + BATCH_SIZE]
                live_ids |= self._check_batch(yt, batch)

            deleted_rows = [id_map[vid] for vid in yt_ids if vid not in live_ids]
            if not deleted_rows:
                print(f"[reconciler] {niche['name']}: all {len(yt_ids)} video(s) live")
                continue

            for row in deleted_rows:
                print(f"[reconciler] DELETED  {niche['name']} | {row['video_type']} | {row['youtube_video_id']}")

            self._reset_deleted(deleted_rows, db_videos, live_ids)
            total_reset += len(deleted_rows)
            print(f"[reconciler] {niche['name']}: returned {len(deleted_rows)} video(s) to script queue")

        print(f"[reconciler] done — {total_reset} total video(s) reset")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    Reconciler(supabase=sb).run()


if __name__ == "__main__":
    main()
