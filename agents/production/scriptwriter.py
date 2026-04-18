from dataclasses import dataclass
from typing import List, Optional
from supabase import Client
from agents.shared.anthropic_client import complete, complete_sonnet
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry


LONG_FORM_PROMPT = """You are writing a script for a faceless YouTube video in the {category} niche.

Topic title: {title}
Source story: {body}

Write a complete video script (~1,800 words, ~12 minutes) in this structure:
- Hook (30 seconds): open with the most dramatic or surprising moment
- Context (2 min): background and stakes
- Story (6 min): detailed narrative, what happened, turning points
- Lesson (2 min): what the viewer can learn or action they can take
- CTA (30 sec): "If this happened to you..." + subscribe line

Include scene direction tags like [B-ROLL: person reading documents] throughout.
Write conversationally, as if telling a friend. No jargon. No filler.
Do NOT include a title or headers in the output — just the spoken script text."""

SHORT_FORM_PROMPT = """You are writing a YouTube Short script (60 seconds, ~200 words) based on this longer script.

The Short should:
- Open with the single most attention-grabbing line from the full story
- Summarize the key revelation or outcome in 40–50 seconds
- End with: "Full story linked in bio."

Full script for reference:
{long_form}

Write only the spoken Short script. No headers."""

METADATA_PROMPT = """Generate YouTube metadata for this video script.

Script excerpt (first 500 chars): {excerpt}
Niche: {niche_name}
Category: {category}

Return exactly three lines:
Line 1: Title (under 70 chars, no clickbait, specific and curiosity-driven)
Line 2: Description (2 sentences, include the word "{category}" naturally, end with "Like and subscribe for more.")
Line 3: Tags (8 tags, comma-separated, no spaces around commas)"""


@dataclass
class ScriptPair:
    long_form: str
    short_form: str
    youtube_title: str
    youtube_description: str
    youtube_tags: List[str]


class Scriptwriter:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def generate(
        self,
        topic_title: str,
        topic_body: str,
        niche_name: str,
        niche_category: str,
    ) -> ScriptPair:
        long_form = complete_sonnet(
            LONG_FORM_PROMPT.format(
                title=topic_title,
                body=topic_body[:3000],
                category=niche_category,
            ),
            max_tokens=3000,
        )
        short_form = complete(
            SHORT_FORM_PROMPT.format(long_form=long_form[:2000]),
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
        )
        meta_raw = complete_sonnet(
            METADATA_PROMPT.format(
                excerpt=long_form[:500],
                niche_name=niche_name,
                category=niche_category,
            ),
            max_tokens=300,
        )
        lines = [l.strip() for l in meta_raw.strip().split("\n") if l.strip()]
        title = lines[0] if len(lines) > 0 else topic_title[:70]
        description = lines[1] if len(lines) > 1 else ""
        tags = [t.strip() for t in lines[2].split(",") if t.strip()] if len(lines) > 2 else []

        return ScriptPair(
            long_form=long_form,
            short_form=short_form,
            youtube_title=title,
            youtube_description=description,
            youtube_tags=tags,
        )

    def write_to_db(self, pair: ScriptPair, topic_id: str, niche_id: str) -> str:
        result = execute_with_retry(
            self._sb.table("scripts").insert(
                {
                    "topic_id": topic_id,
                    "niche_id": niche_id,
                    "long_form_text": pair.long_form,
                    "short_text": pair.short_form,
                    "youtube_title": pair.youtube_title,
                    "youtube_description": pair.youtube_description,
                    "youtube_tags": pair.youtube_tags,
                    "status": "pending",
                    "gate3_state": "awaiting_review",
                }
            )
        )
        if not result.data:
            raise RuntimeError(f"Script insert returned no data for topic {topic_id}")
        return result.data[0]["id"]

    def process_approved_topics(self, niche_id: str) -> None:
        topics = execute_with_retry(
            self._sb.table("topics")
            .select("*")
            .eq("niche_id", niche_id)
            .eq("gate2_state", "approved")
            .eq("status", "approved")
        ).data
        niche_rows = execute_with_retry(
            self._sb.table("niches").select("name,category").eq("id", niche_id).limit(1)
        ).data
        if not niche_rows:
            print(f"[scriptwriter] niche {niche_id} not found, skip")
            return
        niche = niche_rows[0]
        for topic in topics:
            pair = self.generate(
                topic_title=topic["title"],
                topic_body=topic.get("body", ""),
                niche_name=niche["name"],
                niche_category=niche["category"],
            )
            script_id = self.write_to_db(pair, topic_id=topic["id"], niche_id=niche_id)
            self._gate.advance_or_pause(
                gate=GateNumber.SCRIPT,
                niche_id=niche_id,
                table="scripts",
                item_id=script_id,
                gate_column="gate3_state",
                auto_state="approved",
                review_state="awaiting_review",
            )
            execute_with_retry(
                self._sb.table("topics").update({"status": "processing"}).eq("id", topic["id"])
            )
