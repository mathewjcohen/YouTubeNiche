from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from supabase import Client

from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.config_loader import get_env
from agents.production.replicate_client import ReplicateClient
from agents.shared.tlog import tlog

THUMB_W, THUMB_H = 1280, 720          # long-form 16:9
SHORT_W, SHORT_H = 1080, 1920         # shorts 9:16

_CATEGORY_STYLE: dict[str, str] = {
    "general": "dramatic scene with a shocked or alarmed person, bold split-tone lighting, deep shadows with vivid accent color — electric blue, fiery orange, or urgent red",
}

# Bold font paths searched in order (macOS, then Ubuntu)
_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(title: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    words = title.split()
    lines: list = []
    current: list = []
    for word in words:
        test = " ".join(current + [word])
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [title]


def _overlay_text(img: Image.Image, title: str) -> Image.Image:
    """Composite title text over the bottom 1/3 of the image using Pillow."""
    w, h = img.size
    zone_top = (h * 2) // 3

    base = img.copy()
    draw = ImageDraw.Draw(base)
    pad = int(w * 0.04)
    max_w = w - 2 * pad
    zone_h = h - zone_top

    # Seed chosen_* with the smallest font so there's always a valid fallback
    _seed_font = _find_font(22)
    _seed_lines = _wrap_text(title, _seed_font, max_w, draw)
    _seed_bb = draw.textbbox((0, 0), "Ag", font=_seed_font)
    _seed_lh = _seed_bb[3] - _seed_bb[1]
    chosen_font = _seed_font
    chosen_font_size = 22
    chosen_lines = _seed_lines
    chosen_line_h = _seed_lh
    chosen_gap = 4
    chosen_total_h = _seed_lh * len(_seed_lines) + 4 * (len(_seed_lines) - 1)

    # Find the largest font where text fits in ≤3 lines within 85% of the zone.
    # chosen_* is updated on every valid iteration so lines and metrics always match.
    for font_size in range(90 if w >= 1000 else 52, 18, -4):
        font = _find_font(font_size)
        lines = _wrap_text(title, font, max_w, draw)
        if len(lines) > 3:
            continue
        sample_bb = draw.textbbox((0, 0), "Ag", font=font)
        line_h = sample_bb[3] - sample_bb[1]
        gap = max(4, font_size // 8)
        total_h = line_h * len(lines) + gap * (len(lines) - 1)
        chosen_font, chosen_font_size = font, font_size
        chosen_lines, chosen_line_h, chosen_gap, chosen_total_h = lines, line_h, gap, total_h
        if total_h <= int(zone_h * 0.85):
            break

    # Clamp y so text never drifts above the zone even if total_h > zone_h
    y = max(zone_top, zone_top + (zone_h - chosen_total_h) // 2)
    stroke_w = max(2, chosen_font_size // 18)
    for line in chosen_lines:
        bb = draw.textbbox((0, 0), line, font=chosen_font)
        x = (w - (bb[2] - bb[0])) // 2
        draw.text((x, y), line, font=chosen_font, fill=(255, 255, 255), stroke_width=stroke_w, stroke_fill=(0, 0, 0))
        y += chosen_line_h + chosen_gap

    return base


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
    style = _CATEGORY_STYLE.get(category, "dramatic background, ultra-vivid bright accents")
    orientation = "vertical 9:16" if is_short else "horizontal 16:9"
    return (
        f"YouTube thumbnail background, {orientation}, "
        f"shocked or alarmed person with wide eyes and open mouth reacting dramatically, "
        f"subject and main focal point positioned in upper two-thirds of frame, "
        f"{style}, ultra-vivid saturated colors, cinematic dramatic lighting, "
        f"high contrast, electric bold color palette, scroll-stopping visual impact, "
        f"photorealistic, no text, no words, no captions, no letters"
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
        img = _overlay_text(img, title)
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
            .select("id, youtube_title, niche_id, niches(category), videos!inner(id, video_type, gate5_state)")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .neq("status", "done")
            .execute()
            .data
        )
        tlog(f"[thumbnail] {len(scripts)} script(s) with video rows for niche {niche_id}")
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
                    tlog(f"[thumbnail] short {video['id'][:8]} — gate5 auto-approved, no thumbnail generated")
                    continue

                try:
                    out = self.render(
                        title=script["youtube_title"],
                        category=category,
                        output_stem=stem,
                        video_type=video_type,
                    )
                except Exception as exc:
                    tlog(f"[thumbnail] render failed for {stem}: {exc}")
                    continue
                try:
                    thumb_url = self._upload(out)
                    tlog(f"[thumbnail] uploaded → {thumb_url}")
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
                    tlog(f"[thumbnail] updated video row for {stem}")
                except Exception as exc:
                    tlog(f"[thumbnail] upload/db update failed for {stem}: {exc}")
