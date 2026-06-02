import json
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
import botocore.exceptions
import requests
from moviepy.editor import (
    VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, ColorClip
)
from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry
from agents.shared.tlog import tlog
from agents.shared.anthropic_client import complete


BROLL_PATTERN = re.compile(r"\[B-ROLL:\s*(.+?)\]", re.IGNORECASE)
CLIPS_PER_TAG = 3         # clips fetched per B-ROLL tag
LONG_MAX_CLIP_SEC = 8     # long-form: moderate pacing
SHORT_MAX_CLIP_SEC = 4    # shorts: fast cuts aid retention
VIDEOS_PER_RUN = 1        # long+short pairs to assemble per pipeline run

BROLL_FALLBACK_TAGS = ["stressed person documents", "couple discussing finances", "person at laptop worried"]

BROLL_TAGS_PROMPT_LONG = """Return exactly 8 Pexels video search terms for a YouTube video with this script.
Terms must feature real people in emotionally relatable situations matching the story's tone.
Good examples: "stressed person reading letter", "couple arguing over bills", "businesswoman shocked phone call", "man signing legal documents".
Bad examples: "nature background", "abstract", "city skyline" — no scenery, no objects without people.
Return ONLY a JSON array of 8 strings. No explanation, no markdown, just the array.

Script:
{script_text}"""

BROLL_TAGS_PROMPT_SHORT = """Return exactly 6 Pexels video search terms for a YouTube Short with this script.
Terms must feature people with visible facial expressions — close-up reactions, emotional moments, expressive faces.
This is critical: YouTube auto-selects thumbnails from video frames, so clips with faces produce better thumbnails.
Good examples: "shocked woman reading document", "man frustrated at computer", "person covering mouth in disbelief".
Bad examples: "nature background", "city timelapse", "office building" — no scenery or faceless clips.
Return ONLY a JSON array of 6 strings. No explanation, no markdown, just the array.

Script:
{script_text}"""


def _generate_broll_tags(script_text: str, is_short: bool) -> List[str]:
    prompt_template = BROLL_TAGS_PROMPT_SHORT if is_short else BROLL_TAGS_PROMPT_LONG
    prompt = prompt_template.format(script_text=script_text[:3000])
    try:
        raw = complete(prompt, max_tokens=256)
        tags = json.loads(raw.strip())
        if isinstance(tags, list) and len(tags) > 0:
            return [str(t) for t in tags]
    except Exception:
        pass
    return BROLL_FALLBACK_TAGS


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
                if ".amazonaws.com/" in audio_path:
                    from agents.shared.config_loader import get_env
                    s3_key = audio_path.split(".amazonaws.com/", 1)[1]
                    boto3.client("s3", region_name=get_env("REMOTION_REGION")).download_file(
                        get_env("AWS_S3_BUCKET"), s3_key, str(local_audio)
                    )
                else:
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
                        max_clip = SHORT_MAX_CLIP_SEC if is_short else LONG_MAX_CLIP_SEC
                        cap = min(raw.duration, max_clip)
                        sub = raw.subclip(0, cap)
                        # Cover-crop: scale to fill target frame, then center-crop
                        scale = max(target_w / sub.w, target_h / sub.h)
                        scaled = sub.resize(scale)
                        cropped = scaled.crop(x_center=scaled.w / 2, y_center=scaled.h / 2, width=target_w, height=target_h)
                        pool.append(cropped)
                    except Exception as exc:
                        tlog(f"[assembler] clip {i}_{j} download failed: {exc}")

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
            tlog(f"[assembler] encoding {output_stem} ({total_duration:.1f}s audio, {len(pool)} clips cycling)…")
            video.write_videofile(
                str(out_path),
                fps=self.FPS,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(self._output_dir / f"{output_stem}_tmp.m4a"),
                remove_temp=True,
                logger=None,
            )
            tlog(f"[assembler] encode complete → {out_path}")

        tlog(f"[assembler] uploading {out_path.name}…")
        return self._upload_video(out_path, out_path.name)

    def _delete_voiceover_assets(self, video: dict) -> None:
        from agents.shared.config_loader import get_env
        for field in ("audio_path", "srt_path"):
            url = video.get(field)
            if not url or ".amazonaws.com/" not in url:
                continue
            try:
                key = url.split(".amazonaws.com/", 1)[1]
                bucket = get_env("AWS_S3_BUCKET")
                region = get_env("REMOTION_REGION")
                boto3.client("s3", region_name=region).delete_object(Bucket=bucket, Key=key)
                tlog(f"[assembler] deleted s3://{bucket}/{key}")
            except Exception as exc:
                tlog(f"[assembler] s3 audio cleanup failed (non-fatal): {exc}")

    def _query_pending_videos(self, niche_id: str, video_type: str) -> list:
        return execute_with_retry(
            self._sb.table("videos")
            .select("*, scripts(long_form_text, short_text)")
            .eq("niche_id", niche_id)
            .eq("gate4_state", "approved")
            .eq("gate5_state", "approved")
            .eq("status", "pending")
            .eq("video_type", video_type)
            .limit(VIDEOS_PER_RUN)
        ).data

    def process_approved_voiceovers(self, niche_id: str) -> None:
        videos = self._query_pending_videos(niche_id, "long") + self._query_pending_videos(niche_id, "short")
        for video in videos:
            try:
                scripts_data = video.get("scripts")
                if not scripts_data:
                    tlog(f"[assembler] video {video['id']} has no linked script, skip")
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
                gate6_enabled = self._gate.gate_enabled(GateNumber.FINAL_VIDEO, video["niche_id"])
                gate6_state = "awaiting_review" if gate6_enabled else "approved"
                new_status = "approved" if not gate6_enabled else "processing"
                execute_with_retry(
                    self._sb.table("videos").update({
                        "video_path": out_path,
                        "status": new_status,
                        "gate6_state": gate6_state,
                    }).eq("id", video["id"])
                )
                tlog(f"[assembler] video {video['id']} assembled → {out_path} (gate6={gate6_state})")
                self._delete_voiceover_assets(video)
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey"):
                    tlog(f"[assembler] video {video['id']} audio permanently missing (S3 404) — marking assembly_failed")
                    execute_with_retry(self._sb.table("videos").delete().eq("id", video["id"]))
                    execute_with_retry(self._sb.table("scripts").update({"status": "assembly_failed"}).eq("id", video["script_id"]))
                else:
                    tlog(f"[assembler] video {video['id']} S3 error, will retry next run: {exc}")
            except Exception as exc:
                tlog(f"[assembler] video {video['id']} failed, will retry next run: {exc}")
