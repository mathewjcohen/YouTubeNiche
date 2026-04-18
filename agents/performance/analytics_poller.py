from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from googleapiclient.discovery import build
from supabase import Client, create_client

from agents.shared.config_loader import get_env
from agents.production.uploader import build_youtube_service

# Promotion thresholds (at 60-day review)
PROMOTE_MIN_VIEWS = 50
PROMOTE_MIN_CTR = 0.03
PROMOTE_MIN_WATCH_TIME = 0.35

# Archive: all three thresholds must be missed
ARCHIVE_MAX_VIEWS = 50
ARCHIVE_MAX_CTR = 0.03
ARCHIVE_MAX_WATCH_TIME = 0.35

# Early promotion flag
EARLY_VIEWS_THRESHOLD = 200
EARLY_CTR_THRESHOLD = 0.05


@dataclass
class NichePerformance:
    views_total: int
    ctr: float
    avg_watch_time_pct: float


def should_promote(perf: NichePerformance) -> bool:
    return (
        perf.views_total >= PROMOTE_MIN_VIEWS
        and perf.ctr >= PROMOTE_MIN_CTR
        and perf.avg_watch_time_pct >= PROMOTE_MIN_WATCH_TIME
    )


def should_archive(perf: NichePerformance) -> bool:
    return (
        perf.views_total < ARCHIVE_MAX_VIEWS
        and perf.ctr < ARCHIVE_MAX_CTR
        and perf.avg_watch_time_pct < ARCHIVE_MAX_WATCH_TIME
    )


def should_flag_early(perf: NichePerformance) -> bool:
    return perf.views_total >= EARLY_VIEWS_THRESHOLD and perf.ctr >= EARLY_CTR_THRESHOLD


class AnalyticsPoller:
    def __init__(self, supabase: Client):
        self._sb = supabase
        self._yt = build_youtube_service()
        self._analytics = build("youtubeAnalytics", "v2", credentials=self._yt._http.credentials)

    def poll_niche(self, niche_id: str, channel_id: str) -> Optional[NichePerformance]:
        try:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            result = self._analytics.reports().query(
                ids=f"channel=={channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,clickThroughRate",
                dimensions="day",
            ).execute()
            rows = result.get("rows", [])
            if not rows:
                return None
            total_views = sum(int(r[1]) for r in rows)
            avg_ctr = sum(float(r[4]) for r in rows) / len(rows) / 100
            avg_view_dur = sum(float(r[3]) for r in rows) / len(rows)
            watch_pct = min(avg_view_dur / 480, 1.0)
            return NichePerformance(
                views_total=total_views,
                ctr=avg_ctr,
                avg_watch_time_pct=watch_pct,
            )
        except Exception as e:
            print(f"[analytics] failed to poll niche {niche_id}: {e}")
            return None

    def run(self) -> None:
        testing_niches = (
            self._sb.table("niches")
            .select("*")
            .eq("status", "testing")
            .execute()
            .data
        )
        for niche in testing_niches:
            brand = niche.get("brand_package") or {}
            channel_id = brand.get("channel_id")
            if not channel_id:
                print(f"[analytics] niche {niche['name']} has no channel_id in brand_package, skip")
                continue

            perf = self.poll_niche(niche["id"], channel_id)
            if not perf:
                continue

            self._sb.table("niche_analytics").insert(
                {
                    "niche_id": niche["id"],
                    "views_total": perf.views_total,
                    "ctr": perf.ctr,
                    "avg_watch_time_pct": perf.avg_watch_time_pct,
                    "early_promotion_flagged": should_flag_early(perf),
                }
            ).execute()

            activated_at = niche.get("activated_at")
            if activated_at:
                activated = datetime.fromisoformat(activated_at.replace("Z", "+00:00"))
                days_active = (datetime.now(timezone.utc) - activated).days
                if days_active >= 60:
                    if should_promote(perf):
                        self._sb.table("niches").update({"status": "promoted"}).eq("id", niche["id"]).execute()
                        print(f"[analytics] PROMOTED: {niche['name']}")
                    elif should_archive(perf):
                        self._sb.table("niches").update({"status": "archived"}).eq("id", niche["id"]).execute()
                        print(f"[analytics] ARCHIVED: {niche['name']}")

            if should_flag_early(perf):
                print(f"[analytics] EARLY FLAG: {niche['name']} — {perf.views_total} views, CTR {perf.ctr:.1%}")


def main():
    sb = create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))
    poller = AnalyticsPoller(supabase=sb)
    poller.run()


if __name__ == "__main__":
    main()
