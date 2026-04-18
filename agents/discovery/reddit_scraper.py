from dataclasses import dataclass
import requests
import time


HEADERS = {"User-Agent": "YouTubeNiche-Bot/1.0"}


@dataclass
class RedditPost:
    post_id: str
    title: str
    body: str
    score: int
    url: str
    subreddit: str


class RedditScraper:
    def fetch_top_posts(
        self,
        subreddit: str,
        min_score: int = 500,
        min_body_length: int = 300,
        limit: int = 25,
        timeframe: str = "week",
    ) -> list[RedditPost]:
        url = f"https://www.reddit.com/r/{subreddit}/top.json"
        resp = requests.get(
            url,
            params={"t": timeframe, "limit": limit},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        children = resp.json()["data"]["children"]

        posts = []
        for child in children:
            d = child["data"]
            body = d.get("selftext", "")
            score = d.get("score", 0)
            if score < min_score:
                continue
            if len(body) < min_body_length:
                continue
            posts.append(
                RedditPost(
                    post_id=d["id"],
                    title=d["title"],
                    body=body,
                    score=score,
                    url=d.get("url", ""),
                    subreddit=subreddit,
                )
            )
        return posts

    def fetch_all_for_niche(
        self,
        subreddits: list[str],
        min_score: int = 500,
        min_body_length: int = 300,
    ) -> list[RedditPost]:
        all_posts: list[RedditPost] = []
        for subreddit in subreddits:
            try:
                posts = self.fetch_top_posts(subreddit, min_score, min_body_length)
                all_posts.extend(posts)
                time.sleep(1)
            except Exception as e:
                print(f"[reddit] failed for r/{subreddit}: {e}")
        return all_posts

    def deduplicate(self, posts: list[RedditPost], known_ids: set[str]) -> list[RedditPost]:
        return [p for p in posts if p.post_id not in known_ids]
