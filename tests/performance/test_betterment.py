import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Test: _summary() includes youtube_video_id
# ---------------------------------------------------------------------------
def test_summary_includes_youtube_video_id():
    from agents.performance.insights_agent import InsightsAgent

    agent = InsightsAgent.__new__(InsightsAgent)
    video = {
        "youtube_video_id": "abc123",
        "title": "Test Title",
        "niche_name": "Finance",
        "video_type": "short",
        "views": 10,
        "avg_view_pct": 0.37,
        "word_count": 150,
        "duration_sec": 62,
    }
    result = agent._summary(video)
    assert result["youtube_video_id"] == "abc123"
    assert result["title"] == "Test Title"


# ---------------------------------------------------------------------------
# Test: _generate_betterment() parses valid JSON response
# ---------------------------------------------------------------------------
def test_generate_betterment_parses_valid_json():
    from agents.performance.insights_agent import InsightsAgent

    agent = InsightsAgent.__new__(InsightsAgent)

    mock_response = json.dumps({
        "narrative": "- Direct titles outperform curiosity hooks\n- Finance topics with personal stakes win",
        "content_patterns": {
            "winning_angles": ["Personal-stakes finance", "Direct problem-statement titles"],
            "avoid": ["Curiosity-gap hooks", "Tech novelty without viewer impact"]
        }
    })

    stats = {
        "top_5_videos": [{"title": "Why Working Two Jobs Leaves You Vulnerable", "views": 10, "watch_pct": 0.37}],
        "bottom_5_videos": [{"title": "AI Cancer Detection", "views": 0, "watch_pct": 0.0}],
    }

    with patch("agents.performance.insights_agent.anthropic_client.complete_sonnet", return_value=mock_response):
        result = agent._generate_betterment(stats)

    assert result["narrative"] == "- Direct titles outperform curiosity hooks\n- Finance topics with personal stakes win"
    assert "Personal-stakes finance" in result["content_patterns"]["winning_angles"]
    assert "Curiosity-gap hooks" in result["content_patterns"]["avoid"]


# ---------------------------------------------------------------------------
# Test: _generate_betterment() falls back gracefully on malformed JSON
# ---------------------------------------------------------------------------
def test_generate_betterment_fallback_on_bad_json():
    from agents.performance.insights_agent import InsightsAgent

    agent = InsightsAgent.__new__(InsightsAgent)

    with patch("agents.performance.insights_agent.anthropic_client.complete_sonnet", return_value="not json at all"):
        result = agent._generate_betterment({"top_5_videos": [], "bottom_5_videos": []})

    assert result["narrative"] == ""
    assert result["content_patterns"] == {"winning_angles": [], "avoid": []}
