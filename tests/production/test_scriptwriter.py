import pytest
from unittest.mock import MagicMock, patch
from agents.production.scriptwriter import Scriptwriter, ScriptPair


@pytest.fixture
def writer():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    mock_gate.advance_or_pause.return_value = "awaiting_review"
    return Scriptwriter(supabase=mock_sb, gate_client=mock_gate)


def test_generate_returns_script_pair(writer):
    with patch("agents.production.scriptwriter.complete_sonnet") as mock_s, \
         patch("agents.production.scriptwriter.complete") as mock_h:
        mock_s.return_value = "LONG FORM SCRIPT CONTENT [B-ROLL: person checks phone]"
        mock_h.return_value = "SHORT SCRIPT CONTENT"
        patch2 = patch("agents.production.scriptwriter.complete_sonnet",
                       side_effect=["LONG FORM SCRIPT CONTENT", "Title|Description|tag1,tag2"])
        with patch2:
            result = writer.generate(
                topic_title="I sued my landlord and won",
                topic_body="Full story about the eviction dispute...",
                niche_name="legal rights",
                niche_category="legal",
            )
    assert isinstance(result, ScriptPair)
    assert len(result.long_form) > 0
    assert len(result.short_form) > 0


def test_write_to_db_calls_insert(writer):
    pair = ScriptPair(
        long_form="Long script here",
        short_form="Short script here",
        youtube_title="I Sued My Landlord And Won",
        youtube_description="In this video...",
        youtube_tags=["legal", "tenant rights"],
    )
    writer._sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "script-uuid-123"}
    ]
    script_id = writer.write_to_db(pair, topic_id="topic-uuid", niche_id="niche-uuid")
    assert script_id == "script-uuid-123"
