from dataclasses import dataclass
from typing import List, Set
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
    ) -> List[RedditPost]:
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
        subreddits: List[str],
        min_score: int = 500,
        min_body_length: int = 300,
    ) -> List[RedditPost]:
        all_posts: List[RedditPost] = []
        for subreddit in subreddits:
            try:
                posts = self.fetch_top_posts(subreddit, min_score, min_body_length)
                all_posts.extend(posts)
                time.sleep(1)
            except Exception as e:
                print(f"[reddit] failed for r/{subreddit}: {e}")
        return all_posts

    def deduplicate(self, posts: List[RedditPost], known_ids: Set[str]) -> List[RedditPost]:
        return [p for p in posts if p.post_id not in known_ids]


def main():
    from supabase import create_client
    from agents.shared.config_loader import get_env, get_subreddits
    from agents.shared.anthropic_client import complete
    from agents.shared.gate_client import GateClient, GateNumber
    from agents.shared.db_retry import execute_with_retry

    sb = create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))
    gate = GateClient(sb)
    scraper = RedditScraper()
    subreddits_map = get_subreddits()

    active_niches = execute_with_retry(sb.table("niches").select("*").in_("status", ["testing", "promoted"])).data
    known_ids = {row["reddit_post_id"] for row in execute_with_retry(sb.table("topics").select("reddit_post_id")).data}

    for niche in active_niches:
        subs = niche.get("subreddits") or subreddits_map.get(niche["category"], [])
        posts = scraper.fetch_all_for_niche(subs)
        posts = scraper.deduplicate(posts, known_ids)
        for post in posts[:10]:
            score_prompt = f"Rate this Reddit post for YouTube video potential (1-10). Title: {post.title}\nBody excerpt: {post.body[:300]}\nReturn only the integer score."
            try:
                score_str = complete(score_prompt, model="claude-haiku-4-5-20251001", max_tokens=10)
                claude_score = float(score_str.strip())
            except Exception:
                claude_score = 5.0

            result = execute_with_retry(sb.table("topics").insert({
                "niche_id": niche["id"],
                "reddit_post_id": post.post_id,
                "title": post.title,
                "url": post.url,
                "body": post.body,
                "upvotes": post.score,
                "claude_score": claude_score,
                "status": "pending",
                "gate2_state": "pending",
            }))
            topic_id = result.data[0]["id"]
            gate.advance_or_pause(
                gate=GateNumber.TOPIC_SELECTION,
                niche_id=niche["id"],
                table="topics",
                item_id=topic_id,
                gate_column="gate2_state",
                auto_state="approved",
                review_state="awaiting_review",
            )
            known_ids.add(post.post_id)
    print(f"[reddit-scraper] done for {len(active_niches)} active niches")


if __name__ == "__main__":
    main()
