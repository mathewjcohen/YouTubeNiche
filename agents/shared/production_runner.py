from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared.pipeline_runner import get_app_setting, get_render_method
from agents.production.voiceover import VoiceoverAgent
from agents.production.thumbnail_gen import ThumbnailGenerator
from agents.production.video_assembler import VideoAssembler, PexelsClient
from agents.production.uploader import YouTubeUploader


class ProductionRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        enabled = get_app_setting(self._sb, "pipeline_enabled", "true")
        print(f"[production] pipeline_enabled={enabled}")
        if enabled == "false":
            print("[production] paused via dashboard — exiting")
            return

        niches = execute_with_retry(
            self._sb.table("niches")
            .select("*, youtube_accounts(channel_id)")
            .in_("status", ["promoted", "testing"])
        ).data
        print(f"[production] {len(niches)} active niche(s)")
        for niche in niches:
            try:
                self._process_niche(niche)
            except Exception as exc:
                print(f"[production] niche '{niche.get('name', niche.get('id'))}' failed: {exc}")

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]
        name = niche.get("name", niche_id)
        print(f"[production] niche '{name}'")

        agent = VoiceoverAgent(supabase=self._sb, gate_client=self._gate)
        agent.process_approved_scripts(niche_id, limit=1)

        gen = ThumbnailGenerator(
            supabase=self._sb,
            gate_client=self._gate,
            replicate_api_key=get_env("REPLICATE_API_KEY", required=False),
        )
        gen.process_approved_scripts(niche_id)

        render_method = get_render_method(self._sb)
        if render_method == "aws":
            from agents.production.remotion_renderer import RemotionRenderer
            renderer = RemotionRenderer(supabase=self._sb, gate_client=self._gate)
            renderer.process_approved_voiceovers(niche_id)
        else:
            pexels = PexelsClient(api_key=get_env("PEXELS_API_KEY"))
            assembler = VideoAssembler(
                supabase=self._sb,
                gate_client=self._gate,
                pexels_client=pexels,
            )
            assembler.process_approved_voiceovers(niche_id)

        if niche.get("channel_state") == "linked":
            uploader = YouTubeUploader(supabase=self._sb, gate_client=self._gate)
            uploader.process_approved_videos(niche_id)
        else:
            print(f"[production]   skipping upload — '{name}' has no linked channel")


def main() -> None:
    print("[production] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    runner = ProductionRunner(supabase=sb, gate_client=gate)
    runner.run()
    print("[production] done")


if __name__ == "__main__":
    main()
