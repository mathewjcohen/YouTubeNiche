import pytest
from unittest.mock import MagicMock
from agents.performance.analytics_poller import (
    AnalyticsPoller, NichePerformance, should_promote, should_archive, should_flag_early
)


def test_should_promote_returns_true_when_all_thresholds_met():
    perf = NichePerformance(views_total=80, ctr=0.04, avg_watch_time_pct=0.40)
    assert should_promote(perf) is True


def test_should_promote_returns_false_when_views_too_low():
    perf = NichePerformance(views_total=30, ctr=0.05, avg_watch_time_pct=0.45)
    assert should_promote(perf) is False


def test_should_promote_returns_false_when_ctr_too_low():
    perf = NichePerformance(views_total=100, ctr=0.02, avg_watch_time_pct=0.40)
    assert should_promote(perf) is False


def test_should_archive_returns_true_when_all_thresholds_missed():
    perf = NichePerformance(views_total=20, ctr=0.01, avg_watch_time_pct=0.20)
    assert should_archive(perf) is True


def test_should_archive_returns_false_when_any_threshold_met():
    # Only CTR passes, but that's enough to not archive
    perf = NichePerformance(views_total=20, ctr=0.04, avg_watch_time_pct=0.20)
    assert should_archive(perf) is False


def test_should_flag_early_returns_true_when_viral():
    perf = NichePerformance(views_total=250, ctr=0.06, avg_watch_time_pct=0.30)
    assert should_flag_early(perf) is True


def test_should_flag_early_returns_false_when_not_viral():
    perf = NichePerformance(views_total=150, ctr=0.06, avg_watch_time_pct=0.30)
    assert should_flag_early(perf) is False
