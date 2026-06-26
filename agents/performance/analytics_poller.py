import re
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

# Audience retention: cap per-video retention fetches to avoid quota exhaustion
MAX_RETENTION_FETCHES_PER_NICHE = 10

# YouTube Analytics API rejects filter strings with too many video IDs; batch to stay safe
ANALYTICS_VIDEO_BATCH_SIZE = 200


@dataclass
class NichePerformance:
    views_total: int
    avg_watch_time_pct: float        # true weighted avg from YouTube's averageViewPercentage (0–1)
    avg_view_duration_sec: float = 0.0
    impressions: int = 0
    long_views: int = 0
    long_avg_view_duration_sec: float = 0.0
    long_avg_watch_pct: float = 0.0
    short_views: int = 0
    short_avg_view_duration_sec: float = 0.0
    short_avg_watch_pct: float = 0.0
    subscribers_gained: int = 0
    estimated_minutes_watched: int = 0
    likes: int = 0
    videos_published: int = 0
    shorts_published: int = 0
    traffic_sources: dict = field(default_factory=dict)
    top_countries: dict = field(default_factory=dict)
    device_types: dict = field(default_factory=dict)
    subscriber_ratio: float = 0.0


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


def _parse_iso_duration(duration: str) -> int:
    """Parse ISO 8601 duration string (e.g. PT5M30S) to seconds."""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration or "")
    if not match:
        return 0
    h, m, s = [int(x or 0) for x in match.groups()]
    return h * 3600 + m * 60 + s


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
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        return yt, analytics

    def _fetch_published_videos(self, niche_id: str) -> list[dict]:
        """Returns full published_video rows for a niche."""
        return execute_with_retry(
            self._sb.table("published_videos")
            .select("youtube_video_id, video_type, title, duration_sec, status, created_at, script_id")
            .eq("niche_id", niche_id)
            .neq("youtube_video_id", "")
            .not_.is_("youtube_video_id", "null")
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
        video_ids = [v.strip() for v in video_ids if v and v.strip()]
        if not video_ids:
            return {}
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), ANALYTICS_VIDEO_BATCH_SIZE):
            batch = video_ids[i:i + ANALYTICS_VIDEO_BATCH_SIZE]
            result = analytics_service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes",
                dimensions="video",
                filters=f"video=={','.join(batch)}",
            ).execute()
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
        """Channel-level subscribers gained. Returns (impressions=0, subscribers_gained).

        impressions requires content-owner credentials; not available with yt-analytics scope.
        """
        try:
            result = analytics_service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="subscribersGained",
            ).execute()
            rows = result.get("rows", [])
            if rows:
                return 0, int(rows[0][0])
        except Exception as e:
            print(f"[analytics] channel-level metrics query failed (non-fatal): {e}")
        return 0, 0

    def _query_traffic_sources(
        self,
        analytics_service,
        video_ids: list[str],
        start_date: str,
        end_date: str,
    ) -> dict:
        """Fraction of views by traffic source type."""
        video_ids = [v.strip() for v in video_ids if v and v.strip()]
        if not video_ids:
            return {}
        raw: dict[str, int] = {}
        try:
            for i in range(0, len(video_ids), ANALYTICS_VIDEO_BATCH_SIZE):
                batch = video_ids[i:i + ANALYTICS_VIDEO_BATCH_SIZE]
                result = analytics_service.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views",
                    dimensions="insightTrafficSourceType",
                    filters=f"video=={','.join(batch)}",
                ).execute()
                for row in result.get("rows", []):
                    raw[row[0]] = raw.get(row[0], 0) + int(row[1])
        except Exception as e:
            print(f"[analytics] traffic source query failed (non-fatal): {e}")
            return {}
        total = sum(raw.values())
        if not total:
            return {}
        return {k: round(v / total, 3) for k, v in raw.items()}

    def _query_top_countries(
        self,
        analytics_service,
        video_ids: list[str],
        start_date: str,
        end_date: str,
        top_n: int = 5,
    ) -> dict:
        """Fraction of views by country, top N."""
        video_ids = [v.strip() for v in video_ids if v and v.strip()]
        if not video_ids:
            return {}
        raw: dict[str, int] = {}
        try:
            for i in range(0, len(video_ids), ANALYTICS_VIDEO_BATCH_SIZE):
                batch = video_ids[i:i + ANALYTICS_VIDEO_BATCH_SIZE]
                result = analytics_service.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views",
                    dimensions="country",
                    filters=f"video=={','.join(batch)}",
                ).execute()
                for row in result.get("rows", []):
                    raw[row[0]] = raw.get(row[0], 0) + int(row[1])
        except Exception as e:
            print(f"[analytics] country query failed (non-fatal): {e}")
            return {}
        total = sum(raw.values())
        if not total:
            return {}
        top = sorted(raw.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return {k: round(v / total, 3) for k, v in top}

    def _query_device_types(
        self,
        analytics_service,
        video_ids: list[str],
        start_date: str,
        end_date: str,
    ) -> dict:
        """Fraction of views by device type."""
        video_ids = [v.strip() for v in video_ids if v and v.strip()]
        if not video_ids:
            return {}
        raw: dict[str, int] = {}
        try:
            for i in range(0, len(video_ids), ANALYTICS_VIDEO_BATCH_SIZE):
                batch = video_ids[i:i + ANALYTICS_VIDEO_BATCH_SIZE]
                result = analytics_service.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views",
                    dimensions="deviceType",
                    filters=f"video=={','.join(batch)}",
                ).execute()
                for row in result.get("rows", []):
                    raw[row[0]] = raw.get(row[0], 0) + int(row[1])
        except Exception as e:
            print(f"[analytics] device type query failed (non-fatal): {e}")
            return {}
        total = sum(raw.values())
        if not total:
            return {}
        return {k: round(v / total, 3) for k, v in raw.items()}

    def _query_subscriber_ratio(
        self,
        analytics_service,
        video_ids: list[str],
        start_date: str,
        end_date: str,
    ) -> float:
        """Fraction of views from subscribed users (channel-level; video filter not supported by YT Analytics for subscribedStatus)."""
        if not video_ids:
            return 0.0
        total_views = 0
        sub_views = 0
        try:
            result = analytics_service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views",
                dimensions="subscribedStatus",
            ).execute()
            for row in result.get("rows", []):
                total_views += int(row[1])
                if row[0] == "SUBSCRIBED":
                    sub_views += int(row[1])
        except Exception as e:
            print(f"[analytics] subscriber ratio query failed (non-fatal): {e}")
            return 0.0
        if not total_views:
            return 0.0
        return round(sub_views / total_views, 3)

    def _query_audience_retention(
        self,
        analytics_service,
        video_id: str,
        start_date: str,
        end_date: str,
    ) -> Optional[dict]:
        """Retention curve for a single video.

        Returns {elapsed_ratio_str: watch_ratio} or None on failure.
        elapsedVideoTimeRatio is returned as a string key so it round-trips
        cleanly through JSON/JSONB without float precision surprises.
        """
        try:
            result = analytics_service.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="audienceWatchRatio",
                dimensions="elapsedVideoTimeRatio",
                filters=f"video=={video_id}",
            ).execute()
            rows = result.get("rows", [])
            if not rows:
                return None
            return {f"{float(r[0]):.2f}": round(float(r[1]), 4) for r in rows}
        except Exception as e:
            print(f"[analytics] retention query failed for {video_id} (non-fatal): {e}")
            return None

    def _fetch_video_metadata(
        self,
        yt_service,
        video_ids: list[str],
    ) -> dict[str, dict]:
        """Fetch title and duration from YouTube Data API. Chunks to 50 IDs per request."""
        if not video_ids:
            return {}
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            try:
                result = yt_service.videos().list(
                    part="contentDetails,snippet",
                    id=",".join(batch),
                ).execute()
                for item in result.get("items", []):
                    out[item["id"]] = {
                        "title": item["snippet"]["title"],
                        "duration_sec": _parse_iso_duration(item["contentDetails"]["duration"]),
                    }
            except Exception as e:
                print(f"[analytics] video metadata fetch failed (non-fatal): {e}")
        return out

    def _backfill_published_video_metadata(
        self,
        yt_service,
        niche_id: str,
        published_rows: list[dict],
    ) -> None:
        """Fill title/duration_sec for published_videos rows that are missing them."""
        missing = [r["youtube_video_id"] for r in published_rows if not r.get("title") or not r.get("duration_sec")]
        if not missing:
            return
        metadata = self._fetch_video_metadata(yt_service, missing)
        for vid_id, meta in metadata.items():
            execute_with_retry(
                self._sb.table("published_videos")
                .update({"title": meta["title"], "duration_sec": meta["duration_sec"]})
                .eq("youtube_video_id", vid_id)
                .eq("niche_id", niche_id)
            )
        print(f"[analytics] backfilled metadata for {len(metadata)} video(s) in niche {niche_id}")

    def _sync_published_videos(
        self,
        yt_service,
        niche_id: str,
        published_rows: list[dict],
    ) -> None:
        """Sync published_videos.status against YouTube — marks removed/private/live."""
        all_ids = [r["youtube_video_id"] for r in published_rows]
        if not all_ids:
            return

        returned: dict[str, str] = {}
        for i in range(0, len(all_ids), 50):
            batch = all_ids[i:i + 50]
            try:
                result = yt_service.videos().list(
                    part="status",
                    id=",".join(batch),
                ).execute()
                for item in result.get("items", []):
                    privacy = item.get("status", {}).get("privacyStatus", "public")
                    returned[item["id"]] = privacy
            except Exception as e:
                print(f"[analytics] sync check failed for niche {niche_id} (non-fatal): {e}")
                return

        now = datetime.now(timezone.utc).isoformat()
        changed = 0
        for row in published_rows:
            vid_id = row["youtube_video_id"]
            current = row.get("status", "live")
            if vid_id not in returned:
                if current != "removed":
                    execute_with_retry(
                        self._sb.table("published_videos")
                        .update({"status": "removed", "removed_at": now})
                        .eq("youtube_video_id", vid_id)
                        .eq("niche_id", niche_id)
                    )
                    print(f"[analytics] marked removed: {vid_id}")
                    changed += 1
            else:
                new_status = "private" if returned[vid_id] in ("private", "unlisted") else "live"
                if current != new_status:
                    update: dict = {"status": new_status}
                    if new_status == "live":
                        update["removed_at"] = None
                    execute_with_retry(
                        self._sb.table("published_videos")
                        .update(update)
                        .eq("youtube_video_id", vid_id)
                        .eq("niche_id", niche_id)
                    )
                    print(f"[analytics] status {current} -> {new_status}: {vid_id}")
                    changed += 1

        if changed:
            print(f"[analytics] synced {changed} status change(s) for niche {niche_id}")

    def _recover_pipeline_videos(
        self,
        niche_id: str,
        known_ids: set[str],
    ) -> int:
        """Insert published_videos rows for pipeline uploads missing from the table.

        Looks for rows in the `videos` table that have youtube_video_id set
        (uploaded successfully) but have no matching published_videos row.
        These get the correct niche_id and script_id from the source row.
        """
        video_rows = execute_with_retry(
            self._sb.table("videos")
            .select("script_id, niche_id, video_type, youtube_video_id")
            .eq("niche_id", niche_id)
            .not_.is_("youtube_video_id", "null")
        ).data

        missing = [v for v in video_rows if v["youtube_video_id"] not in known_ids]
        if not missing:
            return 0

        rows = [
            {
                "niche_id": v["niche_id"],
                "script_id": v["script_id"],
                "youtube_video_id": v["youtube_video_id"],
                "video_type": v["video_type"],
                "status": "live",
            }
            for v in missing
        ]
        execute_with_retry(self._sb.table("published_videos").insert(rows))
        for v in missing:
            print(f"[analytics] recovered pipeline video: {v['youtube_video_id']} ({v['video_type']})")
        return len(rows)

    def _flag_and_analyze_zombies(
        self,
        niche_id: str,
        niche_name: str,
        published_rows: list[dict],
    ) -> None:
        """Mark videos >30 days old with zero lifetime views as 'zombie' and log a comparison."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        # Sum lifetime views per video from the video_analytics table
        va_rows = execute_with_retry(
            self._sb.table("video_analytics")
            .select("youtube_video_id, views")
            .eq("niche_id", niche_id)
        ).data
        lifetime_views: dict[str, int] = {}
        for row in va_rows:
            vid = row["youtube_video_id"]
            lifetime_views[vid] = lifetime_views.get(vid, 0) + (row["views"] or 0)

        live_rows = [r for r in published_rows if r.get("status") == "live"]
        new_zombie_ids: set[str] = set()
        for row in live_rows:
            raw_ts = row.get("created_at")
            if not raw_ts:
                continue
            try:
                created = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created > cutoff:
                continue
            if lifetime_views.get(row["youtube_video_id"], 0) == 0:
                new_zombie_ids.add(row["youtube_video_id"])

        for vid_id in new_zombie_ids:
            execute_with_retry(
                self._sb.table("published_videos")
                .update({"status": "zombie"})
                .eq("youtube_video_id", vid_id)
                .eq("niche_id", niche_id)
            )
        if new_zombie_ids:
            print(f"[analytics] flagged {len(new_zombie_ids)} new zombie(s) in niche '{niche_name}'")

        # Comparison: all zombies (new + pre-existing) vs performers
        all_zombie_ids = new_zombie_ids | {r["youtube_video_id"] for r in published_rows if r.get("status") == "zombie"}
        zombies = [r for r in published_rows if r["youtube_video_id"] in all_zombie_ids]
        performers = [r for r in live_rows if lifetime_views.get(r["youtube_video_id"], 0) > 0]

        if not zombies or not performers:
            return

        def _avg(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.0

        z_dur = _avg([r.get("duration_sec") or 0 for r in zombies])
        p_dur = _avg([r.get("duration_sec") or 0 for r in performers])
        z_title = _avg([len(r.get("title") or "") for r in zombies])
        p_title = _avg([len(r.get("title") or "") for r in performers])
        z_shorts_pct = sum(1 for r in zombies if r.get("video_type") == "short") / len(zombies) * 100
        p_shorts_pct = sum(1 for r in performers if r.get("video_type") == "short") / len(performers) * 100

        print(
            f"[analytics] zombie vs performer — '{niche_name}' "
            f"({len(zombies)} zombies / {len(performers)} performers):"
        )
        print(f"  duration:  zombies {z_dur:.0f}s  |  performers {p_dur:.0f}s")
        print(f"  title len: zombies {z_title:.0f}c  |  performers {p_title:.0f}c")
        print(f"  % shorts:  zombies {z_shorts_pct:.0f}%  |  performers {p_shorts_pct:.0f}%")

        # Script word count from long_form_text / short_text
        all_script_ids = list({r["script_id"] for r in zombies + performers if r.get("script_id")})
        if not all_script_ids:
            return
        try:
            script_rows = execute_with_retry(
                self._sb.table("scripts")
                .select("id, long_form_text, short_text")
                .in_("id", all_script_ids)
            ).data
        except Exception:
            return
        wc_map = {
            s["id"]: len((s.get("long_form_text") or s.get("short_text") or "").split())
            for s in script_rows
        }
        z_wc = _avg([wc_map.get(r["script_id"], 0) for r in zombies if r.get("script_id")])
        p_wc = _avg([wc_map.get(r["script_id"], 0) for r in performers if r.get("script_id")])
        print(f"  word count: zombies {z_wc:.0f}w  |  performers {p_wc:.0f}w")

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
        self, niche_id: str, channel_id: str, analytics_service, yt_service, all_ids: list[str]
    ) -> Optional[NichePerformance]:
        rows = self._fetch_published_videos(niche_id)
        if not rows:
            print(f"[analytics] niche {niche_id} has no published videos, skip")
            return None

        all_ids_list = [r["youtube_video_id"] for r in rows]
        long_ids = {r["youtube_video_id"] for r in rows if r["video_type"] == "long"}
        short_ids = {r["youtube_video_id"] for r in rows if r["video_type"] == "short"}
        longs_count = len(long_ids)
        shorts_count = len(short_ids)

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        video_metrics = self._query_video_metrics(analytics_service, all_ids_list, start_date, end_date)
        impressions, subs_gained = self._query_channel_metrics(analytics_service, start_date, end_date)

        traffic_sources = self._query_traffic_sources(analytics_service, all_ids_list, start_date, end_date)
        top_countries = self._query_top_countries(analytics_service, all_ids_list, start_date, end_date)
        device_types = self._query_device_types(analytics_service, all_ids_list, start_date, end_date)
        subscriber_ratio = self._query_subscriber_ratio(analytics_service, all_ids_list, start_date, end_date)

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
            traffic_sources=traffic_sources,
            top_countries=top_countries,
            device_types=device_types,
            subscriber_ratio=subscriber_ratio,
        )

    def poll_videos(
        self,
        niche_id: str,
        analytics_service,
        published_rows: list[dict],
        start_date: str,
        end_date: str,
    ) -> None:
        """Insert one video_analytics row per published video per poll, including retention curves."""
        all_ids = [r["youtube_video_id"] for r in published_rows]
        if not all_ids:
            return
        type_map = {r["youtube_video_id"]: r["video_type"] for r in published_rows}
        video_metrics = self._query_video_metrics(analytics_service, all_ids, start_date, end_date)

        # Fetch retention for all published videos using a lifetime window so videos
        # that got their views outside the 7-day metrics window still get curves.
        # YouTube requires ~50+ views before audienceWatchRatio returns data.
        retention_map: dict[str, Optional[dict]] = {}
        for vid_id in all_ids[:MAX_RETENTION_FETCHES_PER_NICHE]:
            curve = self._query_audience_retention(
                analytics_service, vid_id, "2020-01-01", end_date
            )
            retention_map[vid_id] = curve
            if curve is None:
                print(f"[analytics] no retention data for {vid_id} (insufficient views or too new)")

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
                "audience_retention_json": retention_map.get(vid_id),
            }
            for vid_id, m in video_metrics.items()
        ]
        if rows_to_insert:
            execute_with_retry(self._sb.table("video_analytics").insert(rows_to_insert))
            retention_count = sum(1 for r in rows_to_insert if r["audience_retention_json"])
            print(
                f"[analytics] stored {len(rows_to_insert)} video_analytics rows "
                f"({retention_count} with retention) for niche {niche_id}"
            )

    def _discover_channel_orphans(
        self,
        yt_service,
        channel_id: str,
        niche_infos: list[dict],
        all_known_ids: set[str],
    ) -> int:
        """Find videos on a YouTube channel not tracked in published_videos.

        For single-niche channels all orphans are assigned to that niche.
        For multi-niche channels each orphan is matched to the niche whose script
        title has the highest word-overlap with the YouTube video title; skipped
        when no confident match is found (avoids cross-niche contamination).
        """
        try:
            ch_resp = yt_service.channels().list(part="contentDetails", id=channel_id).execute()
        except Exception as e:
            print(f"[analytics] channel lookup failed for {channel_id} (non-fatal): {e}")
            return 0

        ch_items = ch_resp.get("items", [])
        if not ch_items:
            return 0
        uploads_playlist_id = ch_items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        orphaned_ids: list[str] = []
        page_token: Optional[str] = None
        while True:
            try:
                resp = yt_service.playlistItems().list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                ).execute()
            except Exception as e:
                print(f"[analytics] uploads playlist fetch failed for {channel_id} (non-fatal): {e}")
                break
            for item in resp.get("items", []):
                vid_id = item["contentDetails"]["videoId"]
                if vid_id not in all_known_ids:
                    orphaned_ids.append(vid_id)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        if not orphaned_ids:
            return 0

        metadata = self._fetch_video_metadata(yt_service, orphaned_ids)
        if not metadata:
            return 0

        rows: list[dict] = []
        is_single_niche = len(niche_infos) == 1

        if is_single_niche:
            niche_id = niche_infos[0]["id"]
            for vid_id, meta in metadata.items():
                dur = meta.get("duration_sec") or 0
                rows.append({
                    "niche_id": niche_id,
                    "youtube_video_id": vid_id,
                    "video_type": "short" if 0 < dur <= 60 else "long",
                    "title": meta.get("title"),
                    "duration_sec": meta.get("duration_sec"),
                    "status": "live",
                })
        else:
            niche_ids = [n["id"] for n in niche_infos]
            script_rows = execute_with_retry(
                self._sb.table("scripts").select("id, niche_id, youtube_title").in_("niche_id", niche_ids)
            ).data
            niche_name_map = {n["id"]: n["name"] for n in niche_infos}
            for vid_id, meta in metadata.items():
                vid_words = set((meta.get("title") or "").lower().split())
                best_script = None
                best_score = 0.0
                for s in script_rows:
                    s_words = set((s.get("youtube_title") or "").lower().split())
                    if not vid_words or not s_words:
                        continue
                    score = len(vid_words & s_words) / max(len(vid_words), len(s_words))
                    if score > best_score:
                        best_score = score
                        best_script = s
                if best_script and best_score >= 0.5:
                    dur = meta.get("duration_sec") or 0
                    rows.append({
                        "niche_id": best_script["niche_id"],
                        "script_id": best_script["id"],
                        "youtube_video_id": vid_id,
                        "video_type": "short" if 0 < dur <= 60 else "long",
                        "title": meta.get("title"),
                        "duration_sec": meta.get("duration_sec"),
                        "status": "live",
                    })
                    niche_name = niche_name_map.get(best_script["niche_id"], "?")
                    print(f"[analytics] attributed orphan {vid_id} → niche '{niche_name}' (score={best_score:.2f})")
                else:
                    title_preview = (meta.get("title") or "")[:50]
                    print(f"[analytics] cannot attribute orphan {vid_id} '{title_preview}' (score={best_score:.2f}), skipping")

        if rows:
            execute_with_retry(self._sb.table("published_videos").insert(rows))
        return len(rows)

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches")
            .select("id, name, status, activated_at, youtube_accounts(channel_id, token_json)")
            .in_("status", ["testing", "promoted"])
        ).data

        failures = []
        # Collect per-channel info so we can run orphan discovery once per channel after the niche loop
        channel_info: dict[str, dict] = {}  # channel_id → {yt_service, niche_infos: [{id, name}]}

        for niche in active_niches:
            account = niche.get("youtube_accounts") or {}
            channel_id = account.get("channel_id")
            token_json = account.get("token_json")
            if not channel_id or not token_json:
                print(f"[analytics] niche {niche['name']} has no linked YouTube channel or token, skip")
                continue

            try:
                print(f"[analytics] polling: {niche['name']} ({niche['status']})")
                yt_service, analytics = self._build_analytics_service(token_json)
                if channel_id not in channel_info:
                    channel_info[channel_id] = {"yt_service": yt_service, "niche_infos": []}
                channel_info[channel_id]["niche_infos"].append({"id": niche["id"], "name": niche["name"]})

                end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

                published_rows = self._fetch_published_videos(niche["id"])

                # Backfill title + duration for any new uploads
                self._backfill_published_video_metadata(yt_service, niche["id"], published_rows)
                # Sync live/removed/private status against YouTube
                self._sync_published_videos(yt_service, niche["id"], published_rows)
                # Discover videos on the channel not yet in published_videos
                known_ids = {r["youtube_video_id"] for r in published_rows}
                found = self._recover_pipeline_videos(niche["id"], known_ids)
                if found:
                    print(f"[analytics] recovered {found} missing pipeline video(s) for niche {niche['name']}")
                # Re-fetch so poll_niche sees full up-to-date set
                published_rows = self._fetch_published_videos(niche["id"])
                # Backfill metadata for any rows that recovery just inserted
                if found:
                    self._backfill_published_video_metadata(yt_service, niche["id"], published_rows)

                perf = self.poll_niche(niche["id"], channel_id, analytics, yt_service, [])
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
                    "subs_total": 0,  # requires separate Data API call; not critical
                    "early_promotion_flagged": should_flag_early(perf),
                    "videos_published": perf.videos_published,
                    "shorts_published": perf.shorts_published,
                    "traffic_sources": perf.traffic_sources or None,
                    "top_countries": perf.top_countries or None,
                    "device_types": perf.device_types or None,
                    "subscriber_ratio": perf.subscriber_ratio or None,
                }))

                self.poll_videos(niche["id"], analytics, published_rows, start_date, end_date)
                self._flag_and_analyze_zombies(niche["id"], niche["name"], published_rows)

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

        # Channel-level discovery: find videos on YouTube not yet in published_videos
        # (handles uploads that pre-date the current pipeline or had DB write failures)
        for ch_id, info in channel_info.items():
            try:
                all_ids: set[str] = set()
                for niche_info in info["niche_infos"]:
                    all_ids.update(
                        r["youtube_video_id"] for r in self._fetch_published_videos(niche_info["id"])
                    )
                found = self._discover_channel_orphans(
                    info["yt_service"], ch_id, info["niche_infos"], all_ids
                )
                if found:
                    print(f"[analytics] discovered {found} orphaned video(s) on channel {ch_id}")
            except Exception as e:
                print(f"[analytics] orphan discovery failed for channel {ch_id} (non-fatal): {e}")

        if failures:
            raise RuntimeError(f"[analytics] polling failed for {len(failures)} niche(s): {failures}")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    poller = AnalyticsPoller(supabase=sb)
    poller.run()


if __name__ == "__main__":
    main()
