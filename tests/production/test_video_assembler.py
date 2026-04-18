import pytest
from unittest.mock import MagicMock, patch
from agents.production.video_assembler import PexelsClient, extract_scene_tags


def test_extract_scene_tags_finds_tags():
    script = """
    So she opened the letter [B-ROLL: person reading mail] and her face dropped.
    Then she called her lawyer [B-ROLL: phone call close-up] immediately.
    """
    tags = extract_scene_tags(script)
    assert tags == ["person reading mail", "phone call close-up"]


def test_extract_scene_tags_returns_empty_for_no_tags():
    tags = extract_scene_tags("No scene tags here at all.")
    assert tags == []


def test_pexels_search_returns_video_urls(tmp_path):
    client = PexelsClient(api_key="test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "videos": [
            {
                "video_files": [
                    {"quality": "hd", "width": 1920, "link": "https://pexels.com/clip1.mp4"},
                    {"quality": "sd", "width": 1280, "link": "https://pexels.com/clip1_sd.mp4"},
                ]
            }
        ]
    }
    with patch("requests.get", return_value=mock_resp):
        urls = client.search_video_urls("person reading mail", count=1)
    assert urls == ["https://pexels.com/clip1.mp4"]
