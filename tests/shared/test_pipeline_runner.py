import pytest
from unittest.mock import MagicMock, patch, call
from agents.shared.pipeline_runner import PipelineRunner


@pytest.fixture
def runner():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return PipelineRunner(supabase=mock_sb, gate_client=mock_gate)


def test_run_calls_process_niche_for_active_niches(runner):
    niche_data = {"id": "niche-1", "name": "legal rights", "category": "legal"}
    runner._sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [niche_data]
    with patch.object(runner, "_process_niche") as mock_process:
        runner.run()
    assert mock_process.call_count == 2
    assert mock_process.call_args_list == [call(niche_data), call(niche_data)]


def test_process_niche_skips_when_no_active_items(runner):
    runner._sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    with patch("agents.shared.pipeline_runner.get_env"), \
         patch("agents.production.video_assembler.PexelsClient"):
        # Should not raise
        runner._process_niche({"id": "niche-1", "name": "legal", "category": "legal"})
