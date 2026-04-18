from enum import IntEnum
from typing import Optional
from supabase import Client

class GateNumber(IntEnum):
    NICHE_ACTIVATION = 1
    TOPIC_SELECTION = 2
    SCRIPT = 3
    VOICEOVER = 4
    THUMBNAIL = 5
    FINAL_VIDEO = 6

class GateClient:
    def __init__(self, supabase: Client):
        self._sb = supabase

    def gate_enabled(self, gate: GateNumber, niche_id: Optional[str] = None) -> bool:
        if niche_id:
            result = (
                self._sb.table("gate_config")
                .select("enabled")
                .eq("niche_id", niche_id)
                .eq("gate_number", int(gate))
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["enabled"]
        result = (
            self._sb.table("gate_config")
            .select("enabled")
            .eq("gate_number", int(gate))
            .is_("niche_id", "null")
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["enabled"]
        return True

    def set_item_gate_state(self, table: str, item_id: str, gate_column: str, state: str) -> None:
        self._sb.table(table).update({gate_column: state}).eq("id", item_id).execute()

    def advance_or_pause(self, gate: GateNumber, niche_id: str, table: str, item_id: str,
                         gate_column: str, auto_state: str = "approved",
                         review_state: str = "awaiting_review") -> str:
        state = auto_state if not self.gate_enabled(gate, niche_id) else review_state
        self.set_item_gate_state(table, item_id, gate_column, state)
        return state
