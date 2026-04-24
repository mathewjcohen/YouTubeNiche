from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from googleapiclient.discovery import build
from supabase import Client, create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.production.uploader import build_youtube_service

# Promotion thresholds (at 60-day review)
PROMOTE_MIN_VIEWS = 50
PROMOTE_MIN_WATCH_TIME = 0.35

# Archive: both thresholds must be missed
ARCHIVE_MAX_VIEWS = 50
ARCHIVE_MAX_WATCH_TIME = 0.35

# Early promotion flag
EARLY_VIEWS_THRESHOLD = 200


@dataclass
class NichePerformance:
    views_total: int
    avg_watch_time_pct: float
    videos_published: int = 0
    shorts_published: int = 0


def should_promote(perf: NichePerformance) -> bool:
    return (
        perf.views_total >= PROMOTE_MIN_VIEWS
        and perf.avg_watch_time_pct >= PROMOTE_MIN_WATCH_TIME
    )


def should_archive(perf: NichePerformance) -> bool:
    return (
        perf.views_total < ARCHIVE_MAX_VIEWS
        and perf.avg_watch_time_pct < ARCHIVE_MAX_WATCH_TIME
    )


def should_flag_early(perf: NichePerformance) -> bool:
    return perf.views_total >= EARLY_VIEWS_THRESHOLD


class AnalyticsPoller:
    def __init__(self, supabase: Client):
        self._sb = supabase
        self._yt = build_youtube_service()
        self._analytics = build("youtubeAnalytics", "v2", credentials=self._yt._http.credentials)

    def _fetch_video_counts(self, niche_id: str, channel_id: str) -> tuple[int, int]:
        """Returns (total_from_youtube, shorts_from_db). Longs = total - shorts."""
        total = 0
        try:
            result = self._yt.channels().list(part="statistics", id=channel_id).execute()
            items = result.get("items", [])
            if items:
                total = int(items[0].get("statistics", {}).get("videoCount", 0))
        except Exception as e:
            print(f"[analytics] channels.list failed for {niche_id}: {e}")

        shorts = 0
        try:
            resp = execute_with_retry(
                self._sb.table("videos")
                .select("id", count="exact")
                .eq("niche_id", niche_id)
                .eq("video_type", "short")
                .not_.is_("youtube_video_id", "null")
            )
            shorts = resp.count or 0
        except Exception as e:
            print(f"[analytics] shorts count query failed for {niche_id}: {e}")

        return total, shorts

    def poll_niche(self, niche_id: str, channel_id: str) -> Optional[NichePerformance]:
        try:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            result = self._analytics.reports().query(
                ids=f"channel=={channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration",
                dimensions="day",
            ).execute()
            rows = result.get("rows", [])
            if not rows or len(rows[0]) < 4:
                return None
            total_views = sum(int(r[1]) for r in rows)
            avg_view_dur = sum(float(r[3]) for r in rows) / len(rows)
            watch_pct = min(avg_view_dur / 480, 1.0)
            total_published, shorts_published = self._fetch_video_counts(niche_id, channel_id)
            return NichePerformance(
                views_total=total_views,
                avg_watch_time_pct=watch_pct,
                videos_published=max(0, total_published - shorts_published),
                shorts_published=shorts_published,
            )
        except Exception as e:
            print(f"[analytics] failed to poll niche {niche_id}: {e}")
            return None

    def run(self) -> None:
        testing_niches = execute_with_retry(
            self._sb.table("niches")
            .select("*, youtube_accounts(channel_id)")
            .eq("status", "testing")
        ).data
        for niche in testing_niches:
            account = niche.get("youtube_accounts") or {}
            channel_id = account.get("channel_id")
            if not channel_id:
                print(f"[analytics] niche {niche['name']} has no linked YouTube channel, skip")
                continue

            perf = self.poll_niche(niche["id"], channel_id)
            if not perf:
                continue

            execute_with_retry(self._sb.table("niche_analytics").insert(
                {
                    "niche_id": niche["id"],
                    "views_total": perf.views_total,
                    "avg_watch_time_pct": perf.avg_watch_time_pct,
                    "early_promotion_flagged": should_flag_early(perf),
                    "videos_published": perf.videos_published,
                    "shorts_published": perf.shorts_published,
                }
            ))

            activated_at = niche.get("activated_at")
            if activated_at:
                activated = datetime.fromisoformat(activated_at.replace("Z", "+00:00"))
                days_active = (datetime.now(timezone.utc) - activated).days
                if days_active >= 60:
                    if should_promote(perf):
                        execute_with_retry(self._sb.table("niches").update({"status": "promoted"}).eq("id", niche["id"]))
                        print(f"[analytics] PROMOTED: {niche['name']}")
                    elif should_archive(perf):
                        execute_with_retry(self._sb.table("niches").update({"status": "archived"}).eq("id", niche["id"]))
                        print(f"[analytics] ARCHIVED: {niche['name']}")

            if should_flag_early(perf):
                print(f"[analytics] EARLY FLAG: {niche['name']} — {perf.views_total} views")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    poller = AnalyticsPoller(supabase=sb)
    poller.run()


if __name__ == "__main__":
    main()
