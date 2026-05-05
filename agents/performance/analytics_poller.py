from dataclasses import dataclass, field
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
    avg_watch_time_pct: float        # true weighted avg from YouTube's averageViewPercentage (0–1)
    avg_view_duration_sec: float     # weighted avg seconds watched
    impressions: int
    long_views: int
    long_avg_view_duration_sec: float
    long_avg_watch_pct: float
    short_views: int
    short_avg_view_duration_sec: float
    short_avg_watch_pct: float
    subscribers_gained: int
    estimated_minutes_watched: int
    likes: int
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


def _weighted_avg(values_and_weights: list[tuple[float, int]]) -> float:
    """Return the weighted average of (value, weight) pairs. Returns 0 if total weight is 0."""
    total_weight = sum(w for _, w in values_and_weights)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in values_and_weights) / total_weight


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

    def _fetch_published_videos(self, niche_id: str) -> list[dict]:
        """Returns full published_video rows for a niche."""
        return execute_with_retry(
            self._sb.table("published_videos")
            .select("youtube_video_id, video_type")
            .eq("niche_id", niche_id)
        ).data

    def _query_video_metrics(
        self,
        analytics_service,
        video_ids: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, dict]:
        """Per-video metrics keyed by youtube_video_id.

        Uses dimensions=video so we get one row per video — avoids the
        average-of-daily-averages bias of the old day-dimension approach.
        averageViewPercentage is YouTube's own %, so no hardcoded denominator needed.
        """
        if not video_ids:
            return {}
        result = analytics_service.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes",
            dimensions="video",
            filters=f"video=={','.join(video_ids)}",
        ).execute()
        out: dict[str, dict] = {}
        for row in result.get("rows", []):
            out[row[0]] = {
                "views": int(row[1]),
                "estimated_minutes_watched": float(row[2]),
                "avg_view_duration_sec": float(row[3]),
                "avg_view_pct": float(row[4]) / 100.0,  # YouTube returns 0–100
                "likes": int(row[5]),
            }
        return out

    def _query_channel_metrics(
        self,
        analytics_service,
        start_date: str,
        end_date: str,
    ) -> tuple[int, int]:
        """Channel-level impressions and subscribers gained.

        impressions/impressionClickThroughRate are only available without a
        video filter, so this is channel-wide. Acceptable given most niches
        have their own channel.
        Returns (impressions, subscribers_gained).
        """
        try:
            result = analytics_service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="impressions,subscribersGained",
            ).execute()
            rows = result.get("rows", [])
            if rows:
                return int(rows[0][0]), int(rows[0][1])
        except Exception as e:
            print(f"[analytics] channel-level metrics query failed (non-fatal): {e}")
        return 0, 0

    def _aggregate(self, video_metrics: dict[str, dict]) -> tuple[int, float, float, float, int]:
        """Aggregate metrics across a set of videos.

        Returns (views, avg_watch_pct, avg_duration_sec, estimated_minutes, likes).
        """
        if not video_metrics:
            return 0, 0.0, 0.0, 0.0, 0
        total_views = sum(m["views"] for m in video_metrics.values())
        total_minutes = sum(m["estimated_minutes_watched"] for m in video_metrics.values())
        total_likes = sum(m["likes"] for m in video_metrics.values())
        avg_pct = _weighted_avg([(m["avg_view_pct"], m["views"]) for m in video_metrics.values()])
        avg_dur = (total_minutes * 60 / total_views) if total_views > 0 else 0.0
        return total_views, avg_pct, avg_dur, total_minutes, total_likes

    def poll_niche(
        self, niche_id: str, channel_id: str, analytics_service
    ) -> Optional[NichePerformance]:
        rows = self._fetch_published_videos(niche_id)
        if not rows:
            print(f"[analytics] niche {niche_id} has no published videos, skip")
            return None

        all_ids = [r["youtube_video_id"] for r in rows]
        long_ids = {r["youtube_video_id"] for r in rows if r["video_type"] == "long"}
        short_ids = {r["youtube_video_id"] for r in rows if r["video_type"] == "short"}
        longs_count = len(long_ids)
        shorts_count = len(short_ids)

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        video_metrics = self._query_video_metrics(analytics_service, all_ids, start_date, end_date)
        impressions, subs_gained = self._query_channel_metrics(analytics_service, start_date, end_date)

        total_views, avg_pct, avg_dur, total_minutes, total_likes = self._aggregate(video_metrics)

        long_m = {vid: m for vid, m in video_metrics.items() if vid in long_ids}
        long_views, long_avg_pct, long_avg_dur, _, _ = self._aggregate(long_m)

        short_m = {vid: m for vid, m in video_metrics.items() if vid in short_ids}
        short_views, short_avg_pct, short_avg_dur, _, _ = self._aggregate(short_m)

        return NichePerformance(
            views_total=total_views,
            avg_watch_time_pct=avg_pct,
            avg_view_duration_sec=avg_dur,
            impressions=impressions,
            long_views=long_views,
            long_avg_view_duration_sec=long_avg_dur,
            long_avg_watch_pct=long_avg_pct,
            short_views=short_views,
            short_avg_view_duration_sec=short_avg_dur,
            short_avg_watch_pct=short_avg_pct,
            subscribers_gained=subs_gained,
            estimated_minutes_watched=int(total_minutes),
            likes=total_likes,
            videos_published=longs_count,
            shorts_published=shorts_count,
        )

    def poll_videos(
        self,
        niche_id: str,
        analytics_service,
        published_rows: list[dict],
        start_date: str,
        end_date: str,
    ) -> None:
        """Insert one video_analytics row per published video per poll."""
        all_ids = [r["youtube_video_id"] for r in published_rows]
        if not all_ids:
            return
        type_map = {r["youtube_video_id"]: r["video_type"] for r in published_rows}
        video_metrics = self._query_video_metrics(analytics_service, all_ids, start_date, end_date)
        rows_to_insert = [
            {
                "niche_id": niche_id,
                "youtube_video_id": vid_id,
                "video_type": type_map.get(vid_id, "long"),
                "views": m["views"],
                "avg_view_duration_sec": m["avg_view_duration_sec"],
                "avg_view_pct": m["avg_view_pct"],
                "estimated_minutes_watched": m["estimated_minutes_watched"],
                "likes": m["likes"],
            }
            for vid_id, m in video_metrics.items()
        ]
        if rows_to_insert:
            execute_with_retry(self._sb.table("video_analytics").insert(rows_to_insert))
            print(f"[analytics] stored {len(rows_to_insert)} video_analytics rows for niche {niche_id}")

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

                end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

                perf = self.poll_niche(niche["id"], channel_id, analytics)
                if not perf:
                    continue

                execute_with_retry(self._sb.table("niche_analytics").insert({
                    "niche_id": niche["id"],
                    "views_total": perf.views_total,
                    "avg_watch_time_pct": perf.avg_watch_time_pct,
                    "avg_view_duration_sec": perf.avg_view_duration_sec,
                    "ctr": 0.0,  # impressionClickThroughRate requires content-owner scope; kept for schema compat
                    "impressions": perf.impressions,
                    "long_views": perf.long_views,
                    "long_avg_view_duration_sec": perf.long_avg_view_duration_sec,
                    "long_avg_watch_pct": perf.long_avg_watch_pct,
                    "short_views": perf.short_views,
                    "short_avg_view_duration_sec": perf.short_avg_view_duration_sec,
                    "short_avg_watch_pct": perf.short_avg_watch_pct,
                    "subscribers_gained": perf.subscribers_gained,
                    "estimated_minutes_watched": perf.estimated_minutes_watched,
                    "likes": perf.likes,
                    "subs_total": 0,  # subs_total requires separate Data API call; not critical
                    "early_promotion_flagged": should_flag_early(perf),
                    "videos_published": perf.videos_published,
                    "shorts_published": perf.shorts_published,
                }))

                published_rows = self._fetch_published_videos(niche["id"])
                self.poll_videos(niche["id"], analytics, published_rows, start_date, end_date)

                activated_at = niche.get("activated_at")
                if activated_at:
                    activated = datetime.fromisoformat(activated_at[:19] + "+00:00")
                    days_active = (datetime.now(timezone.utc) - activated).days
                    if days_active >= 60:
                        if should_promote(perf):
                            execute_with_retry(
                                self._sb.table("niches").update({"status": "promoted"}).eq("id", niche["id"])
                            )
                            print(f"[analytics] PROMOTED: {niche['name']}")
                        elif should_archive(perf):
                            execute_with_retry(
                                self._sb.table("niches").update({"status": "archived"}).eq("id", niche["id"])
                            )
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
