import pytest
from unittest.mock import patch, MagicMock
from agents.discovery.youtube_client import YouTubeClient, VideoSearchResult


@pytest.fixture
def client():
    return YouTubeClient(rapidapi_key="test-rapid-key")


def test_search_returns_results_from_invidious(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "videoId": "abc123",
            "title": "How to negotiate your salary",
            "viewCount": 150000,
            "lengthSeconds": 720,
            "author": "Career Channel",
        }
    ]
    with patch("requests.get", return_value=mock_response):
        results = client.search("salary negotiation tips", max_results=5)
    assert len(results) == 1
    assert results[0].video_id == "abc123"
    assert results[0].view_count == 150000


def test_falls_back_to_rapidapi_on_invidious_failure(client):
    invidious_fail = MagicMock()
    invidious_fail.status_code = 500

    rapidapi_response = MagicMock()
    rapidapi_response.status_code = 200
    rapidapi_response.json.return_value = {
        "contents": [
            {
                "video": {
                    "videoId": "xyz789",
                    "title": "Salary Tips",
                    "stats": {"views": 80000},
                    "lengthSeconds": 600,
                    "author": {"title": "Jobs Channel"},
                }
            }
        ]
    }

    with patch("requests.get", side_effect=[invidious_fail, invidious_fail, invidious_fail, rapidapi_response]):
        results = client.search("salary tips", max_results=5)
    assert len(results) == 1
    assert results[0].video_id == "xyz789"


def test_falls_back_to_rpm_proxy_when_all_fail(client):
    fail = MagicMock()
    fail.status_code = 500
    with patch("requests.get", return_value=fail):
        results = client.search("insurance advice", max_results=5)
    # RPM proxy returns empty search results but doesn't raise
    assert results == []


def test_get_rpm_estimate_returns_known_category(client):
    assert client.get_rpm_estimate("insurance") == (25.0, 45.0)


def test_get_rpm_estimate_returns_default_for_unknown(client):
    low, high = client.get_rpm_estimate("cooking")
    assert low == 2.0
    assert high == 8.0
