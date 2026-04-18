import pytest
from unittest.mock import MagicMock, patch
from agents.discovery.niche_scout import NicheScout


@pytest.fixture
def scout():
    mock_sb = MagicMock()
    mock_scorer = MagicMock()
    mock_gate = MagicMock()
    return NicheScout(supabase=mock_sb, scorer=mock_scorer, gate_client=mock_gate)


def test_run_scores_all_categories(scout):
    from agents.discovery.niche_scorer import NicheScoreResult
    scout._scorer.score.return_value = NicheScoreResult(
        niche_name="test", category="career", final_score=42.0,
        rpm_min=10.0, rpm_max=20.0, trend_score=1.2,
        reddit_activity=3.0, youtube_competition=2.0, avg_rpm=15.0,
    )
    scout._sb.table.return_value.select.return_value.execute.return_value.data = []
    scout._sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    scout.run()

    # Should have called score() once per category (8 categories)
    assert scout._scorer.score.call_count == 8


def test_run_upserts_top_candidates(scout):
    from agents.discovery.niche_scorer import NicheScoreResult
    scout._scorer.score.return_value = NicheScoreResult(
        niche_name="test", category="legal", final_score=55.0,
        rpm_min=20.0, rpm_max=50.0, trend_score=1.5,
        reddit_activity=4.0, youtube_competition=2.5, avg_rpm=35.0,
    )
    scout._sb.table.return_value.select.return_value.execute.return_value.data = []
    scout._sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    scout.run()

    # upsert should have been called for each scored niche
    assert scout._sb.table.return_value.upsert.called
