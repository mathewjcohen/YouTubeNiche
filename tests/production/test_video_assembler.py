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


def test_s3_404_sets_assembly_failed_not_pending():
    """S3 404 on audio must set scripts.status='assembly_failed', not 'pending'.
    Resetting to 'pending' causes the voiceover agent to regenerate audio (burns OpenAI quota).
    """
    import botocore.exceptions
    from agents.production.video_assembler import VideoAssembler, PexelsClient

    mock_sb = MagicMock()
    mock_gate = MagicMock()
    pexels = MagicMock(spec=PexelsClient)

    assembler = VideoAssembler(supabase=mock_sb, gate_client=mock_gate, pexels_client=pexels)

    video = {
        "id": "video-1",
        "script_id": "script-1",
        "niche_id": "niche-1",
        "video_type": "long",
        "audio_path": "https://bucket.s3.region.amazonaws.com/audio/test.mp3",
        "srt_path": "https://bucket.s3.region.amazonaws.com/audio/test.srt",
        "scripts": {"long_form_text": "Hello world.", "short_text": "Short."},
    }

    # videos query returns our test video
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [video]

    # assemble() raises S3 404
    s3_error = botocore.exceptions.ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "GetObject"
    )
    with patch.object(assembler, "assemble", side_effect=s3_error):
        assembler.process_approved_voiceovers("niche-1")

    # Verify scripts.status was set to assembly_failed (not pending)
    update_calls = mock_sb.table.return_value.update.call_args_list
    status_values = [c.args[0].get("status") for c in update_calls if c.args and "status" in c.args[0]]
    assert "assembly_failed" in status_values, f"Expected assembly_failed in status updates, got: {status_values}"
    assert "pending" not in status_values, "Must not reset to pending — that burns OpenAI quota"
