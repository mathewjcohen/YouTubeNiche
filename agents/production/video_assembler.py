import random
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import List, Optional

import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS  # removed in Pillow 10, moviepy 1.x needs it

import boto3
import requests
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, ColorClip
)
from supabase import Client
from agents.shared.gate_client import GateClient
from agents.shared.db_retry import execute_with_retry


BROLL_PATTERN = re.compile(r"\[B-ROLL:\s*(.+?)\]", re.IGNORECASE)
CLIPS_PER_TAG = 3    # clips fetched per B-ROLL tag
MAX_CLIP_SEC = 15    # cap clip length so cuts stay snappy


def extract_scene_tags(script: str) -> List[str]:
    return BROLL_PATTERN.findall(script)


class PexelsClient:
    BASE = "https://api.pexels.com/videos"

    def __init__(self, api_key: str):
        self._headers = {"Authorization": api_key}

    def search_video_urls(self, query: str, count: int = CLIPS_PER_TAG, orientation: str = "landscape") -> List[str]:
        resp = requests.get(
            f"{self.BASE}/search",
            headers=self._headers,
            params={"query": query, "per_page": count, "orientation": orientation},
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
        resp = requests.get(url, headers=self._headers, stream=True, timeout=60)
        resp.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest_path


class VideoAssembler:
    LONG_W, LONG_H = 1920, 1080
    SHORT_W, SHORT_H = 1080, 1920
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

    def _upload_video(self, file_path: Path, object_name: str) -> str:
        from agents.shared.config_loader import get_env
        bucket = get_env("AWS_S3_BUCKET")
        region = get_env("REMOTION_REGION")
        s3 = boto3.client("s3", region_name=region)
        s3.upload_file(
            str(file_path),
            bucket,
            object_name,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        return f"https://{bucket}.s3.{region}.amazonaws.com/{object_name}"

    def assemble(
        self,
        audio_path: str,
        srt_path: str,
        script_text: str,
        output_stem: str,
        is_short: bool = False,
    ) -> str:
        target_w = self.SHORT_W if is_short else self.LONG_W
        target_h = self.SHORT_H if is_short else self.LONG_H
        tags = extract_scene_tags(script_text)
        if not tags:
            tags = ["nature background", "city timelapse", "office work"]

        with tempfile.TemporaryDirectory() as tmpdir:
            if audio_path.startswith("http"):
                local_audio = Path(tmpdir) / "audio.mp3"
                urllib.request.urlretrieve(audio_path, str(local_audio))
                audio_path = str(local_audio)

            audio = AudioFileClip(audio_path)
            total_duration = audio.duration

            # Build a pool of short clips (one per Pexels result across all tags).
            # Capped at MAX_CLIP_SEC so cuts stay snappy; pool is then cycled to
            # fill the full audio duration instead of looping one clip per segment.
            orientation = "portrait" if is_short else "landscape"
            pool: List[VideoFileClip] = []
            for i, tag in enumerate(tags):
                urls = self._pexels.search_video_urls(tag, count=CLIPS_PER_TAG, orientation=orientation)
                for j, url in enumerate(urls):
                    dest = Path(tmpdir) / f"clip_{i}_{j}.mp4"
                    try:
                        self._pexels.download_clip(url, dest)
                        raw = VideoFileClip(str(dest))
                        cap = min(raw.duration, MAX_CLIP_SEC)
                        sub = raw.subclip(0, cap)
                        # Cover-crop: scale to fill target frame, then center-crop
                        scale = max(target_w / sub.w, target_h / sub.h)
                        scaled = sub.resize(scale)
                        cropped = scaled.crop(x_center=scaled.w / 2, y_center=scaled.h / 2, width=target_w, height=target_h)
                        pool.append(cropped)
                    except Exception as exc:
                        print(f"[assembler] clip {i}_{j} download failed: {exc}")

            if not pool:
                pool = [ColorClip(size=(target_w, target_h), color=(0, 0, 0), duration=5)]

            random.shuffle(pool)

            # Cycle through pool clips until total_duration is filled
            timeline: List = []
            elapsed = 0.0
            idx = 0
            while elapsed < total_duration:
                clip = pool[idx % len(pool)]
                remaining = total_duration - elapsed
                segment = clip.subclip(0, min(clip.duration, remaining))
                timeline.append(segment)
                elapsed += segment.duration
                idx += 1

            video = concatenate_videoclips(timeline, method="chain")
            video = video.set_audio(audio)

            out_path = self._output_dir / f"{output_stem}.mp4"
            print(f"[assembler] encoding {output_stem} ({total_duration:.1f}s audio, {len(pool)} clips cycling)…")
            video.write_videofile(
                str(out_path),
                fps=self.FPS,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(self._output_dir / f"{output_stem}_tmp.m4a"),
                remove_temp=True,
                logger=None,
            )
            print(f"[assembler] encode complete → {out_path}")

        print(f"[assembler] uploading {out_path.name}…")
        return self._upload_video(out_path, out_path.name)

    def process_approved_voiceovers(self, niche_id: str) -> None:
        videos = execute_with_retry(
            self._sb.table("videos")
            .select("*, scripts(long_form_text, short_text)")
            .eq("niche_id", niche_id)
            .eq("gate4_state", "approved")
            .eq("gate5_state", "approved")
            .eq("status", "pending")
        ).data
        for video in videos:
            try:
                scripts_data = video.get("scripts")
                if not scripts_data:
                    print(f"[assembler] video {video['id']} has no linked script, skip")
                    continue
                script_text = (
                    scripts_data["long_form_text"]
                    if video["video_type"] == "long"
                    else scripts_data["short_text"]
                )
                stem = f"{video['id'][:8]}_{video['video_type']}_assembled"
                out_path = self.assemble(
                    audio_path=video["audio_path"],
                    srt_path=video["srt_path"],
                    script_text=script_text,
                    output_stem=stem,
                    is_short=(video["video_type"] == "short"),
                )
                execute_with_retry(
                    self._sb.table("videos").update(
                        {"video_path": out_path, "status": "processing", "gate6_state": "awaiting_review"}
                    ).eq("id", video["id"])
                )
                print(f"[assembler] video {video['id']} assembled → {out_path}")
            except Exception as exc:
                print(f"[assembler] video {video['id']} failed, will retry next run: {exc}")
