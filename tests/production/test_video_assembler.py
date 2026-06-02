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


def test_generate_broll_tags_returns_list_from_valid_json():
    from agents.production.video_assembler import _generate_broll_tags
    with patch("agents.production.video_assembler.complete") as mock_llm:
        mock_llm.return_value = '["stressed person reading letter", "couple arguing over bills", "lawyer at desk"]'
        tags = _generate_broll_tags("Script about an insurance dispute.", is_short=False)
    assert tags == ["stressed person reading letter", "couple arguing over bills", "lawyer at desk"]


def test_generate_broll_tags_falls_back_on_malformed_json():
    from agents.production.video_assembler import _generate_broll_tags, BROLL_FALLBACK_TAGS
    with patch("agents.production.video_assembler.complete") as mock_llm:
        mock_llm.return_value = "Sorry, here are some terms: person, office, stress"
        tags = _generate_broll_tags("Some script text.", is_short=False)
    assert tags == BROLL_FALLBACK_TAGS


def test_generate_broll_tags_falls_back_on_empty_array():
    from agents.production.video_assembler import _generate_broll_tags, BROLL_FALLBACK_TAGS
    with patch("agents.production.video_assembler.complete") as mock_llm:
        mock_llm.return_value = "[]"
        tags = _generate_broll_tags("Some script text.", is_short=False)
    assert tags == BROLL_FALLBACK_TAGS


def test_generate_broll_tags_short_prompt_differs_from_long():
    """Short prompt should emphasise faces/expressions for thumbnail auto-selection."""
    from agents.production.video_assembler import BROLL_TAGS_PROMPT_SHORT, BROLL_TAGS_PROMPT_LONG
    assert "face" in BROLL_TAGS_PROMPT_SHORT.lower() or "expression" in BROLL_TAGS_PROMPT_SHORT.lower()


def test_assemble_uses_llm_tags_not_fallback(tmp_path):
    """assemble() must call _generate_broll_tags and pass results to Pexels search."""
    from agents.production.video_assembler import VideoAssembler, PexelsClient

    mock_sb = MagicMock()
    mock_gate = MagicMock()
    mock_pexels = MagicMock(spec=PexelsClient)
    mock_pexels.search_video_urls.return_value = []

    assembler = VideoAssembler(
        supabase=mock_sb, gate_client=mock_gate,
        pexels_client=mock_pexels, output_dir=str(tmp_path)
    )

    with patch("agents.production.video_assembler._generate_broll_tags") as mock_tags, \
         patch("agents.production.video_assembler.AudioFileClip") as mock_audio, \
         patch("agents.production.video_assembler.ColorClip") as mock_color, \
         patch("agents.production.video_assembler.concatenate_videoclips"), \
         patch.object(assembler, "_upload_video", return_value="https://s3/video.mp4"):
        mock_tags.return_value = ["stressed person laptop", "lawyer documents"]
        mock_audio.return_value.duration = 5.0
        mock_audio.return_value.set_audio = MagicMock()
        mock_clip = MagicMock()
        mock_clip.duration = 5.0
        mock_clip.subclip.return_value = mock_clip
        mock_color.return_value = mock_clip

        assembler.assemble(
            audio_path="/tmp/fake.mp3",
            srt_path="/tmp/fake.srt",
            script_text="A story about an insurance dispute.",
            output_stem="test_video",
            is_short=False,
        )

    mock_tags.assert_called_once_with("A story about an insurance dispute.", is_short=False)
    searched_queries = [call.args[0] for call in mock_pexels.search_video_urls.call_args_list]
    assert "stressed person laptop" in searched_queries


def test_short_uses_short_clip_cap(tmp_path):
    from agents.production.video_assembler import VideoAssembler, PexelsClient, SHORT_MAX_CLIP_SEC

    mock_pexels = MagicMock(spec=PexelsClient)
    mock_clip = MagicMock()
    mock_clip.duration = 20.0
    mock_clip.w = 1080
    mock_clip.h = 1920
    mock_pexels.search_video_urls.return_value = ["https://pexels.com/clip.mp4"]

    assembler = VideoAssembler(
        supabase=MagicMock(), gate_client=MagicMock(),
        pexels_client=mock_pexels, output_dir=str(tmp_path)
    )

    with patch("agents.production.video_assembler._generate_broll_tags", return_value=["person stressed"]), \
         patch("agents.production.video_assembler.AudioFileClip") as mock_audio, \
         patch("agents.production.video_assembler.VideoFileClip", return_value=mock_clip), \
         patch("agents.production.video_assembler.concatenate_videoclips"), \
         patch.object(assembler, "_upload_video", return_value="https://s3/video.mp4"):
        mock_audio.return_value.duration = 5.0
        mock_audio.return_value.set_audio = MagicMock()

        assembler.assemble(
            audio_path="/tmp/fake.mp3",
            srt_path="/tmp/fake.srt",
            script_text="Short script.",
            output_stem="test_short",
            is_short=True,
        )

    subclip_calls = mock_clip.subclip.call_args_list
    assert all(call.args[1] <= SHORT_MAX_CLIP_SEC for call in subclip_calls if len(call.args) >= 2)


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

    # Track all execute_with_retry calls so we can inspect the DB operations
    exec_calls = []

    def fake_exec(q):
        exec_calls.append(q)
        result = MagicMock()
        # First call = _query_pending_videos("long"), return our video
        # Second call = _query_pending_videos("short"), return nothing
        # Subsequent calls = delete/update from the S3-error handler
        result.data = [video] if len(exec_calls) == 1 else []
        return result

    s3_error = botocore.exceptions.ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "GetObject"
    )

    with patch("agents.production.video_assembler.execute_with_retry", side_effect=fake_exec):
        with patch.object(assembler, "assemble", side_effect=s3_error):
            assembler.process_approved_voiceovers("niche-1")

    # Both videos and scripts tables must have been touched
    table_calls = [c.args[0] for c in mock_sb.table.call_args_list]
    assert "videos" in table_calls
    assert "scripts" in table_calls

    # scripts.update must use assembly_failed, never pending
    all_update_status_values = [
        c.args[0]["status"]
        for c in mock_sb.table.return_value.update.call_args_list
        if c.args and isinstance(c.args[0], dict) and "status" in c.args[0]
    ]
    assert "assembly_failed" in all_update_status_values, (
        f"Expected assembly_failed in status updates, got: {all_update_status_values}"
    )
    assert "pending" not in all_update_status_values, (
        "Must not reset to pending — that burns OpenAI quota"
    )
