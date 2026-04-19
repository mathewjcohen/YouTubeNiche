from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import textwrap
from PIL import Image, ImageDraw, ImageFont
from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber


CATEGORY_COLORS = {
    "legal": {"bg": (20, 30, 60), "accent": (255, 200, 50), "text": (255, 255, 255)},
    "insurance": {"bg": (10, 50, 30), "accent": (100, 220, 130), "text": (255, 255, 255)},
    "tax": {"bg": (60, 20, 20), "accent": (255, 100, 80), "text": (255, 255, 255)},
    "personal_finance": {"bg": (20, 20, 60), "accent": (100, 180, 255), "text": (255, 255, 255)},
    "real_estate": {"bg": (40, 25, 10), "accent": (255, 170, 50), "text": (255, 255, 255)},
    "career": {"bg": (10, 10, 40), "accent": (150, 120, 255), "text": (255, 255, 255)},
    "ai_tech": {"bg": (5, 15, 40), "accent": (0, 210, 210), "text": (255, 255, 255)},
    "health": {"bg": (20, 50, 50), "accent": (80, 220, 180), "text": (255, 255, 255)},
}

DEFAULT_COLORS = {"bg": (20, 20, 20), "accent": (255, 255, 100), "text": (255, 255, 255)}

THUMB_W, THUMB_H = 1280, 720


@dataclass
class ThumbnailTemplate:
    category: str
    bg_color: tuple
    accent_color: tuple
    text_color: tuple


class ThumbnailGenerator:
    def __init__(
        self,
        supabase: Optional[Client] = None,
        gate_client: Optional[GateClient] = None,
        output_dir: str = "output/thumbnails",
    ):
        self._sb = supabase
        self._gate = gate_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, title: str, category: str, output_stem: str) -> Path:
        colors = CATEGORY_COLORS.get(category, DEFAULT_COLORS)
        img = Image.new("RGB", (THUMB_W, THUMB_H), color=colors["bg"])
        draw = ImageDraw.Draw(img)

        # Accent bar at bottom
        bar_height = 80
        draw.rectangle(
            [(0, THUMB_H - bar_height), (THUMB_W, THUMB_H)],
            fill=colors["accent"],
        )

        # Title text — wrap at ~22 chars per line for large font
        _BOLD_CANDIDATES = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",          # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Ubuntu
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        _REGULAR_CANDIDATES = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",               # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",            # Ubuntu
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

        def _load_font(candidates: list, size: int):
            for path in candidates:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
            return ImageFont.load_default()

        font_large = _load_font(_BOLD_CANDIDATES, 90)
        font_small = _load_font(_REGULAR_CANDIDATES, 42)

        wrapped = textwrap.wrap(title, width=22)
        line_height = 110
        total_text_height = len(wrapped) * line_height
        y_start = (THUMB_H - bar_height - total_text_height) // 2

        for i, line in enumerate(wrapped):
            bbox = draw.textbbox((0, 0), line, font=font_large)
            text_w = bbox[2] - bbox[0]
            x = (THUMB_W - text_w) // 2
            y = y_start + i * line_height
            # Shadow
            draw.text((x + 4, y + 4), line, font=font_large, fill=(0, 0, 0, 180))
            draw.text((x, y), line, font=font_large, fill=colors["text"])

        # Category label in accent bar
        cat_label = category.replace("_", " ").upper()
        bbox = draw.textbbox((0, 0), cat_label, font=font_small)
        label_w = bbox[2] - bbox[0]
        draw.text(
            ((THUMB_W - label_w) // 2, THUMB_H - bar_height + 18),
            cat_label,
            font=font_small,
            fill=colors["bg"],
        )

        out_path = self._output_dir / f"{output_stem}.jpg"
        img.save(str(out_path), "JPEG", quality=95)
        return out_path

    def _upload(self, local_path: Path) -> str:
        self._sb.storage.from_("thumbnails").upload(
            local_path.name,
            local_path.read_bytes(),
            {"content-type": "image/jpeg", "upsert": "true"},
        )
        return self._sb.storage.from_("thumbnails").get_public_url(local_path.name)

    def process_approved_scripts(self, niche_id: str) -> None:
        if not self._sb or not self._gate:
            raise RuntimeError("supabase and gate_client required for pipeline use")
        scripts = (
            self._sb.table("scripts")
            .select("*, niches(category)")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .execute()
            .data
        )
        for script in scripts:
            category = script["niches"]["category"]
            for video_type in ("long", "short"):
                stem = f"{script['id'][:8]}_{video_type}_thumb"
                out = self.render(
                    title=script["youtube_title"],
                    category=category,
                    output_stem=stem,
                )
                videos = (
                    self._sb.table("videos")
                    .select("id")
                    .eq("script_id", script["id"])
                    .eq("video_type", video_type)
                    .execute()
                    .data
                )
                thumb_url = self._upload(out)
                for video in videos:
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
