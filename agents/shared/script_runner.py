from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared.pipeline_runner import get_app_setting
from agents.production.scriptwriter import Scriptwriter


class ScriptRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        enabled = get_app_setting(self._sb, "pipeline_enabled", "true")
        print(f"[script] pipeline_enabled={enabled}")
        if enabled == "false":
            print("[script] paused via dashboard — exiting")
            return

        niches = execute_with_retry(
            self._sb.table("niches")
            .select("id,name,category,status")
            .in_("status", ["promoted", "testing"])
        ).data
        print(f"[script] {len(niches)} active niche(s)")
        for niche in niches:
            self._process_niche(niche)

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]
        name = niche.get("name", niche_id)
        print(f"[script] niche '{name}'")

        approved_topics = execute_with_retry(
            self._sb.table("topics")
            .select("id")
            .eq("niche_id", niche_id)
            .eq("gate2_state", "approved")
            .eq("status", "pending")
        ).data
        if not approved_topics:
            print(f"[script]   no approved topics — skipping scriptwriter")
            return

        print(f"[script]   {len(approved_topics)} approved topic(s) → running scriptwriter")
        writer = Scriptwriter(supabase=self._sb, gate_client=self._gate)
        writer.process_approved_topics(niche_id)


def main() -> None:
    print("[script] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    runner = ScriptRunner(supabase=sb, gate_client=gate)
    runner.run()
    print("[script] done")


if __name__ == "__main__":
    main()
