import re
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

PRIVACY: Never use real names or usernames from the source story, even if they were posted publicly.
Refer to people by role or description only (e.g. "the landlord", "a Reddit user", "the employer").

CRITICAL: Output ONLY the spoken narration — no title, no section headers, no timestamps,
no stage directions, no camera notes, no brackets or production metadata of any kind.
Your response begins with the first spoken word of the narration and ends with the last."""

SHORT_FORM_PROMPT = """You are writing a YouTube Short script (60 seconds, ~200 words) based on this longer script.

The Short should:
- Open with the single most attention-grabbing line from the full story
- Summarize the key revelation or outcome in 40–50 seconds
- End with: "Watch the full story in the description."

Full script for reference:
{long_form}

PRIVACY: Never use real names or usernames from the source story, even if they were posted publicly.
Refer to people by role or description only (e.g. "the landlord", "a Reddit user", "the employer").

CRITICAL: Output ONLY the spoken narration — no title, no label, no duration, no headers,
no "YouTube Short", no "Script:", no brackets or production notes of any kind.
Your response begins with the first spoken word of the narration and ends with the last."""

METADATA_PROMPT = """Generate YouTube metadata for this video script.

Script excerpt (first 500 chars): {excerpt}
Niche: {niche_name}
Category: {category}

Return exactly three lines:
Line 1: Title (under 70 chars, no clickbait, specific and curiosity-driven)
Line 2: Description (2 sentences, include the word "{category}" naturally, end with "Like and subscribe for more.")
Line 3: Tags (8 tags, comma-separated, no spaces around commas)"""

DISCLAIMERS: dict[str, str] = {
    "legal": (
        "\n\n⚠️ DISCLAIMER: This video is for informational and entertainment purposes only and does "
        "not constitute legal advice. Laws vary by jurisdiction. Always consult a licensed attorney "
        "for advice specific to your situation."
    ),
    "insurance": (
        "\n\n⚠️ DISCLAIMER: This video is for informational purposes only and does not constitute "
        "insurance advice. Coverage and policies vary. Consult a licensed insurance professional "
        "before making any decisions."
    ),
    "tax": (
        "\n\n⚠️ DISCLAIMER: This video is for informational purposes only and does not constitute "
        "tax or financial advice. Tax laws vary and change frequently. Consult a licensed CPA or "
        "tax professional for guidance specific to your situation."
    ),
    "personal_finance": (
        "\n\n⚠️ DISCLAIMER: This video is for informational and entertainment purposes only and is "
        "not financial advice. Investing involves risk, including possible loss of principal. Consult "
        "a certified financial planner before making financial decisions."
    ),
    "real_estate": (
        "\n\n⚠️ DISCLAIMER: This video is for informational purposes only and does not constitute "
        "real estate or legal advice. Market conditions vary by location. Consult a licensed real "
        "estate agent or attorney before making real estate decisions."
    ),
    "career": (
        "\n\n⚠️ DISCLAIMER: This video is for informational and entertainment purposes only. "
        "Individual results may vary. Consult a career professional or attorney for advice specific "
        "to your employment situation."
    ),
    "ai_tech": (
        "\n\n⚠️ DISCLAIMER: This video is for informational purposes only. Technology and AI "
        "capabilities change rapidly. Always verify information with official documentation before "
        "making business or technical decisions."
    ),
    "health": (
        "\n\n⚠️ DISCLAIMER: This video is for informational and entertainment purposes only and does "
        "not constitute medical advice. It is not a substitute for professional medical diagnosis, "
        "treatment, or advice. Always consult a qualified healthcare provider before making any "
        "health-related decisions."
    ),
}

_DEFAULT_DISCLAIMER = (
    "\n\n⚠️ DISCLAIMER: This video is for informational and entertainment purposes only. "
    "Consult a qualified professional before making any decisions based on this content."
)


_AI_VOICE_DISCLOSURE = "\n\n🤖 Voiceover is AI-generated."


def get_disclaimer(category: str) -> str:
    return DISCLAIMERS.get(category.lower(), _DEFAULT_DISCLAIMER) + _AI_VOICE_DISCLOSURE


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
        _broll = re.compile(r'\[B-ROLL:.*?\]\n?', re.IGNORECASE | re.DOTALL)

        long_form = _broll.sub('', complete_sonnet(
            LONG_FORM_PROMPT.format(
                title=topic_title,
                body=topic_body[:3000],
                category=niche_category,
            ),
            max_tokens=3000,
        )).strip()
        short_form = _broll.sub('', complete(
            SHORT_FORM_PROMPT.format(long_form=long_form[:2000]),
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
        )).strip()
        meta_raw = complete_sonnet(
            METADATA_PROMPT.format(
                excerpt=long_form[:500],
                niche_name=niche_name,
                category=niche_category,
            ),
            max_tokens=300,
        )
        lines = [re.sub(r'^Line \d+:\s*', '', l.strip()) for l in meta_raw.strip().split("\n") if l.strip()]
        title = lines[0] if len(lines) > 0 else topic_title[:70]
        base_description = lines[1] if len(lines) > 1 else ""
        tags = [t.strip() for t in lines[2].split(",") if t.strip()] if len(lines) > 2 else []
        description = base_description + get_disclaimer(niche_category)

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
            .eq("status", "pending")
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
