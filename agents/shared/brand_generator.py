import re
from dataclasses import dataclass
from supabase import Client
from agents.shared.anthropic_client import complete_sonnet

BRAND_PROMPT = """Generate a complete YouTube channel brand package for a faceless educational channel.

Niche: {niche_name}
Category: {category}

Return EXACTLY this format (each field on its own line, label: value):
Channel Name: [5-20 char name, memorable, niche-relevant, no generic words like "tips" or "guide"]
Tagline: [10-15 word punchy description of the channel's value]
Primary Color: [hex code, dark, good for backgrounds]
Accent Color: [hex code, bright, for text and highlights]
Font: [Google Font pairing: Heading Font / Body Font]
About: [2-sentence channel description, audience-first]
Thumbnail Layout: [one of: dark-left-title, dark-center-title, split-image-title]"""


@dataclass
class BrandPackage:
    channel_name: str
    tagline: str
    primary_color: str
    accent_color: str
    font_pairing: str
    about_section: str
    thumbnail_layout: str
    channel_id: str = ""  # filled after YouTube Brand Account creation

    def to_dict(self) -> dict:
        return {
            "channel_name": self.channel_name,
            "tagline": self.tagline,
            "primary_color": self.primary_color,
            "accent_color": self.accent_color,
            "font_pairing": self.font_pairing,
            "about_section": self.about_section,
            "thumbnail_layout": self.thumbnail_layout,
            "channel_id": self.channel_id,
        }


def _extract(text: str, label: str, default: str = "") -> str:
    pattern = re.compile(rf"^{label}:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
    m = pattern.search(text)
    return m.group(1).strip() if m else default


class BrandGenerator:
    def __init__(self, supabase: Client):
        self._sb = supabase

    def generate(self, niche_name: str, category: str) -> BrandPackage:
        raw = complete_sonnet(BRAND_PROMPT.format(niche_name=niche_name, category=category), max_tokens=400)
        return BrandPackage(
            channel_name=_extract(raw, "Channel Name", default=niche_name[:20].title()),
            tagline=_extract(raw, "Tagline", default=f"Everything about {niche_name}."),
            primary_color=_extract(raw, "Primary Color", default="#1a1a2e"),
            accent_color=_extract(raw, "Accent Color", default="#e94560"),
            font_pairing=_extract(raw, "Font", default="Roboto Bold / Open Sans"),
            about_section=_extract(raw, "About", default=f"We cover {niche_name} topics every week."),
            thumbnail_layout=_extract(raw, "Thumbnail Layout", default="dark-center-title"),
        )

    def generate_and_store(self, niche_id: str, niche_name: str, category: str) -> BrandPackage:
        package = self.generate(niche_name, category)
        self._sb.table("niches").update(
            {"brand_package": package.to_dict(), "gate1_state": "awaiting_review"}
        ).eq("id", niche_id).execute()
        return package
