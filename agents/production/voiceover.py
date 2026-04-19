import asyncio
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional
import edge_tts
from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry
from agents.shared.config_loader import get_env

# OpenAI TTS — used when OPENAI_API_KEY is set
OPENAI_TTS_MODEL = "tts-1-hd"

# Per-category voice selection
# onyx  — deep, relaxed, authoritative (law, finance, tax)
# nova   — warm, friendly, approachable (health, insurance, career)
CATEGORY_VOICE: dict[str, str] = {
    "legal":            "onyx",
    "insurance":        "nova",
    "tax":              "onyx",
    "personal_finance": "onyx",
    "real_estate":      "nova",
    "career":           "nova",
    "ai_tech":          "onyx",
    "health":           "nova",
}
DEFAULT_VOICE = "onyx"

# Fallback when no OpenAI key
EDGE_TTS_VOICE = "en-US-AndrewNeural"


def _clean_for_tts(text: str) -> str:
    """Strip stage directions, B-roll notes, and production metadata from script text."""
    # Remove [B-ROLL: ...] and any other bracketed directions (including multi-line)
    text = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove lines that are only hashtags or production keywords
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append(line)
            continue
        # Skip hashtag lines
        if re.match(r'^#\w', s):
            continue
        # Skip lines that start with known production keywords
        if re.match(
            r'^(b[-\s]?roll|cold open|tight shot|wide shot|cut to|fade|overlay|'
            r'timestamp|scene|hashtag|vo:|narrator:|on[-\s]?screen)',
            s, re.IGNORECASE
        ):
            continue
        cleaned.append(line)
    text = '\n'.join(cleaned)
    # Collapse excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


@dataclass
class WordTimestamp:
    word: str
    offset_ms: int
    duration_ms: int


def ms_to_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_srt(words: List[WordTimestamp], max_chars_per_cue: int = 80) -> str:
    if not words:
        return ""
    cues: List[Tuple[int, int, str]] = []
    current_words: List[WordTimestamp] = []
    current_chars = 0

    def flush():
        if not current_words:
            return
        start = current_words[0].offset_ms
        last = current_words[-1]
        end = last.offset_ms + last.duration_ms
        text = " ".join(w.word for w in current_words)
        cues.append((start, end, text))

    for w in words:
        if current_chars + len(w.word) + 1 > max_chars_per_cue and current_words:
            flush()
            current_words = []
            current_chars = 0
        current_words.append(w)
        current_chars += len(w.word) + 1

    flush()

    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_srt_time(start)} --> {ms_to_srt_time(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _build_word_timestamps_from_text(text: str, audio_path: Path) -> List[WordTimestamp]:
    """
    OpenAI TTS doesn't return word-level timestamps via the standard API.
    Build approximate timestamps by splitting text into words and distributing
    evenly across the audio duration using mutagen for the actual MP3 length.
    """
    try:
        from mutagen.mp3 import MP3
        duration_ms = int(MP3(str(audio_path)).info.length * 1000)
    except Exception:
        # Rough fallback: ~150 words per minute
        word_count = len(text.split())
        duration_ms = int(word_count / 150 * 60 * 1000)

    words = text.split()
    if not words:
        return []
    per_word_ms = duration_ms // len(words)
    result = []
    for i, word in enumerate(words):
        result.append(WordTimestamp(
            word=word,
            offset_ms=i * per_word_ms,
            duration_ms=per_word_ms,
        ))
    return result


class VoiceoverAgent:
    def __init__(self, supabase: Client, gate_client: GateClient, output_dir: str = "output/audio"):
        self._sb = supabase
        self._gate = gate_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        _key = get_env("OPENAI_API_KEY", required=False)
        self._openai_key: Optional[str] = _key or None

    def _synthesize_openai(self, text: str, audio_path: Path, voice: str) -> List[WordTimestamp]:
        from openai import OpenAI
        client = OpenAI(api_key=self._openai_key)
        print(f"[voiceover] using OpenAI TTS ({OPENAI_TTS_MODEL}/{voice})")
        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        audio_path.write_bytes(response.content)
        return _build_word_timestamps_from_text(text, audio_path)

    async def _synthesize_edge(self, text: str, audio_path: Path) -> List[WordTimestamp]:
        print(f"[voiceover] using edge-tts ({EDGE_TTS_VOICE})")
        communicate = edge_tts.Communicate(text=text, voice=EDGE_TTS_VOICE)
        words: List[WordTimestamp] = []
        with audio_path.open("wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append(WordTimestamp(
                        word=chunk["text"],
                        offset_ms=chunk["offset"] // 10_000,
                        duration_ms=chunk["duration"] // 10_000,
                    ))
        return words

    async def synthesize(self, text: str, output_stem: str, category: str = "", max_attempts: int = 3) -> Tuple[Path, Path]:
        text = _clean_for_tts(text)
        audio_path = self._output_dir / f"{output_stem}.mp3"
        srt_path = self._output_dir / f"{output_stem}.srt"
        voice = CATEGORY_VOICE.get(category.lower(), DEFAULT_VOICE)

        last_exc: Exception = RuntimeError("no attempts made")
        for attempt in range(1, max_attempts + 1):
            try:
                if self._openai_key:
                    words = self._synthesize_openai(text, audio_path, voice)
                else:
                    words = await self._synthesize_edge(text, audio_path)
                srt_content = build_srt(words)
                srt_path.write_text(srt_content, encoding="utf-8")
                return audio_path, srt_path
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts:
                    wait = 2 ** attempt + random.uniform(0, 1)
                    print(f"[voiceover] synthesis attempt {attempt}/{max_attempts} failed: {exc}; retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
        raise last_exc

    def _upload(self, local_path: Path, content_type: str) -> str:
        storage_key = local_path.name
        self._sb.storage.from_("voiceovers").upload(
            storage_key, local_path.read_bytes(), {"content-type": content_type, "upsert": "true"}
        )
        return self._sb.storage.from_("voiceovers").get_public_url(storage_key)

    def process_approved_scripts(self, niche_id: str) -> None:
        niche_rows = execute_with_retry(
            self._sb.table("niches").select("category").eq("id", niche_id).limit(1)
        ).data
        category = niche_rows[0]["category"] if niche_rows else ""
        scripts = execute_with_retry(
            self._sb.table("scripts")
            .select("*")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .eq("status", "pending")
        ).data
        for script in scripts:
            for video_type, text in [("long", script["long_form_text"]), ("short", script["short_text"])]:
                stem = f"{script['id'][:8]}_{video_type}"
                try:
                    audio_path, srt_path = asyncio.run(self.synthesize(text, stem, category=category))
                except Exception as exc:
                    print(f"[voiceover] synthesis failed for {stem} after retries: {exc}; skipping")
                    continue
                audio_url = self._upload(audio_path, "audio/mpeg")
                srt_url = self._upload(srt_path, "text/plain")

                result = execute_with_retry(
                    self._sb.table("videos").insert(
                        {
                            "script_id": script["id"],
                            "niche_id": niche_id,
                            "video_type": video_type,
                            "audio_path": audio_url,
                            "srt_path": srt_url,
                            "status": "pending",
                            "gate4_state": "pending",
                        }
                    )
                )
                if not result.data:
                    print(f"[voiceover] insert returned no data for script {script['id']} ({video_type}), skip")
                    continue
                video_id = result.data[0]["id"]
                self._gate.advance_or_pause(
                    gate=GateNumber.VOICEOVER,
                    niche_id=niche_id,
                    table="videos",
                    item_id=video_id,
                    gate_column="gate4_state",
                    auto_state="approved",
                    review_state="awaiting_review",
                )
            execute_with_retry(
                self._sb.table("scripts").update({"status": "processing"}).eq("id", script["id"])
            )
