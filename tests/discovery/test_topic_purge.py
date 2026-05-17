import json
import pytest
from unittest.mock import patch, MagicMock


PATTERNS = {
    "winning_angles": ["Personal-stakes finance", "Direct problem-statement titles"],
    "avoid": ["Curiosity-gap hooks", "Tech novelty without viewer impact"]
}


# ---------------------------------------------------------------------------
# Test: _score_batch() parses a valid Claude response
# ---------------------------------------------------------------------------
def test_score_batch_parses_valid_response():
    from agents.discovery.topic_purge import TopicPurge

    purge = TopicPurge.__new__(TopicPurge)
    purge._content_patterns = PATTERNS

    topics = [
        {"id": "aaa", "title": "Why Rising Rent Crushes Middle-Class Families"},
        {"id": "bbb", "title": "AI Discovers New Protein"},
    ]
    mock_response = json.dumps([
        {"id": "aaa", "keep": True, "reason": None},
        {"id": "bbb", "keep": False, "reason": "Tech novelty without viewer stake"},
    ])

    with patch("agents.discovery.topic_purge.anthropic_client.complete_sonnet", return_value=mock_response):
        results = purge._score_batch(topics)

    assert len(results) == 2
    keep_map = {r["id"]: r for r in results}
    assert keep_map["aaa"]["keep"] is True
    assert keep_map["bbb"]["keep"] is False
    assert "Tech novelty" in keep_map["bbb"]["reason"]


# ---------------------------------------------------------------------------
# Test: _score_batch() handles malformed JSON gracefully (keeps all)
# ---------------------------------------------------------------------------
def test_score_batch_fallback_on_bad_json():
    from agents.discovery.topic_purge import TopicPurge

    purge = TopicPurge.__new__(TopicPurge)
    purge._content_patterns = PATTERNS

    topics = [{"id": "aaa", "title": "Some Topic"}]

    with patch("agents.discovery.topic_purge.anthropic_client.complete_sonnet", return_value="not json"):
        results = purge._score_batch(topics)

    assert all(r["keep"] for r in results)


# ---------------------------------------------------------------------------
# Test: _build_prompt() includes winning angles and avoid patterns
# ---------------------------------------------------------------------------
def test_build_prompt_includes_patterns():
    from agents.discovery.topic_purge import TopicPurge

    purge = TopicPurge.__new__(TopicPurge)
    purge._content_patterns = PATTERNS

    topics = [{"id": "x", "title": "Test Title"}]
    prompt = purge._build_prompt(topics)

    assert "Personal-stakes finance" in prompt
    assert "Curiosity-gap hooks" in prompt
    assert "Test Title" in prompt
