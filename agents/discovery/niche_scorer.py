from dataclasses import dataclass, field
from typing import List
from pytrends.request import TrendReq
from agents.discovery.youtube_client import YouTubeClient
from agents.discovery.reddit_scraper import RedditScraper


@dataclass
class NicheScoreResult:
    niche_name: str
    category: str
    final_score: float
    rpm_min: float
    rpm_max: float
    trend_score: float
    reddit_activity: float
    youtube_competition: float
    avg_rpm: float
    details: dict = field(default_factory=dict)


class NicheScorer:
    def __init__(self, youtube_client: YouTubeClient, reddit_scraper: RedditScraper):
        self._yt = youtube_client
        self._reddit = reddit_scraper

    def score(
        self,
        niche_name: str,
        category: str,
        subreddits: List[str],
    ) -> NicheScoreResult:
        rpm_min, rpm_max = self._yt.get_rpm_estimate(category)
        avg_rpm = (rpm_min + rpm_max) / 2

        trend_score = self._get_trend_score(niche_name)
        reddit_activity = self._get_reddit_activity(subreddits)
        yt_videos = self._yt.search(niche_name, max_results=10)
        competition_score = self._compute_competition(yt_videos)

        # Formula: RPM × trend × activity ÷ competition
        if competition_score > 0:
            final_score = (avg_rpm * trend_score * reddit_activity) / competition_score
        else:
            final_score = avg_rpm * trend_score * reddit_activity

        return NicheScoreResult(
            niche_name=niche_name,
            category=category,
            final_score=round(final_score, 2),
            rpm_min=rpm_min,
            rpm_max=rpm_max,
            trend_score=trend_score,
            reddit_activity=reddit_activity,
            youtube_competition=competition_score,
            avg_rpm=avg_rpm,
            details={
                "yt_video_count": len(yt_videos),
                "yt_source": yt_videos[0].source if yt_videos else "rpm_proxy",
            },
        )

    def _get_trend_score(self, keyword: str) -> float:
        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload([keyword], timeframe="today 12-m")
            df = pytrends.interest_over_time()
            if df.empty:
                return 1.0
            series = df[keyword]
            # Normalize: recent 4-week avg ÷ 12-month avg
            recent = float(series.iloc[-4:].mean())
            overall = float(series.mean())
            return round(recent / overall, 2) if overall > 0 else 1.0
        except Exception:
            return 1.0  # neutral fallback

    def _get_reddit_activity(self, subreddits: List[str]) -> float:
        total_score = 0
        count = 0
        for sub in subreddits[:3]:  # cap at 3 to stay polite
            try:
                posts = self._reddit.fetch_top_posts(sub, min_score=100, min_body_length=0, limit=10)
                if posts:
                    total_score += sum(p.score for p in posts) / len(posts)
                    count += 1
            except Exception:
                pass
        if count == 0:
            return 1.0
        avg = total_score / count
        # Normalize: cap at 10K, scale to 1–10
        return round(min(avg / 1000, 10.0), 2)

    def _compute_competition(self, videos: list) -> float:
        if not videos:
            return 1.0
        avg_views = sum(v.view_count for v in videos) / len(videos)
        # Higher avg views = more established competition = harder
        # Normalize to 1–10 scale (10M views ceiling)
        return round(min(avg_views / 100000, 10.0), 2)
