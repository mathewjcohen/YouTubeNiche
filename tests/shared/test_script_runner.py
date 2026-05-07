import pytest
from unittest.mock import MagicMock, patch
from agents.shared.script_runner import ScriptRunner


@pytest.fixture
def runner():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return ScriptRunner(supabase=mock_sb, gate_client=mock_gate)


def test_run_exits_when_pipeline_disabled(runner):
    """When pipeline_enabled=false, run() does nothing."""
    with patch("agents.shared.script_runner.get_app_setting", return_value="false"), \
         patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        runner.run()
    mock_retry.assert_not_called()


def test_run_processes_all_active_niches(runner):
    """run() calls _process_niche for each active niche (promoted + testing)."""
    niches = [
        {"id": "n1", "name": "legal", "category": "legal", "status": "promoted"},
        {"id": "n2", "name": "tax", "category": "tax", "status": "testing"},
    ]
    with patch("agents.shared.script_runner.get_app_setting", return_value="true"), \
         patch("agents.shared.script_runner.execute_with_retry") as mock_retry, \
         patch.object(runner, "_process_niche") as mock_process:
        mock_retry.return_value.data = niches
        runner.run()
    assert mock_process.call_count == 2
    processed_ids = [c.args[0]["id"] for c in mock_process.call_args_list]
    assert processed_ids == ["n1", "n2"]


def test_process_niche_skips_when_no_approved_topics(runner):
    """No approved topics → scriptwriter is not called."""
    with patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        mock_retry.return_value.data = []  # no approved topics
        with patch("agents.shared.script_runner.Scriptwriter") as mock_sw:
            runner._process_niche({"id": "niche-1", "name": "legal", "category": "legal"})
    mock_sw.assert_not_called()


def test_process_niche_runs_scriptwriter_when_topics_approved(runner):
    """Approved topics → Scriptwriter.process_approved_topics is called."""
    niche = {"id": "niche-1", "name": "legal", "category": "legal"}

    with patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        mock_retry.return_value.data = [{"id": "topic-1"}]  # one approved topic
        mock_writer = MagicMock()
        with patch("agents.shared.script_runner.Scriptwriter", return_value=mock_writer):
            runner._process_niche(niche)

    mock_writer.process_approved_topics.assert_called_once_with("niche-1")
