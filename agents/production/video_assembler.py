import re
import tempfile
import urllib.request
from pathlib import Path
from typing import List, Tuple, Optional

import requests
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, ColorClip
)
from supabase import Client
from agents.shared.gate_client import GateClient


BROLL_PATTERN = re.compile(r"\[B-ROLL:\s*(.+?)\]", re.IGNORECASE)


def extract_scene_tags(script: str) -> List[str]:
    return BROLL_PATTERN.findall(script)


class PexelsClient:
    BASE = "https://api.pexels.com/videos"

    def __init__(self, api_key: str):
        self._headers = {"Authorization": api_key}

    def search_video_urls(self, query: str, count: int = 3) -> List[str]:
        resp = requests.get(
            f"{self.BASE}/search",
            headers=self._headers,
            params={"query": query, "per_page": count, "orientation": "landscape"},
            timeout=10,
        )
        resp.raise_for_status()
        urls = []
        for video in resp.json().get("videos", [])[:count]:
            files = video.get("video_files", [])
            hd = [f for f in files if f.get("quality") == "hd" and f.get("width", 0) >= 1280]
            chosen = hd[0] if hd else (files[0] if files else None)
            if chosen:
                urls.append(chosen["link"])
        return urls

    def download_clip(self, url: str, dest_path: Path) -> Path:
        urllib.request.urlretrieve(url, str(dest_path))
        return dest_path


class VideoAssembler:
    TARGET_WIDTH = 1920
    TARGET_HEIGHT = 1080
    FPS = 24

    def __init__(
        self,
        supabase: Client,
        gate_client: GateClient,
        pexels_client: PexelsClient,
        output_dir: str = "output/video",
    ):
        self._sb = supabase
        self._gate = gate_client
        self._pexels = pexels_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def assemble(
        self,
        audio_path: str,
        srt_path: str,
        script_text: str,
        output_stem: str,
    ) -> Path:
        tags = extract_scene_tags(script_text)
        if not tags:
            tags = ["nature background", "city timelapse", "office work"]

        audio = AudioFileClip(audio_path)
        total_duration = audio.duration
        clip_duration = total_duration / max(len(tags), 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            clips = []
            for i, tag in enumerate(tags):
                urls = self._pexels.search_video_urls(tag, count=1)
                if not urls:
                    clip = ColorClip(
                        size=(self.TARGET_WIDTH, self.TARGET_HEIGHT),
                        color=(0, 0, 0),
                        duration=clip_duration,
                    )
                else:
                    dest = Path(tmpdir) / f"clip_{i}.mp4"
                    self._pexels.download_clip(urls[0], dest)
                    raw = VideoFileClip(str(dest))
                    if raw.duration < clip_duration:
                        loops = int(clip_duration / raw.duration) + 1
                        raw = concatenate_videoclips([raw] * loops)
                    clip = raw.subclip(0, clip_duration).resize((self.TARGET_WIDTH, self.TARGET_HEIGHT))
                clips.append(clip)

            video = concatenate_videoclips(clips, method="chain")
            video = video.set_audio(audio)
            video = video.subclip(0, min(total_duration, video.duration))

            out_path = self._output_dir / f"{output_stem}.mp4"
            video.write_videofile(
                str(out_path),
                fps=self.FPS,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(self._output_dir / f"{output_stem}_tmp.m4a"),
                remove_temp=True,
                logger=None,
            )
            return out_path

    def process_approved_voiceovers(self, niche_id: str) -> None:
        videos = (
            self._sb.table("videos")
            .select("*, scripts(long_form_text, short_text)")
            .eq("niche_id", niche_id)
            .eq("gate4_state", "approved")
            .eq("status", "pending")
            .execute()
            .data
        )
        for video in videos:
            script_text = (
                video["scripts"]["long_form_text"]
                if video["video_type"] == "long"
                else video["scripts"]["short_text"]
            )
            stem = f"{video['id'][:8]}_{video['video_type']}_assembled"
            out_path = self.assemble(
                audio_path=video["audio_path"],
                srt_path=video["srt_path"],
                script_text=script_text,
                output_stem=stem,
            )
            self._sb.table("videos").update(
                {"video_path": str(out_path), "status": "processing"}
            ).eq("id", video["id"]).execute()
