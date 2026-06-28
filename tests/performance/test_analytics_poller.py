import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call
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
    execute_mock = MagicMock()
    execute_mock.data = []

    poller = AnalyticsPoller(supabase=mock_sb)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "agents.performance.analytics_poller.execute_with_retry",
            lambda q: execute_mock,
        )
        result = poller.poll_niche("niche-1", "UCxxx", MagicMock(), MagicMock(), [])

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
            poller.poll_niche("niche-1", "UCxxx", mock_analytics, MagicMock(), [])


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
        rows = poller._fetch_published_videos("niche-1")

    assert [r["youtube_video_id"] for r in rows] == ["vid-long-1", "vid-short-1"]
    assert sum(1 for r in rows if r["video_type"] == "long") == 1
    assert sum(1 for r in rows if r["video_type"] == "short") == 1
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

    def fake_poll(niche_id, channel_id, analytics, yt_service, all_ids):
        call_count["n"] += 1
        if niche_id == "niche-bad":
            raise Exception("403 Forbidden")
        return NichePerformance(views_total=10, avg_watch_time_pct=0.20)

    poller.poll_niche = fake_poll
    poller._fetch_published_videos = lambda niche_id: []
    poller._backfill_published_video_metadata = lambda *a, **kw: None
    poller._sync_published_videos = lambda *a, **kw: None
    poller._recover_pipeline_videos = lambda *a, **kw: 0
    poller._discover_channel_orphans = lambda *a, **kw: 0
    poller._flag_and_analyze_zombies = lambda *a, **kw: None

    def fake_execute(q):
        return niche_data

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", fake_execute)
        mp.setattr("agents.performance.analytics_poller.build_youtube_service", lambda token_dict: MagicMock())
        mp.setattr("agents.performance.analytics_poller.build", lambda *a, **kw: MagicMock())
        with pytest.raises(RuntimeError, match="niche-bad"):
            poller.run()

    assert call_count["n"] == 2  # both niches were attempted


# --- zombie flagging ---

def _make_poller():
    return AnalyticsPoller(supabase=MagicMock())


def _ts(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def test_flag_and_analyze_zombies_marks_old_zero_view_video(capsys):
    poller = _make_poller()
    published_rows = [
        {"youtube_video_id": "old-zero", "video_type": "short", "title": "Short A",
         "duration_sec": 45, "status": "live", "uploaded_at": _ts(40), "script_id": None},
    ]
    # video_analytics returns 0 views for the video; scripts returns empty
    va_result = MagicMock()
    va_result.data = [{"youtube_video_id": "old-zero", "views": 0}]
    scripts_result = MagicMock()
    scripts_result.data = []
    update_result = MagicMock()
    update_result.data = []

    call_seq = iter([va_result, update_result, scripts_result])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: next(call_seq))
        poller._flag_and_analyze_zombies("niche-1", "Test Niche", published_rows)

    out = capsys.readouterr().out
    assert "1 new zombie" in out


def test_flag_and_analyze_zombies_skips_recent_video(capsys):
    poller = _make_poller()
    published_rows = [
        {"youtube_video_id": "new-zero", "video_type": "short", "title": "New Short",
         "duration_sec": 45, "status": "live", "uploaded_at": _ts(10), "script_id": None},
    ]
    va_result = MagicMock()
    va_result.data = [{"youtube_video_id": "new-zero", "views": 0}]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: va_result)
        poller._flag_and_analyze_zombies("niche-1", "Test Niche", published_rows)

    out = capsys.readouterr().out
    assert "zombie" not in out


def test_flag_and_analyze_zombies_skips_video_with_views(capsys):
    poller = _make_poller()
    published_rows = [
        {"youtube_video_id": "old-views", "video_type": "long", "title": "Long A",
         "duration_sec": 600, "status": "live", "uploaded_at": _ts(40), "script_id": None},
    ]
    va_result = MagicMock()
    va_result.data = [{"youtube_video_id": "old-views", "views": 50}]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: va_result)
        poller._flag_and_analyze_zombies("niche-1", "Test Niche", published_rows)

    out = capsys.readouterr().out
    assert "zombie" not in out


def test_flag_and_analyze_zombies_skips_already_zombie(capsys):
    poller = _make_poller()
    published_rows = [
        {"youtube_video_id": "already-zombie", "video_type": "short", "title": "Old Short",
         "duration_sec": 30, "status": "zombie", "uploaded_at": _ts(60), "script_id": None},
    ]
    va_result = MagicMock()
    va_result.data = []  # zero lifetime views

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: va_result)
        poller._flag_and_analyze_zombies("niche-1", "Test Niche", published_rows)

    out = capsys.readouterr().out
    # no "new zombie" message — it was already flagged
    assert "new zombie" not in out


def test_flag_and_analyze_zombies_prints_comparison_when_both_groups_exist(capsys):
    poller = _make_poller()
    published_rows = [
        {"youtube_video_id": "zombie-1", "video_type": "short", "title": "Short Z",
         "duration_sec": 40, "status": "live", "uploaded_at": _ts(50), "script_id": "s1"},
        {"youtube_video_id": "performer-1", "video_type": "long", "title": "Long P",
         "duration_sec": 700, "status": "live", "uploaded_at": _ts(50), "script_id": "s2"},
    ]
    va_result = MagicMock()
    va_result.data = [
        {"youtube_video_id": "zombie-1", "views": 0},
        {"youtube_video_id": "performer-1", "views": 100},
    ]
    update_result = MagicMock()
    update_result.data = []
    scripts_result = MagicMock()
    scripts_result.data = [
        {"id": "s1", "long_form_text": None, "short_text": "short script words here"},
        {"id": "s2", "long_form_text": "long script " + "word " * 900, "short_text": None},
    ]

    call_seq = iter([va_result, update_result, scripts_result])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agents.performance.analytics_poller.execute_with_retry", lambda q: next(call_seq))
        poller._flag_and_analyze_zombies("niche-1", "Test Niche", published_rows)

    out = capsys.readouterr().out
    assert "zombie vs performer" in out
    assert "duration" in out
    assert "word count" in out
