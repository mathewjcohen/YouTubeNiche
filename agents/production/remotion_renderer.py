import math
import random
import re
import time
import tempfile
from pathlib import Path

import boto3
import requests
from botocore.config import Config as BotocoreConfig
from supabase import Client

from agents.shared.gate_client import GateClient
from agents.shared.db_retry import execute_with_retry
from agents.shared.config_loader import get_env

FPS = 24
BROLL_PATTERN = re.compile(r"\[B-ROLL:\s*(.+?)\]", re.IGNORECASE)
POLL_INTERVAL = 15   # seconds between progress checks
RENDER_TIMEOUT = 1200  # 20 minutes max wait per video


def _pexels_search(query: str, api_key: str) -> tuple[str, float] | None:
    """Return (video_url, duration_sec) for the best Pexels result, or None."""
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 1, "orientation": "landscape"},
        timeout=10,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        return None
    video = videos[0]
    duration = float(video.get("duration", 15))
    files = video.get("video_files", [])
    hd = [f for f in files if f.get("quality") == "hd" and f.get("width", 0) >= 1280]
    chosen = hd[0] if hd else (files[0] if files else None)
    if not chosen:
        return None
    return chosen["link"], duration


def _download_and_upload_broll(
    supabase: Client,
    pexels_url: str,
    pexels_headers: dict,
    storage_key: str,
) -> str:
    """Download a Pexels clip and upload to Supabase broll bucket. Returns public URL."""
    resp = requests.get(pexels_url, headers=pexels_headers, stream=True, timeout=60)
    resp.raise_for_status()
    data = resp.content
    try:
        supabase.storage.from_("broll").upload(
            storage_key, data, {"content-type": "video/mp4", "upsert": "true"}
        )
    except Exception:
        pass  # file may already exist from a previous run
    return supabase.storage.from_("broll").get_public_url(storage_key)


def _audio_duration_sec(audio_url: str) -> float:
    """Download audio and return duration in seconds using mutagen."""
    import mutagen.mp3
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        resp = requests.get(audio_url, timeout=60)
        resp.raise_for_status()
        f.write(resp.content)
        tmp_path = f.name
    audio = mutagen.mp3.MP3(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    return audio.info.length


_BOTO_CONFIG = BotocoreConfig(
    read_timeout=600,    # 10 min — accommodates Lambda cold start + render orchestration
    connect_timeout=30,
    retries={"max_attempts": 1},
)

# Patch RemotionClient at class level so all instances use the extended timeout.
try:
    from remotion_lambda import RemotionClient as _RemotionClient
    _RemotionClient._create_lambda_client = lambda self: boto3.client(
        "lambda", region_name=self.region, config=_BOTO_CONFIG
    )
except ImportError:
    pass


class RemotionRenderer:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def _upload_video(self, file_path: Path, object_name: str) -> str:
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

    def render(self, audio_url: str, script_text: str, output_stem: str) -> str:
        from remotion_lambda import RenderMediaParams

        pexels_key = get_env("PEXELS_API_KEY")
        pexels_headers = {"Authorization": pexels_key}

        # 1. Get audio duration
        duration_sec = _audio_duration_sec(audio_url)

        # 2. Extract b-roll scene tags and fetch clips
        tags = BROLL_PATTERN.findall(script_text) or ["nature background", "city timelapse", "office work"]
        scenes: list[dict] = []
        per_scene_sec = duration_sec / len(tags)
        per_scene_frames = int(per_scene_sec * FPS)

        for i, tag in enumerate(tags):
            result = _pexels_search(tag, pexels_key)
            if not result:
                continue
            pexels_url, _clip_duration = result
            storage_key = f"broll_{output_stem}_{i}.mp4"
            public_url = _download_and_upload_broll(
                self._sb, pexels_url, pexels_headers, storage_key
            )
            scenes.append({"url": public_url, "durationFrames": per_scene_frames})

        if not scenes:
            raise RuntimeError("No b-roll clips available — cannot render video")

        random.shuffle(scenes)

        # Adjust last scene so total frames matches audio duration exactly
        total_frames = int(duration_sec * FPS)
        allocated = per_scene_frames * len(scenes)
        scenes[-1]["durationFrames"] += total_frames - allocated

        # 3. Trigger Remotion Lambda render
        remotion_region = get_env("REMOTION_REGION")
        remotion_function_name = get_env("REMOTION_FUNCTION_NAME")
        remotion_serve_url = get_env("REMOTION_SERVE_URL")

        # Pre-flight: show account concurrency limit and deployed function names.
        try:
            lambda_client = boto3.client("lambda", region_name=remotion_region, config=_BOTO_CONFIG)
            account_settings = lambda_client.get_account_settings()
            concurrency_limit = account_settings["AccountLimit"]["ConcurrentExecutions"]
            print(f"[remotion] Lambda account concurrency limit in {remotion_region}: {concurrency_limit}")
            paginator = lambda_client.get_paginator("list_functions")
            deployed = [
                fn["FunctionName"]
                for page in paginator.paginate()
                for fn in page["Functions"]
                if fn["FunctionName"].startswith("remotion")
            ]
            print(f"[remotion] deployed remotion functions: {deployed}")
            print(f"[remotion] REMOTION_FUNCTION_NAME = {remotion_function_name!r}")
        except Exception as _e:
            print(f"[remotion] pre-flight check failed (non-fatal): {_e}")

        from remotion_lambda import RemotionClient
        client = RemotionClient(
            region=remotion_region,
            serve_url=remotion_serve_url,
            function_name=remotion_function_name,
        )

        render_response = client.render_media_on_lambda(
            render_params=RenderMediaParams(
                composition="VideoComposition",
                input_props={
                    "audioUrl": audio_url,
                    "audioDurationSec": duration_sec,
                    "scenes": scenes,
                },
                codec="h264",
                image_format="jpeg",
                # 1 orchestrator + ≤8 renderers = 9 total, within the 10-execution account limit.
                # Raise MAX_RENDERERS once the quota increase to 3000 is approved.
                frames_per_lambda=max(1, math.ceil(total_frames / 8)),
                concurrency_per_lambda=1,
            )
        )

        print(f"[remotion] render {render_response.render_id} started")

        # 4. Poll until done
        deadline = time.time() + RENDER_TIMEOUT
        while time.time() < deadline:
            progress = client.get_render_progress(
                render_id=render_response.render_id,
                bucket_name=render_response.bucket_name,
                log_level="info",
            )
            if progress.fatalErrorEncountered:
                raise RuntimeError(f"Remotion render failed: {progress.errors}")
            if progress.done:
                break
            pct = int(progress.overallProgress * 100)
            print(f"[remotion] render {render_response.render_id} — {pct}%")
            time.sleep(POLL_INTERVAL)
        else:
            raise TimeoutError(f"Remotion render timed out after {RENDER_TIMEOUT}s")

        # 5. Download output and store in Supabase videos bucket via TUS
        output_url = progress.outputFile
        print(f"[remotion] render complete → {output_url}")
        storage_key = f"{output_stem}.mp4"
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            out_resp = requests.get(output_url, stream=True, timeout=300)
            out_resp.raise_for_status()
            for chunk in out_resp.iter_content(chunk_size=1 << 20):
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        try:
            return self._upload_video(tmp_path, storage_key)
        finally:
            tmp_path.unlink(missing_ok=True)

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
                    print(f"[remotion] video {video['id']} has no linked script, skip")
                    continue
                script_text = (
                    scripts_data["long_form_text"]
                    if video["video_type"] == "long"
                    else scripts_data["short_text"]
                )
                stem = f"{video['id'][:8]}_{video['video_type']}_remotion"
                out_url = self.render(
                    audio_url=video["audio_path"],
                    script_text=script_text,
                    output_stem=stem,
                )
                execute_with_retry(
                    self._sb.table("videos").update(
                        {"video_path": out_url, "status": "pending", "gate6_state": "awaiting_review"}
                    ).eq("id", video["id"])
                )
                print(f"[remotion] video {video['id']} assembled → {out_url}")
            except Exception as exc:
                import traceback
                print(f"[remotion] video {video['id']} failed ({type(exc).__name__}), will retry next run: {exc}")
                print(f"[remotion] traceback:\n{traceback.format_exc()}")
