import pytest
from unittest.mock import MagicMock, patch
from agents.discovery.niche_scorer import NicheScorer, NicheScoreResult


@pytest.fixture
def scorer():
    mock_yt = MagicMock()
    mock_yt.search.return_value = [
        MagicMock(view_count=500000, duration_seconds=720),
        MagicMock(view_count=200000, duration_seconds=600),
    ]
    mock_yt.get_rpm_estimate.return_value = (15.0, 35.0)

    mock_reddit = MagicMock()
    mock_reddit.fetch_top_posts.return_value = [
        MagicMock(score=2000),
        MagicMock(score=1500),
        MagicMock(score=800),
    ]
    return NicheScorer(youtube_client=mock_yt, reddit_scraper=mock_reddit)


def test_score_returns_result_with_all_fields(scorer):
    with patch("agents.discovery.niche_scorer.TrendReq") as mock_trends:
        mock_trends.return_value.build_payload.return_value = None
        # patch the pandas DataFrame behavior
        import pandas as pd
        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.__getitem__ = lambda self, key: pd.Series([50, 60, 70, 80])
        mock_trends.return_value.interest_over_time.return_value = mock_df

        result = scorer.score("personal finance tips", category="personal_finance", subreddits=["personalfinance"])

    assert isinstance(result, NicheScoreResult)
    assert result.niche_name == "personal finance tips"
    assert result.final_score > 0
    assert result.rpm_min == 15.0
    assert result.rpm_max == 35.0


def test_score_handles_no_youtube_results(scorer):
    scorer._yt.search.return_value = []
    scorer._yt.get_rpm_estimate.return_value = (10.0, 20.0)
    with patch("agents.discovery.niche_scorer.TrendReq") as mock_trends:
        mock_df = MagicMock()
        mock_df.empty = True
        mock_trends.return_value.interest_over_time.return_value = mock_df
        result = scorer.score("obscure niche xyz", category="career", subreddits=["careeradvice"])
    # Should not raise; score should be low but defined
    assert result.final_score >= 0
