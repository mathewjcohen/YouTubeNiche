import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
import edge_tts
from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry

VOICE = "en-US-AriaNeural"


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


class VoiceoverAgent:
    def __init__(self, supabase: Client, gate_client: GateClient, output_dir: str = "output/audio"):
        self._sb = supabase
        self._gate = gate_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def synthesize(self, text: str, output_stem: str) -> Tuple[Path, Path]:
        audio_path = self._output_dir / f"{output_stem}.mp3"
        srt_path = self._output_dir / f"{output_stem}.srt"

        communicate = edge_tts.Communicate(text=text, voice=VOICE)
        words: List[WordTimestamp] = []

        with audio_path.open("wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append(
                        WordTimestamp(
                            word=chunk["text"],
                            offset_ms=chunk["offset"] // 10_000,
                            duration_ms=chunk["duration"] // 10_000,
                        )
                    )

        srt_content = build_srt(words)
        srt_path.write_text(srt_content, encoding="utf-8")
        return audio_path, srt_path

    def _upload(self, local_path: Path, content_type: str) -> str:
        storage_key = local_path.name
        self._sb.storage.from_("voiceovers").upload(
            storage_key, local_path.read_bytes(), {"content-type": content_type}
        )
        return self._sb.storage.from_("voiceovers").get_public_url(storage_key)

    def process_approved_scripts(self, niche_id: str) -> None:
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
                audio_path, srt_path = asyncio.run(self.synthesize(text, stem))
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
