import pytest
from unittest.mock import MagicMock
from agents.performance.analytics_poller import (
    AnalyticsPoller, NichePerformance, should_promote, should_archive, should_flag_early
)


def test_should_promote_returns_true_when_all_thresholds_met():
    perf = NichePerformance(views_total=80, avg_watch_time_pct=0.40)
    assert should_promote(perf) is True


def test_should_promote_returns_false_when_views_too_low():
    perf = NichePerformance(views_total=30, avg_watch_time_pct=0.45)
    assert should_promote(perf) is False


def test_should_promote_returns_false_when_watch_time_too_low():
    perf = NichePerformance(views_total=100, avg_watch_time_pct=0.20)
    assert should_promote(perf) is False


def test_should_archive_returns_true_when_all_thresholds_missed():
    perf = NichePerformance(views_total=20, avg_watch_time_pct=0.20)
    assert should_archive(perf) is True


def test_should_archive_returns_false_when_any_threshold_met():
    perf = NichePerformance(views_total=20, avg_watch_time_pct=0.40)
    assert should_archive(perf) is False


def test_should_flag_early_returns_true_when_viral():
    perf = NichePerformance(views_total=250, avg_watch_time_pct=0.30)
    assert should_flag_early(perf) is True


def test_should_flag_early_returns_false_when_not_viral():
    perf = NichePerformance(views_total=150, avg_watch_time_pct=0.30)
    assert should_flag_early(perf) is False


def test_poll_niche_skips_when_no_videos():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.not_.is_.return_value = MagicMock()
    execute_mock = MagicMock()
    execute_mock.data = []

    poller = AnalyticsPoller(supabase=mock_sb)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "agents.performance.analytics_poller.execute_with_retry",
            lambda q: execute_mock,
        )
        result = poller.poll_niche("niche-1", "UCxxx", MagicMock())

    assert result is None


def test_poll_niche_raises_on_api_error():
    mock_sb = MagicMock()
    execute_mock = MagicMock()
    execute_mock.data = [{"youtube_video_id": "abc123", "video_type": "long"}]

    mock_analytics = MagicMock()
    mock_analytics.reports.return_value.query.return_value.execute.side_effect = Exception("403 Forbidden")

    poller = AnalyticsPoller(supabase=mock_sb)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "agents.performance.analytics_poller.execute_with_retry",
            lambda q: execute_mock,
        )
        with pytest.raises(Exception, match="403 Forbidden"):
            poller.poll_niche("niche-1", "UCxxx", mock_analytics)


def test_fetch_published_videos_queries_published_videos_table():
    mock_sb = MagicMock()
    execute_mock = MagicMock()
    execute_mock.data = [
        {"youtube_video_id": "vid-long-1", "video_type": "long"},
        {"youtube_video_id": "vid-short-1", "video_type": "short"},
    ]

    poller = AnalyticsPoller(supabase=mock_sb)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: execute_mock)
        ids, longs, shorts = poller._fetch_published_videos("niche-1")

    assert ids == ["vid-long-1", "vid-short-1"]
    assert longs == 1
    assert shorts == 1
    # Verify correct table
    assert mock_sb.table.call_args.args[0] == "published_videos"


def test_run_raises_after_all_niches_attempted_on_partial_failure():
    mock_sb = MagicMock()
    niche_data = MagicMock()
    niche_data.data = [
        {"id": "niche-good", "name": "Good", "status": "testing", "activated_at": None,
         "youtube_accounts": {"channel_id": "UCgood", "token_json": {"token": "good"}}},
        {"id": "niche-bad", "name": "Bad", "status": "testing", "activated_at": None,
         "youtube_accounts": {"channel_id": "UCbad", "token_json": {"token": "bad"}}},
    ]

    poller = AnalyticsPoller(supabase=mock_sb)

    call_count = {"n": 0}

    def fake_poll(niche_id, channel_id, svc):
        call_count["n"] += 1
        if niche_id == "niche-bad":
            raise Exception("403 Forbidden")
        return NichePerformance(views_total=10, avg_watch_time_pct=0.20)

    poller.poll_niche = fake_poll

    def fake_execute(q):
        return niche_data

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", fake_execute)
        mp.setattr("agents.performance.analytics_poller.build_youtube_service", lambda token_dict: MagicMock())
        mp.setattr("agents.performance.analytics_poller.build", lambda *a, **kw: MagicMock())
        with pytest.raises(RuntimeError, match="niche-bad"):
            poller.run()

    assert call_count["n"] == 2  # both niches were attempted
