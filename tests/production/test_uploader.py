import pytest
from unittest.mock import MagicMock, patch
from agents.production.uploader import YouTubeUploader


@pytest.fixture
def uploader():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    mock_gate.advance_or_pause.return_value = "approved"
    with patch("agents.production.uploader.build_youtube_service", return_value=MagicMock()):
        return YouTubeUploader(supabase=mock_sb, gate_client=mock_gate)


def test_upload_video_calls_youtube_api(uploader, tmp_path):
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video data")
    thumb_path = tmp_path / "test.jpg"
    thumb_path.write_bytes(b"fake thumb data")

    mock_yt = uploader._yt
    mock_yt.videos.return_value.insert.return_value.next_chunk.return_value = (
        None, {"id": "yt-video-id-abc"}
    )

    video_id = uploader.upload(
        video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        title="Test Video Title",
        description="Test description",
        tags=["test", "legal"],
        is_short=False,
    )
    assert video_id == "yt-video-id-abc"


def test_upload_raises_on_missing_file(uploader):
    with pytest.raises(FileNotFoundError):
        uploader.upload(
            video_path="/nonexistent/path.mp4",
            thumbnail_path="/nonexistent/thumb.jpg",
            title="Title",
            description="Desc",
            tags=[],
            is_short=False,
        )


BASE_URL = "https://project.supabase.co/storage/v1/object/public"


def _make_video(video_id: str = "abcdef12345678", video_type: str = "long") -> dict:
    return {
        "id": video_id,
        "video_type": video_type,
        "audio_path": f"{BASE_URL}/voiceovers/{video_id[:8]}_{video_type}.mp3",
        "srt_path": f"{BASE_URL}/voiceovers/{video_id[:8]}_{video_type}.srt",
        "thumbnail_path": f"{BASE_URL}/thumbnails/{video_id[:8]}_{video_type}_thumb.jpg",
        "video_path": f"https://mybucket.s3.us-east-1.amazonaws.com/{video_id[:8]}_{video_type}_remotion.mp4",
    }


def test_delete_supabase_assets_removes_voiceover_and_thumbnail(uploader):
    storage = uploader._sb.storage
    storage.from_.return_value.list.return_value = []

    uploader._delete_supabase_assets(_make_video())

    remove_calls = [call.args[0] for call in storage.from_.return_value.remove.call_args_list]
    assert ["abcdef12_long.mp3"] in remove_calls
    assert ["abcdef12_long.srt"] in remove_calls
    assert ["abcdef12_long_thumb.jpg"] in remove_calls


def test_delete_supabase_assets_removes_broll_clips(uploader):
    vid = _make_video()
    prefix = f"broll_{vid['id'][:8]}_{vid['video_type']}_remotion_"
    broll_files = [
        {"name": f"{prefix}0.mp4"},
        {"name": f"{prefix}1.mp4"},
        {"name": f"{prefix}2.mp4"},
    ]
    storage = uploader._sb.storage
    storage.from_.return_value.list.return_value = broll_files

    uploader._delete_supabase_assets(vid)

    remove_calls = [call.args[0] for call in storage.from_.return_value.remove.call_args_list]
    assert [f"{prefix}0.mp4", f"{prefix}1.mp4", f"{prefix}2.mp4"] in remove_calls


def test_delete_supabase_assets_skips_missing_urls(uploader):
    storage = uploader._sb.storage
    storage.from_.return_value.list.return_value = []

    uploader._delete_supabase_assets({"id": "abcdef12345678", "video_type": "long"})

    storage.from_.return_value.remove.assert_not_called()


def test_delete_supabase_assets_raises_on_error(uploader):
    storage = uploader._sb.storage
    storage.from_.return_value.remove.side_effect = Exception("storage error")
    storage.from_.return_value.list.return_value = []

    with pytest.raises(Exception, match="storage error"):
        uploader._delete_supabase_assets(_make_video())
