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


def test_run_discovers_news_candidates():
    from agents.discovery.niche_scorer import NicheScoreResult
    mock_sb = MagicMock()
    mock_scorer = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 5  # 5 articles → qualifies

    scout = NicheScout(
        supabase=mock_sb,
        scorer=mock_scorer,
        gate_client=MagicMock(),
        news_adapters=[mock_adapter],
        news_keywords={"legal": ["lawsuit settlement"]},
    )

    # Return different niche_names for different queries (Pass 1 vs Pass 2)
    def side_effect(niche_name, category, subreddits):
        return NicheScoreResult(
            niche_name=niche_name, category=category, final_score=30.0,
            rpm_min=15.0, rpm_max=35.0, trend_score=1.0,
            reddit_activity=2.0, youtube_competition=2.0, avg_rpm=25.0,
        )

    mock_scorer.score.side_effect = side_effect
    mock_sb.table.return_value.select.return_value.execute.return_value.data = []
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    scout.run()

    scored_names = [call[0][0] for call in mock_scorer.score.call_args_list]
    assert "lawsuit settlement" in scored_names


def test_run_skips_news_candidates_below_threshold():
    from agents.discovery.niche_scorer import NicheScoreResult
    mock_sb = MagicMock()
    mock_scorer = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 4  # 4 articles → below threshold

    scout = NicheScout(
        supabase=mock_sb,
        scorer=mock_scorer,
        gate_client=MagicMock(),
        news_adapters=[mock_adapter],
        news_keywords={"legal": ["lawsuit settlement"]},
    )

    # Return different niche_names for different queries
    def side_effect(niche_name, category, subreddits):
        return NicheScoreResult(
            niche_name=niche_name, category=category, final_score=10.0,
            rpm_min=10.0, rpm_max=20.0, trend_score=1.0,
            reddit_activity=1.0, youtube_competition=1.0, avg_rpm=15.0,
        )

    mock_scorer.score.side_effect = side_effect
    mock_sb.table.return_value.select.return_value.execute.return_value.data = []
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    scout.run()

    # Pass 1 scores 8 categories; "lawsuit settlement" should NOT be among them (< 5 articles)
    scored_names = [call[0][0] for call in mock_scorer.score.call_args_list]
    assert "lawsuit settlement" not in scored_names
