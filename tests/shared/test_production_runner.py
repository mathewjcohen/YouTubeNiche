import pytest
from unittest.mock import MagicMock, patch
from agents.shared.production_runner import ProductionRunner


@pytest.fixture
def runner():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return ProductionRunner(supabase=mock_sb, gate_client=mock_gate)


def test_run_exits_when_pipeline_disabled(runner):
    """When pipeline_enabled=false, run() does nothing."""
    with patch("agents.shared.production_runner.get_app_setting", return_value="false"), \
         patch("agents.shared.production_runner.execute_with_retry") as mock_retry:
        runner.run()
    mock_retry.assert_not_called()


def test_run_processes_all_active_niches(runner):
    """run() calls _process_niche for all promoted and testing niches."""
    niches = [
        {"id": "n1", "name": "legal", "channel_state": "linked", "status": "promoted"},
        {"id": "n2", "name": "tax", "channel_state": "linked", "status": "testing"},
    ]
    with patch("agents.shared.production_runner.get_app_setting", return_value="true"), \
         patch("agents.shared.production_runner.execute_with_retry") as mock_retry, \
         patch.object(runner, "_process_niche") as mock_process:
        mock_retry.return_value.data = niches
        runner.run()
    assert mock_process.call_count == 2


def test_process_niche_runs_all_four_stages(runner):
    """_process_niche calls voiceover, thumbnail, assembler, uploader in order."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "linked", "status": "promoted"}
    call_order = []

    mock_vo = MagicMock()
    mock_vo.process_approved_scripts.side_effect = lambda niche_id, limit: call_order.append("voiceover")

    mock_tg = MagicMock()
    mock_tg.process_approved_scripts.side_effect = lambda niche_id: call_order.append("thumbnail")

    mock_va = MagicMock()
    mock_va.process_approved_voiceovers.side_effect = lambda niche_id: call_order.append("assembler")

    mock_up = MagicMock()
    mock_up.process_approved_videos.side_effect = lambda niche_id: call_order.append("uploader")

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=mock_vo), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=mock_tg), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=mock_va), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=mock_up):
        runner._process_niche(niche)

    assert call_order == ["voiceover", "thumbnail", "assembler", "uploader"]


def test_process_niche_skips_upload_when_channel_not_linked(runner):
    """Upload is skipped when channel_state != 'linked'."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "unlinked", "status": "promoted"}

    mock_up = MagicMock()

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=MagicMock()), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=MagicMock()), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=MagicMock()), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=mock_up):
        runner._process_niche(niche)

    mock_up.process_approved_videos.assert_not_called()


def test_voiceover_called_with_limit_1(runner):
    """Voiceover must be called with limit=1 to prevent exceeding YouTube quota."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "linked", "status": "promoted"}
    mock_vo = MagicMock()

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=mock_vo), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=MagicMock()), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=MagicMock()), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=MagicMock()):
        runner._process_niche(niche)

    mock_vo.process_approved_scripts.assert_called_once_with("niche-1", limit=1)
