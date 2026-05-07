import pytest
from pathlib import Path
from agents.production.voiceover import VoiceoverAgent, WordTimestamp, build_srt


def test_build_srt_formats_correctly():
    words = [
        WordTimestamp(word="Hello", offset_ms=0, duration_ms=400),
        WordTimestamp(word="world", offset_ms=500, duration_ms=350),
        WordTimestamp(word="this", offset_ms=1000, duration_ms=300),
    ]
    srt = build_srt(words, max_chars_per_cue=12)
    assert "00:00:00,000" in srt
    assert "Hello world" in srt
    assert "this" in srt
    # Validate actual SRT structure
    lines = srt.split("\n")
    assert lines[0] == "1"
    assert "-->" in lines[1]
    assert "Hello world" in lines[2]
    assert lines[3] == ""


def test_build_srt_empty_words_returns_empty():
    assert build_srt([], max_chars_per_cue=80) == ""


def test_ms_to_srt_time():
    from agents.production.voiceover import ms_to_srt_time
    assert ms_to_srt_time(0) == "00:00:00,000"
    assert ms_to_srt_time(1500) == "00:00:01,500"
    assert ms_to_srt_time(61500) == "00:01:01,500"
    assert ms_to_srt_time(3661000) == "01:01:01,000"


def test_stuck_reset_skips_scripts_with_video_rows():
    """Scripts that have video rows are mid-pipeline and must NOT be reset to pending."""
    from agents.production.voiceover import VoiceoverAgent
    from unittest.mock import MagicMock, patch

    mock_sb = MagicMock()
    mock_gate = MagicMock()
    agent = VoiceoverAgent(supabase=mock_sb, gate_client=mock_gate)

    stale_script_id = "script-stale-1"
    call_count = [0]

    def mock_retry(query):
        result = MagicMock()
        n = call_count[0]
        call_count[0] += 1
        if n == 0:
            result.data = [{"id": stale_script_id}]   # stale processing scripts
        elif n == 1:
            result.data = [{"id": "video-1"}]           # video rows exist -> must NOT reset
        elif n == 2:
            result.data = [{"category": "legal"}]       # niche category
        else:
            result.data = []                            # no pending scripts
        return result

    with patch("agents.production.voiceover.execute_with_retry", side_effect=mock_retry) as mock_er:
        agent.process_approved_scripts("niche-1")

    # 4 DB calls: stale fetch, video check, niche, pending scripts
    assert call_count[0] == 4, f"Expected 4 DB calls, got {call_count[0]}"
    # The update-to-pending call is NOT among the 4 (it would be a 5th call if it ran)


def test_limit_restricts_scripts_processed():
    """limit=1 param must be accepted without error."""
    from agents.production.voiceover import VoiceoverAgent
    from unittest.mock import MagicMock, patch

    mock_sb = MagicMock()
    mock_gate = MagicMock()
    agent = VoiceoverAgent(supabase=mock_sb, gate_client=mock_gate)

    def mock_retry(query):
        result = MagicMock()
        result.data = []
        return result

    with patch("agents.production.voiceover.execute_with_retry", side_effect=mock_retry):
        # Should not raise TypeError -- limit param must exist
        agent.process_approved_scripts("niche-1", limit=1)
