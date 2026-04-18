from dataclasses import dataclass
from typing import Optional
import requests

INVIDIOUS_INSTANCES = [
    "https://invidious.privacyredirect.com",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
]

RPM_TABLE = {
    "legal": (20.0, 50.0),
    "insurance": (25.0, 45.0),
    "tax": (20.0, 40.0),
    "personal_finance": (15.0, 35.0),
    "real_estate": (15.0, 30.0),
    "career": (10.0, 20.0),
    "ai_tech": (10.0, 25.0),
    "health": (8.0, 20.0),
}

DEFAULT_RPM = (2.0, 8.0)


@dataclass
class VideoSearchResult:
    video_id: str
    title: str
    view_count: int
    duration_seconds: int
    channel_name: str
    source: str  # 'invidious' | 'rapidapi' | 'rpm_proxy'


class YouTubeClient:
    def __init__(self, rapidapi_key: str = ""):
        self._rapidapi_key = rapidapi_key

    def search(self, query: str, max_results: int = 10) -> list:
        results = self._try_invidious(query, max_results)
        if results is not None:
            return results

        results = self._try_rapidapi(query, max_results)
        if results is not None:
            return results

        # RPM proxy fallback: no search results, caller uses RPM estimate only
        return []

    def _try_invidious(self, query: str, max_results: int) -> Optional[list]:
        for instance in INVIDIOUS_INSTANCES:
            try:
                resp = requests.get(
                    f"{instance}/api/v1/search",
                    params={"q": query, "type": "video", "page": 1},
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                return [
                    VideoSearchResult(
                        video_id=item.get("videoId", ""),
                        title=item.get("title", ""),
                        view_count=int(item.get("viewCount", 0)),
                        duration_seconds=int(item.get("lengthSeconds", 0)),
                        channel_name=item.get("author", ""),
                        source="invidious",
                    )
                    for item in data[:max_results]
                    if item.get("type") == "video" or "videoId" in item
                ]
            except Exception:
                continue
        return None

    def _try_rapidapi(self, query: str, max_results: int) -> Optional[list]:
        if not self._rapidapi_key:
            return None
        try:
            resp = requests.get(
                "https://youtube-search-and-download.p.rapidapi.com/search",
                headers={
                    "X-RapidAPI-Key": self._rapidapi_key,
                    "X-RapidAPI-Host": "youtube-search-and-download.p.rapidapi.com",
                },
                params={"query": query, "type": "v"},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            contents = resp.json().get("contents", [])
            results = []
            for item in contents[:max_results]:
                v = item.get("video", {})
                if not v:
                    continue
                results.append(
                    VideoSearchResult(
                        video_id=v.get("videoId", ""),
                        title=v.get("title", ""),
                        view_count=int(v.get("stats", {}).get("views", 0)),
                        duration_seconds=int(v.get("lengthSeconds", 0)),
                        channel_name=v.get("author", {}).get("title", ""),
                        source="rapidapi",
                    )
                )
            return results
        except Exception:
            return None

    def get_rpm_estimate(self, category: str) -> tuple[float, float]:
        return RPM_TABLE.get(category, DEFAULT_RPM)
