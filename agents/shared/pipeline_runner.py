import os
from supabase import Client, create_client
from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1

STAGES = os.environ.get("PIPELINE_STAGES", "all")  # "fast" | "slow" | "all"


def get_render_method(sb: Client) -> str:
    rows = execute_with_retry(
        sb.table("app_settings").select("value").eq("key", "render_method").limit(1)
    ).data
    return rows[0]["value"] if rows else "github"


class PipelineRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches").select("*, youtube_accounts(channel_id)").eq("status", "testing")
        ).data + execute_with_retry(
            self._sb.table("niches").select("*, youtube_accounts(channel_id)").eq("status", "promoted")
        ).data
        for niche in active_niches:
            self._process_niche(niche)

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]

        if STAGES in ("fast", "all"):
            approved_topics = execute_with_retry(
                self._sb.table("topics").select("id")
                .eq("niche_id", niche_id).eq("gate2_state", "approved").eq("status", "pending")
            ).data
            if approved_topics:
                self._run_scriptwriter(niche)

            approved_scripts = execute_with_retry(
                self._sb.table("scripts").select("id")
                .eq("niche_id", niche_id).eq("gate3_state", "approved").eq("status", "pending")
            ).data
            missing_thumbs = execute_with_retry(
                self._sb.table("videos").select("id")
                .eq("niche_id", niche_id).eq("gate5_state", "awaiting_review")
                .is_("thumbnail_path", "null")
            ).data
            if approved_scripts or missing_thumbs:
                self._run_thumbnail_gen(niche)
            if approved_scripts:
                self._run_voiceover(niche)

        if STAGES in ("slow", "all"):
            gate4_approved = execute_with_retry(
                self._sb.table("videos").select("id")
                .eq("niche_id", niche_id).eq("gate4_state", "approved").eq("status", "pending")
            ).data
            if gate4_approved:
                render_method = get_render_method(self._sb)
                self._run_video_assembler(niche, render_method)

            upload_ready = execute_with_retry(
                self._sb.table("videos").select("id")
                .eq("niche_id", niche_id).eq("gate5_state", "approved")
                .eq("gate6_state", "approved").eq("status", "approved")
            ).data
            if upload_ready:
                if niche.get("channel_state") != "linked":
                    print(f"[pipeline] niche '{niche['name']}' has no linked YouTube channel — skipping upload")
                else:
                    self._run_uploader(niche)

    def _run_thumbnail_gen(self, niche: dict) -> None:
        from agents.production.thumbnail_gen import ThumbnailGenerator
        gen = ThumbnailGenerator(
            supabase=self._sb,
            gate_client=self._gate,
            pexels_api_key=get_env("PEXELS_API_KEY"),
        )
        gen.process_approved_scripts(niche["id"])

    def _run_scriptwriter(self, niche: dict) -> None:
        from agents.production.scriptwriter import Scriptwriter
        writer = Scriptwriter(supabase=self._sb, gate_client=self._gate)
        writer.process_approved_topics(niche["id"])

    def _run_voiceover(self, niche: dict) -> None:
        from agents.production.voiceover import VoiceoverAgent
        agent = VoiceoverAgent(supabase=self._sb, gate_client=self._gate)
        agent.process_approved_scripts(niche["id"])

    def _run_video_assembler(self, niche: dict, render_method: str) -> None:
        if render_method == "aws":
            from agents.production.remotion_renderer import RemotionRenderer
            renderer = RemotionRenderer(supabase=self._sb, gate_client=self._gate)
            renderer.process_approved_voiceovers(niche["id"])
        else:
            from agents.production.video_assembler import VideoAssembler, PexelsClient
            pexels = PexelsClient(api_key=get_env("PEXELS_API_KEY"))
            assembler = VideoAssembler(supabase=self._sb, gate_client=self._gate, pexels_client=pexels)
            assembler.process_approved_voiceovers(niche["id"])

    def _run_uploader(self, niche: dict) -> None:
        from agents.production.uploader import YouTubeUploader
        uploader = YouTubeUploader(supabase=self._sb, gate_client=self._gate)
        uploader.process_approved_videos(niche["id"])


def main() -> None:
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    runner = PipelineRunner(supabase=sb, gate_client=gate)
    runner.run()


if __name__ == "__main__":
    main()
