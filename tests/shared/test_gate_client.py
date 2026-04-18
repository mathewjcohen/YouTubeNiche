import pytest
from unittest.mock import MagicMock
from agents.shared.gate_client import GateClient, GateNumber

def make_client():
    mock_sb = MagicMock()
    return GateClient(mock_sb), mock_sb

def test_gate_enabled_returns_true_when_enabled():
    client, mock_sb = make_client()
    mock_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.limit.return_value.execute.return_value.data = [{"enabled": True}]
    assert client.gate_enabled(GateNumber.SCRIPT, niche_id=None) is True

def test_gate_enabled_niche_override_takes_precedence():
    client, mock_sb = make_client()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"enabled": False}]
    assert client.gate_enabled(GateNumber.SCRIPT, niche_id="test-niche-uuid") is False

def test_gate_enabled_falls_back_to_global_when_no_niche_override():
    client, mock_sb = make_client()
    # No niche-specific override (empty data)
    niche_chain = mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value
    niche_chain.data = []
    # Global config returns enabled=True
    global_chain = mock_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.limit.return_value.execute.return_value
    global_chain.data = [{"enabled": True}]
    assert client.gate_enabled(GateNumber.SCRIPT, niche_id="some-niche") is True

def test_set_gate_item_state_calls_supabase_update():
    client, mock_sb = make_client()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    client.set_item_gate_state(table="scripts", item_id="abc", gate_column="gate3_state", state="awaiting_review")
    mock_sb.table.assert_called_with("scripts")
