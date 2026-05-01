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

    def _build_analytics_service(self, token_dict: dict):
        yt = build_youtube_service(token_dict=token_dict)
        creds = yt._http.credentials
        print(f"[analytics] token scopes: {getattr(creds, 'scopes', 'unknown')}")
        try:
            resp = yt.channels().list(part="id", mine=True).execute()
            items = resp.get("items", [])
            resolved = items[0]["id"] if items else "none"
            print(f"[analytics] token resolves to channel: {resolved}")
        except Exception as e:
            print(f"[analytics] channel resolution check failed: {e}")
        return build("youtubeAnalytics", "v2", credentials=creds)

    def _fetch_published_videos(self, niche_id: str) -> tuple[list[str], int, int]:
        """Returns (video_ids, longs_count, shorts_count) for published videos."""
        rows = execute_with_retry(
            self._sb.table("published_videos")
            .select("youtube_video_id, video_type")
            .eq("niche_id", niche_id)
        ).data
        video_ids = [r["youtube_video_id"] for r in rows]
        longs = sum(1 for r in rows if r["video_type"] == "long")
        shorts = sum(1 for r in rows if r["video_type"] == "short")
        return video_ids, longs, shorts

    def poll_niche(self, niche_id: str, channel_id: str, analytics_service) -> Optional[NichePerformance]:
        video_ids, longs_published, shorts_published = self._fetch_published_videos(niche_id)
        if not video_ids:
            print(f"[analytics] niche {niche_id} has no published videos, skip")
            return None

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        result = analytics_service.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration",
            dimensions="day",
            filters=f"video=={','.join(video_ids)}",
        ).execute()
        rows = result.get("rows", [])
        if not rows:
            return NichePerformance(views_total=0, avg_watch_time_pct=0.0,
                                    videos_published=longs_published, shorts_published=shorts_published)
        total_views = sum(int(r[1]) for r in rows)
        avg_view_dur = sum(float(r[3]) for r in rows) / len(rows)
        watch_pct = min(avg_view_dur / 480, 1.0)
        return NichePerformance(
            views_total=total_views,
            avg_watch_time_pct=watch_pct,
            videos_published=longs_published,
            shorts_published=shorts_published,
        )

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches")
            .select("*, youtube_accounts(channel_id, token_json)")
            .in_("status", ["testing", "promoted"])
        ).data

        failures = []
        for niche in active_niches:
            account = niche.get("youtube_accounts") or {}
            channel_id = account.get("channel_id")
            token_json = account.get("token_json")
            if not channel_id or not token_json:
                print(f"[analytics] niche {niche['name']} has no linked YouTube channel or token, skip")
                continue

            try:
                print(f"[analytics] polling: {niche['name']} ({niche['status']})")
                analytics = self._build_analytics_service(token_json)
                perf = self.poll_niche(niche["id"], channel_id, analytics)
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
                    activated = datetime.fromisoformat(activated_at[:19] + "+00:00")
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

            except Exception as e:
                print(f"[analytics] failed to poll niche {niche['id']}: {e}")
                failures.append(niche["id"])

        if failures:
            raise RuntimeError(f"[analytics] polling failed for {len(failures)} niche(s): {failures}")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    poller = AnalyticsPoller(supabase=sb)
    poller.run()


if __name__ == "__main__":
    main()
