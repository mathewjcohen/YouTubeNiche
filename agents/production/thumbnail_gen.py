from pathlib import Path
from typing import Optional

from PIL import Image
from supabase import Client

from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.config_loader import get_env
from agents.production.replicate_client import ReplicateClient

THUMB_W, THUMB_H = 1280, 720          # long-form 16:9
SHORT_W, SHORT_H = 1080, 1920         # shorts 9:16

_CATEGORY_STYLE: dict[str, str] = {
    "legal": "courtroom and law books background, gold accents",
    "insurance": "professional office with documents background, green accents",
    "tax": "tax forms and IRS documents background, red and orange warning accents",
    "personal_finance": "financial charts and money background, blue accents",
    "real_estate": "house exterior and property listing background, orange accents",
    "career": "professional office and business meeting background, purple accents",
    "ai_tech": "futuristic technology and glowing circuits background, cyan accents",
    "health": "medical setting and doctor background, teal accents",
}


def _fit_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(img.width * h / img.height)
    else:
        new_w = w
        new_h = int(img.height * w / img.width)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _build_replicate_prompt(title: str, category: str, is_short: bool) -> str:
    style = _CATEGORY_STYLE.get(category, "dramatic background, bright accents")
    orientation = "vertical 9:16" if is_short else "horizontal 16:9"
    return (
        f"YouTube thumbnail, {orientation}, bold white text reading '{title}', "
        f"shocked or alarmed person reacting, {style}, "
        f"cinematic dramatic lighting, high contrast, scroll-stopping, photorealistic"
    )


class ThumbnailGenerator:
    def __init__(
        self,
        supabase: Optional[Client] = None,
        gate_client: Optional[GateClient] = None,
        output_dir: str = "output/thumbnails",
        replicate_api_key: Optional[str] = None,
    ):
        self._sb = supabase
        self._gate = gate_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._replicate = ReplicateClient(replicate_api_key) if replicate_api_key else None

    def render(
        self,
        title: str,
        category: str,
        output_stem: str,
        video_type: str = "long",
    ) -> Path:
        if not self._replicate:
            raise RuntimeError("REPLICATE_API_KEY is required for thumbnail generation")
        is_short = video_type == "short"
        w, h = (SHORT_W, SHORT_H) if is_short else (THUMB_W, THUMB_H)
        prompt = _build_replicate_prompt(title, category, is_short)
        aspect_ratio = "9:16" if is_short else "16:9"
        img = self._replicate.generate_image(prompt, aspect_ratio)
        img = _fit_crop(img, w, h)
        out_path = self._output_dir / f"{output_stem}.jpg"
        img.save(str(out_path), "JPEG", quality=92)
        return out_path

    def _upload(self, local_path: Path) -> str:
        import boto3
        bucket = get_env("AWS_S3_BUCKET")
        region = get_env("REMOTION_REGION")
        key = f"thumbnails/{local_path.name}"
        boto3.client("s3", region_name=region).upload_file(
            str(local_path),
            bucket,
            key,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    def process_approved_scripts(self, niche_id: str) -> None:
        if not self._sb or not self._gate:
            raise RuntimeError("supabase and gate_client required for pipeline use")
        # Inner join: only scripts that have at least one video row
        scripts = (
            self._sb.table("scripts")
            .select("*, niches(category), videos!inner(id, video_type, gate5_state)")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .execute()
            .data
        )
        print(f"[thumbnail] {len(scripts)} script(s) with video rows for niche {niche_id}")
        for script in scripts:
            category = script["niches"]["category"]
            pending_videos = [v for v in script.get("videos", []) if v.get("gate5_state") != "approved"]
            if not pending_videos:
                continue
            for video in pending_videos:
                video_type = video["video_type"]
                stem = f"{script['id'][:8]}_{video_type}_thumb"

                if video_type == "short":
                    # YouTube does not display custom thumbnails for Shorts on
                    # ineligible channels; skip generation and auto-approve gate5.
                    self._gate.advance_or_pause(
                        gate=GateNumber.THUMBNAIL,
                        niche_id=niche_id,
                        table="videos",
                        item_id=video["id"],
                        gate_column="gate5_state",
                        auto_state="approved",
                        review_state="awaiting_review",
                    )
                    print(f"[thumbnail] short {video['id'][:8]} — gate5 auto-approved, no thumbnail generated")
                    continue

                try:
                    out = self.render(
                        title=script["youtube_title"],
                        category=category,
                        output_stem=stem,
                        video_type=video_type,
                    )
                except Exception as exc:
                    print(f"[thumbnail] render failed for {stem}: {exc}")
                    continue
                try:
                    thumb_url = self._upload(out)
                    print(f"[thumbnail] uploaded → {thumb_url}")
                    self._sb.table("videos").update(
                        {"thumbnail_path": thumb_url}
                    ).eq("id", video["id"]).execute()
                    self._gate.advance_or_pause(
                        gate=GateNumber.THUMBNAIL,
                        niche_id=niche_id,
                        table="videos",
                        item_id=video["id"],
                        gate_column="gate5_state",
                        auto_state="approved",
                        review_state="awaiting_review",
                    )
                    print(f"[thumbnail] updated video row for {stem}")
                except Exception as exc:
                    print(f"[thumbnail] upload/db update failed for {stem}: {exc}")
