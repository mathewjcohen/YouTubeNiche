import io
import textwrap
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from supabase import Client

from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.config_loader import get_env

THUMB_W, THUMB_H = 1280, 720          # long-form 16:9
SHORT_W, SHORT_H = 1080, 1920         # shorts 9:16

_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
_REGULAR_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]

CATEGORY_ACCENT: dict[str, tuple] = {
    "legal":            (255, 200,  50),
    "insurance":        (100, 220, 130),
    "tax":              (255, 100,  80),
    "personal_finance": (100, 180, 255),
    "real_estate":      (255, 170,  50),
    "career":           (150, 120, 255),
    "ai_tech":          (  0, 210, 210),
    "health":           ( 80, 220, 180),
}
DEFAULT_ACCENT = (255, 255, 100)

# Pexels search queries per category when title alone isn't enough
CATEGORY_SEARCH_FALLBACK: dict[str, str] = {
    "legal":            "courtroom law",
    "insurance":        "insurance paperwork",
    "tax":              "tax documents money",
    "personal_finance": "money finance",
    "real_estate":      "house real estate",
    "career":           "business office professional",
    "ai_tech":          "technology computer",
    "health":           "hospital medical",
}


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _pexels_photo(query: str, api_key: str) -> Optional[Image.Image]:
    """Fetch a landscape photo from Pexels and return as PIL Image, or None."""
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 1, "orientation": "landscape"},
        timeout=15,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        return None
    src = photos[0]["src"]
    # "large2x" is 1880px wide — plenty for 1280x720
    img_url = src.get("large2x") or src.get("large") or src.get("original")
    img_resp = requests.get(img_url, timeout=30)
    img_resp.raise_for_status()
    return Image.open(io.BytesIO(img_resp.content)).convert("RGB")


def _fit_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize and center-crop to exactly w×h."""
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


def _apply_gradient(img: Image.Image) -> Image.Image:
    """Dark gradient over the bottom 60% for text legibility."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    grad_top = int(img.height * 0.35)
    for y in range(grad_top, img.height):
        alpha = int(200 * (y - grad_top) / (img.height - grad_top))
        draw.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


class ThumbnailGenerator:
    def __init__(
        self,
        supabase: Optional[Client] = None,
        gate_client: Optional[GateClient] = None,
        output_dir: str = "output/thumbnails",
        pexels_api_key: Optional[str] = None,
    ):
        self._sb = supabase
        self._gate = gate_client
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._pexels_key = pexels_api_key

    def render(
        self,
        title: str,
        category: str,
        output_stem: str,
        bg: Optional[Image.Image] = None,
        video_type: str = "long",
    ) -> Path:
        is_short = video_type == "short"
        w, h = (SHORT_W, SHORT_H) if is_short else (THUMB_W, THUMB_H)

        # 1. Background photo (caller may pass a pre-fetched image to avoid double-fetch)
        if bg is None and self._pexels_key:
            for query in (title, CATEGORY_SEARCH_FALLBACK.get(category, category)):
                try:
                    bg = _pexels_photo(query, self._pexels_key)
                    if bg:
                        print(f"[thumbnail] Pexels photo fetched for query: '{query}'")
                        break
                except Exception as exc:
                    print(f"[thumbnail] Pexels fetch failed for query '{query}': {type(exc).__name__}: {exc}")
        elif bg is None:
            print("[thumbnail] PEXELS_API_KEY not set — skipping photo fetch")

        if bg:
            img = _fit_crop(bg, w, h)
            img = _apply_gradient(img)
        else:
            print(f"[thumbnail] No Pexels photo for '{title}' — using solid fallback")
            img = Image.new("RGB", (w, h), (15, 15, 25))

        draw = ImageDraw.Draw(img)

        # Shorts use a larger font (taller canvas) and fewer chars per line
        font_size = 96 if is_short else 88
        wrap_width = 16 if is_short else 20
        line_h = 115 if is_short else 105
        font_large = _load_font(_BOLD_CANDIDATES, font_size)

        # 2. Wrap and draw title — centered horizontally, 12% side padding
        pad_x = int(w * 0.12)
        wrapped = textwrap.wrap(title, width=wrap_width)
        total_h = len(wrapped) * line_h
        # Shorts: center text vertically in bottom third; long: anchor near bottom
        y_start = (h * 2 // 3) - (total_h // 2) if is_short else h - 160 - total_h
        cx = w // 2

        for i, line in enumerate(wrapped):
            y = y_start + i * line_h
            draw.text((cx + 3, y + 3), line, font=font_large, fill=(0, 0, 0, 180), anchor="mt")
            draw.text((cx, y), line, font=font_large, fill=(255, 255, 255), anchor="mt")

        out_path = self._output_dir / f"{output_stem}.jpg"
        img.save(str(out_path), "JPEG", quality=92)
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
            # Fetch Pexels photo once per script; reuse for both long and short
            shared_bg: Optional[Image.Image] = None
            if self._pexels_key:
                for query in (script["youtube_title"], CATEGORY_SEARCH_FALLBACK.get(category, category)):
                    try:
                        shared_bg = _pexels_photo(query, self._pexels_key)
                        if shared_bg:
                            print(f"[thumbnail] Pexels photo fetched for query: '{query}'")
                            break
                    except Exception as exc:
                        print(f"[thumbnail] Pexels fetch failed for query '{query}': {type(exc).__name__}: {exc}")
            for video_type in ("long", "short"):
                stem = f"{script['id'][:8]}_{video_type}_thumb"
                try:
                    out = self.render(
                        title=script["youtube_title"],
                        category=category,
                        output_stem=stem,
                        bg=shared_bg,
                        video_type=video_type,
                    )
                except Exception as exc:
                    print(f"[thumbnail] render failed for {stem}: {exc}")
                    continue
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
