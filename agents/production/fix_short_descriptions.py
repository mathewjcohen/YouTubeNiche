"""
One-off script: patches the YouTube description of uploaded Shorts to include
a link to the corresponding long-form video.

Safe to re-run — skips Shorts whose description already contains the link.

Run: python3 -m agents.production.fix_short_descriptions
"""

import json
from supabase import Client, create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.uploader import build_youtube_service, SCOPES

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


class ShortDescriptionFixer:
    def __init__(self, supabase: Client):
        self._sb = supabase

    def _build_service_for_account(self, account_id: str):
        rows = execute_with_retry(
            self._sb.table("youtube_accounts")
            .select("token_json")
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
            token_dict = json.loads(creds.to_json())
        return build_youtube_service(token_dict=token_dict)

    def run(self) -> None:
        niches = execute_with_retry(
            self._sb.table("niches")
            .select("id, name, youtube_account_id, channel_state")
            .eq("channel_state", "linked")
        ).data

        total_patched = 0
        total_skipped = 0

        for niche in niches:
            account_id = niche.get("youtube_account_id")
            if not account_id:
                continue

            yt = self._build_service_for_account(account_id)
            if not yt:
                print(f"[fixer] no token for niche {niche['name']} — skipping")
                continue

            # Fetch all uploaded videos for this niche
            all_videos = execute_with_retry(
                self._sb.table("videos")
                .select("id, script_id, video_type, youtube_video_id")
                .eq("niche_id", niche["id"])
                .eq("status", "uploaded")
                .not_.is_("youtube_video_id", "null")
            ).data

            # Build lookup: script_id → long youtube_video_id
            long_ids: dict[str, str] = {
                v["script_id"]: v["youtube_video_id"]
                for v in all_videos
                if v["video_type"] == "long" and v["youtube_video_id"]
            }

            shorts = [v for v in all_videos if v["video_type"] == "short" and v["youtube_video_id"]]

            for short in shorts:
                long_yt_id = long_ids.get(short["script_id"])
                if not long_yt_id:
                    print(f"[fixer] {niche['name']} | short {short['youtube_video_id']} — no uploaded long found, skipping")
                    total_skipped += 1
                    continue

                link = f"https://www.youtube.com/watch?v={long_yt_id}"

                # Fetch current snippet from YouTube
                try:
                    resp = yt.videos().list(
                        part="snippet",
                        id=short["youtube_video_id"]
                    ).execute()
                except Exception as e:
                    print(f"[fixer] videos.list failed for {short['youtube_video_id']}: {e}")
                    total_skipped += 1
                    continue

                items = resp.get("items", [])
                if not items:
                    print(f"[fixer] {short['youtube_video_id']} not found on YouTube — skipping")
                    total_skipped += 1
                    continue

                snippet = items[0]["snippet"]
                current_description = snippet.get("description", "")

                link_line = f"Watch the full video: {link}"
                has_link = link in current_description
                has_disclaimer = "\n\n⚠️ DISCLAIMER:" in current_description

                if has_link and has_disclaimer:
                    disclaimer_pos = current_description.index("\n\n⚠️ DISCLAIMER:")
                    link_pos = current_description.index(link)
                    if link_pos < disclaimer_pos:
                        print(f"[fixer] {niche['name']} | short {short['youtube_video_id']} — link already in correct position, skipping")
                        total_skipped += 1
                        continue
                    # Link is after the disclaimer — strip and reinsert before it
                    cleaned = current_description.replace(f"\n\n{link_line}", "").replace(link_line, "").rstrip()
                    pre, post = cleaned.split("\n\n⚠️ DISCLAIMER:", 1)
                    new_description = pre.rstrip() + f"\n\n{link_line}\n\n⚠️ DISCLAIMER:" + post
                elif has_link:
                    print(f"[fixer] {niche['name']} | short {short['youtube_video_id']} — link already present, skipping")
                    total_skipped += 1
                    continue
                elif has_disclaimer:
                    pre, post = current_description.split("\n\n⚠️ DISCLAIMER:", 1)
                    new_description = pre.rstrip() + f"\n\n{link_line}\n\n⚠️ DISCLAIMER:" + post
                else:
                    new_description = current_description.rstrip() + f"\n\n{link_line}"
                snippet["description"] = new_description

                try:
                    yt.videos().update(
                        part="snippet",
                        body={"id": short["youtube_video_id"], "snippet": snippet}
                    ).execute()
                    print(f"[fixer] {niche['name']} | short {short['youtube_video_id']} — patched with link to {long_yt_id}")
                    total_patched += 1
                except Exception as e:
                    print(f"[fixer] update failed for {short['youtube_video_id']}: {e}")
                    total_skipped += 1

        print(f"\n[fixer] done — {total_patched} patched, {total_skipped} skipped")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    ShortDescriptionFixer(supabase=sb).run()


if __name__ == "__main__":
    main()
