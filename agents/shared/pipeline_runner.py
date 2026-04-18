from supabase import Client, create_client
from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry


class PipelineRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches").select("*").eq("status", "testing")
        ).data + execute_with_retry(
            self._sb.table("niches").select("*").eq("status", "promoted")
        ).data
        for niche in active_niches:
            self._process_niche(niche)

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]

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
        if approved_scripts:
            self._run_voiceover(niche)

        gate4_approved = execute_with_retry(
            self._sb.table("videos").select("id")
            .eq("niche_id", niche_id).eq("gate4_state", "approved").eq("status", "pending")
        ).data
        if gate4_approved:
            self._run_video_assembler(niche)

        upload_ready = execute_with_retry(
            self._sb.table("videos").select("id")
            .eq("niche_id", niche_id).eq("gate5_state", "approved").eq("gate6_state", "approved").eq("status", "approved")
        ).data
        if upload_ready:
            self._run_uploader(niche)

    def _run_scriptwriter(self, niche: dict) -> None:
        from agents.production.scriptwriter import Scriptwriter
        writer = Scriptwriter(supabase=self._sb, gate_client=self._gate)
        writer.process_approved_topics(niche["id"])

    def _run_voiceover(self, niche: dict) -> None:
        from agents.production.voiceover import VoiceoverAgent
        agent = VoiceoverAgent(supabase=self._sb, gate_client=self._gate)
        agent.process_approved_scripts(niche["id"])

    def _run_video_assembler(self, niche: dict) -> None:
        from agents.production.video_assembler import VideoAssembler, PexelsClient
        pexels = PexelsClient(api_key=get_env("PEXELS_API_KEY"))
        assembler = VideoAssembler(supabase=self._sb, gate_client=self._gate, pexels_client=pexels)
        assembler.process_approved_voiceovers(niche["id"])

    def _run_uploader(self, niche: dict) -> None:
        from agents.production.uploader import YouTubeUploader
        uploader = YouTubeUploader(supabase=self._sb, gate_client=self._gate)
        uploader.process_approved_videos(niche["id"])


def main() -> None:
    sb = create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))
    gate = GateClient(sb)
    runner = PipelineRunner(supabase=sb, gate_client=gate)
    runner.run()


if __name__ == "__main__":
    main()
