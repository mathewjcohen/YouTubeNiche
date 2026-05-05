"""
Pattern analysis agent.

Queries video performance data, computes statistical correlations,
calls Claude API for an LLM-written summary, and persists to the
`insights` table for the dashboard to surface.
"""

import json
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional

from supabase import Client, create_client

from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared import anthropic_client

PERIOD_DAYS = 30
MIN_VIDEOS_FOR_ANALYSIS = 3


def _word_count(text: Optional[str]) -> int:
    if not text:
        return 0
    return len(text.split())


def _script_length_bucket(wc: int, video_type: str) -> str:
    if video_type == "short":
        if wc < 100:
            return "<100 words"
        if wc < 200:
            return "100-200 words"
        return "200+ words"
    else:
        if wc < 500:
            return "<500 words"
        if wc < 1000:
            return "500-1000 words"
        return "1000+ words"


def _retention_50pct_drop(retention_json: Optional[dict]) -> Optional[float]:
    """Return the earliest elapsedRatio where audienceWatchRatio drops below 0.5."""
    if not retention_json:
        return None
    for ratio_str, watch_ratio in sorted(retention_json.items(), key=lambda x: float(x[0])):
        if float(watch_ratio) < 0.5:
            return float(ratio_str)
    return None


def _safe_avg(vals: list) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _safe_median(vals: list) -> Optional[float]:
    return statistics.median(vals) if vals else None


class InsightsAgent:
    def __init__(self):
        patch_postgrest_http1()
        self._sb: Client = create_client(
            get_env("SUPABASE_URL"),
            get_env("SUPABASE_SERVICE_KEY"),
        )

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_video_data(self) -> list[dict]:
        niches_resp = execute_with_retry(
            self._sb.table("niches")
            .select("id, name")
            .in_("status", ["testing", "promoted"])
        )
        niche_map: dict[str, str] = {n["id"]: n["name"] for n in (niches_resp.data or [])}
        if not niche_map:
            return []

        pv_resp = execute_with_retry(
            self._sb.table("published_videos")
            .select("youtube_video_id, niche_id, video_type, title, duration_sec, script_id")
            .in_("niche_id", list(niche_map.keys()))
        )
        published = pv_resp.data or []
        if not published:
            return []

        script_ids = [pv["script_id"] for pv in published if pv.get("script_id")]
        scripts_map: dict[str, dict] = {}
        if script_ids:
            scripts_resp = execute_with_retry(
                self._sb.table("scripts")
                .select("id, long_form_text, short_text")
                .in_("id", script_ids)
            )
            scripts_map = {s["id"]: s for s in (scripts_resp.data or [])}

        video_ids = [pv["youtube_video_id"] for pv in published if pv.get("youtube_video_id")]
        if not video_ids:
            return []

        va_resp = execute_with_retry(
            self._sb.table("video_analytics")
            .select("youtube_video_id, views, avg_view_pct, avg_view_duration_sec, likes, estimated_minutes_watched, audience_retention_json")
            .in_("youtube_video_id", video_ids)
            .order("polled_at", desc=True)
        )
        latest_va: dict[str, dict] = {}
        for row in (va_resp.data or []):
            if row["youtube_video_id"] not in latest_va:
                latest_va[row["youtube_video_id"]] = row

        results = []
        for pv in published:
            vid = pv.get("youtube_video_id")
            if not vid or vid not in latest_va:
                continue
            va = latest_va[vid]
            script = scripts_map.get(pv.get("script_id") or "")
            text_key = "short_text" if pv["video_type"] == "short" else "long_form_text"
            wc = _word_count(script.get(text_key) if script else None)

            results.append({
                "niche_name": niche_map.get(pv["niche_id"], "Unknown"),
                "video_type": pv["video_type"],
                "title": pv.get("title") or vid,
                "duration_sec": pv.get("duration_sec"),
                "word_count": wc,
                "views": va.get("views") or 0,
                "avg_view_pct": va.get("avg_view_pct"),
                "avg_view_duration_sec": va.get("avg_view_duration_sec"),
                "likes": va.get("likes") or 0,
                "estimated_minutes_watched": va.get("estimated_minutes_watched"),
                "audience_retention_json": va.get("audience_retention_json"),
            })

        return results

    # ------------------------------------------------------------------
    # Stats computation
    # ------------------------------------------------------------------

    def _compute_stats(self, videos: list[dict]) -> dict:
        total_views = sum(v["views"] for v in videos)
        all_watch_pcts = [v["avg_view_pct"] for v in videos if v["avg_view_pct"] is not None]

        # --- By niche ---
        by_niche: dict[str, list] = {}
        for v in videos:
            by_niche.setdefault(v["niche_name"], []).append(v)

        niche_stats = []
        for niche_name, vids in sorted(by_niche.items()):
            niche_views = sum(v["views"] for v in vids)
            pcts = [v["avg_view_pct"] for v in vids if v["avg_view_pct"] is not None]
            niche_stats.append({
                "niche": niche_name,
                "video_count": len(vids),
                "total_views": niche_views,
                "avg_watch_pct": round(_safe_avg(pcts) or 0, 3),
                "avg_views_per_video": round(niche_views / len(vids), 1),
            })
        niche_stats.sort(key=lambda x: x["avg_watch_pct"], reverse=True)

        # --- By type ---
        by_type: dict[str, list] = {"long": [], "short": []}
        for v in videos:
            by_type[v["video_type"]].append(v)

        type_stats: dict[str, dict] = {}
        for vtype, vids in by_type.items():
            if not vids:
                continue
            pcts = [v["avg_view_pct"] for v in vids if v["avg_view_pct"] is not None]
            type_stats[vtype] = {
                "count": len(vids),
                "total_views": sum(v["views"] for v in vids),
                "avg_watch_pct": round(_safe_avg(pcts) or 0, 3),
                "avg_views": round(sum(v["views"] for v in vids) / len(vids), 1),
            }

        # --- By script length bucket ---
        by_bucket: dict[str, list] = {}
        for v in videos:
            bucket = _script_length_bucket(v["word_count"], v["video_type"])
            by_bucket.setdefault(bucket, []).append(v)

        bucket_stats = []
        for bucket, vids in by_bucket.items():
            pcts = [v["avg_view_pct"] for v in vids if v["avg_view_pct"] is not None]
            bucket_stats.append({
                "script_length": bucket,
                "count": len(vids),
                "avg_watch_pct": round(_safe_avg(pcts) or 0, 3),
                "avg_views": round(sum(v["views"] for v in vids) / len(vids), 1),
            })
        bucket_stats.sort(key=lambda x: x["avg_watch_pct"], reverse=True)

        # --- Retention drop-off ---
        drop_points = [
            dp for v in videos
            if (dp := _retention_50pct_drop(v.get("audience_retention_json"))) is not None
        ]
        retention_stats = {
            "videos_with_data": len(drop_points),
            "avg_50pct_dropoff": round(_safe_avg(drop_points) or 0, 3) if drop_points else None,
            "median_50pct_dropoff": round(_safe_median(drop_points) or 0, 3) if drop_points else None,
        }

        # --- Top / bottom performers (by watch %) ---
        with_data = [v for v in videos if v["avg_view_pct"] is not None]
        sorted_by_watch = sorted(with_data, key=lambda x: x["avg_view_pct"], reverse=True)

        def _summary(v: dict) -> dict:
            return {
                "title": v["title"],
                "niche": v["niche_name"],
                "type": v["video_type"],
                "views": v["views"],
                "watch_pct": round(v["avg_view_pct"] or 0, 3),
                "word_count": v["word_count"],
                "duration_sec": v["duration_sec"],
            }

        return {
            "period_days": PERIOD_DAYS,
            "total_videos": len(videos),
            "total_views": total_views,
            "overall_avg_watch_pct": round(_safe_avg(all_watch_pcts) or 0, 3),
            "by_niche": niche_stats,
            "by_type": type_stats,
            "by_script_length": bucket_stats,
            "retention": retention_stats,
            "top_5_videos": [_summary(v) for v in sorted_by_watch[:5]],
            "bottom_5_videos": [_summary(v) for v in sorted_by_watch[-5:]],
        }

    # ------------------------------------------------------------------
    # LLM summary
    # ------------------------------------------------------------------

    def _generate_summary(self, stats: dict) -> str:
        stats_text = json.dumps(stats, indent=2)
        prompt = f"""You are an analyst reviewing YouTube channel performance for a niche testing pipeline. Below are statistics computed over the last {PERIOD_DAYS} days across all active niches.

{stats_text}

Write a concise, actionable insights report (3-5 bullet points) covering:
- Which niches or video types are performing best (cite actual numbers)
- Where viewers are dropping off based on retention data
- Script length patterns that correlate with better watch time
- Specific, concrete recommendations to improve performance

Be direct and data-driven. Reference actual numbers. No filler or generic advice."""

        return anthropic_client.complete(prompt, max_tokens=1024)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        print("[insights] fetching video performance data")
        videos = self._fetch_video_data()

        if len(videos) < MIN_VIDEOS_FOR_ANALYSIS:
            print(f"[insights] only {len(videos)} videos with analytics — skipping (need >= {MIN_VIDEOS_FOR_ANALYSIS})")
            return

        print(f"[insights] computing stats for {len(videos)} videos")
        stats = self._compute_stats(videos)

        print("[insights] generating LLM summary")
        summary = self._generate_summary(stats)

        execute_with_retry(
            self._sb.table("insights").insert({
                "period_days": PERIOD_DAYS,
                "stats_json": stats,
                "summary_text": summary,
            })
        )
        print("[insights] insights record saved")


if __name__ == "__main__":
    InsightsAgent().run()
