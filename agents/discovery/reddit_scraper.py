from dataclasses import dataclass
from typing import List, Set
import os
import re
import time
import html

import feedparser
import requests


HEADERS = {"User-Agent": "YouTubeNiche-Bot/1.0"}
_POST_ID_RE = re.compile(r"/comments/([a-z0-9]+)/")


@dataclass
class RedditPost:
    post_id: str
    title: str
    body: str
    score: int
    url: str
    subreddit: str


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text).strip()


def _post_id_from_url(url: str) -> str | None:
    m = _POST_ID_RE.search(url)
    return m.group(1) if m else None


class RedditScraper:
    def fetch_top_posts(
        self,
        subreddit: str,
        min_body_length: int = 300,
        limit: int = 25,
        timeframe: str = "week",
    ) -> List[RedditPost]:
        url = f"https://www.reddit.com/r/{subreddit}/top.rss"
        resp = requests.get(url, params={"t": timeframe, "limit": limit}, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        posts = []
        for entry in feed.entries:
            post_id = _post_id_from_url(entry.get("link", ""))
            if not post_id:
                continue
            body = _strip_html(entry.get("summary", ""))
            if len(body) < min_body_length:
                continue
            posts.append(RedditPost(
                post_id=post_id,
                title=entry.get("title", ""),
                body=body,
                score=0,
                url=entry.get("link", ""),
                subreddit=subreddit,
            ))
        return posts

    def fetch_all_for_niche(
        self,
        subreddits: List[str],
        min_body_length: int = 300,
    ) -> List[RedditPost]:
        all_posts: List[RedditPost] = []
        for subreddit in subreddits:
            try:
                posts = self.fetch_top_posts(subreddit, min_body_length)
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
    from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1

    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
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
            if not result.data:
                print(f"[reddit] insert returned no data for post {post.post_id}, skip")
                continue
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
