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
