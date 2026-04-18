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
