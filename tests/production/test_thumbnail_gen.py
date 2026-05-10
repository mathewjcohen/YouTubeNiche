import pytest
from agents.production.thumbnail_gen import ThumbnailGenerator


def test_template_render_creates_file(tmp_path):
    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    out = gen.render(
        title="I Sued My Landlord And Won",
        category="legal",
        output_stem="test_thumbnail",
    )
    assert out.exists()
    assert out.suffix == ".jpg"
    assert out.stat().st_size > 0


def test_title_wraps_long_text(tmp_path):
    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    # Should not raise even with a very long title
    out = gen.render(
        title="This Is An Extremely Long Title That Should Wrap Across Multiple Lines",
        category="personal_finance",
        output_stem="long_title_test",
    )
    assert out.exists()


def test_render_uses_replicate_when_configured(tmp_path):
    """When ReplicateClient is configured, render() returns a file without touching Pexels."""
    from unittest.mock import MagicMock
    from PIL import Image

    fake_img = Image.new("RGB", (1280, 720), (100, 100, 200))
    mock_client = MagicMock()
    mock_client.generate_image.return_value = fake_img

    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    gen._replicate = mock_client

    out = gen.render("Tax Secrets Exposed", "tax", "test_replicate_long", video_type="long")

    assert out.exists()
    mock_client.generate_image.assert_called_once()
    call_args = mock_client.generate_image.call_args
    assert call_args.kwargs.get("aspect_ratio") == "16:9" or call_args.args[1] == "16:9"


def test_render_replicate_short_uses_9_16(tmp_path):
    """Shorts pass aspect_ratio='9:16' to Replicate."""
    from unittest.mock import MagicMock
    from PIL import Image

    fake_img = Image.new("RGB", (1080, 1920), (100, 100, 200))
    mock_client = MagicMock()
    mock_client.generate_image.return_value = fake_img

    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    gen._replicate = mock_client

    gen.render("Tax Secrets Exposed", "tax", "test_replicate_short", video_type="short")

    call_args = mock_client.generate_image.call_args
    assert call_args.kwargs.get("aspect_ratio") == "9:16" or call_args.args[1] == "9:16"


def test_render_falls_back_to_pillow_when_replicate_fails(tmp_path):
    """If Replicate raises, render() falls back to the Pillow solid-color path."""
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_client.generate_image.side_effect = RuntimeError("API error")

    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    gen._replicate = mock_client

    # No pexels key → Pillow solid-color fallback
    out = gen.render("Tax Secrets Exposed", "tax", "test_fallback", video_type="long")

    assert out.exists()


def test_build_replicate_prompt_includes_title_and_orientation():
    """_build_replicate_prompt embeds the title and correct orientation."""
    from agents.production.thumbnail_gen import _build_replicate_prompt

    long_prompt = _build_replicate_prompt("Tax Secrets", "tax", is_short=False)
    short_prompt = _build_replicate_prompt("Tax Secrets", "tax", is_short=True)

    assert "Tax Secrets" in long_prompt
    assert "16:9" in long_prompt
    assert "Tax Secrets" in short_prompt
    assert "9:16" in short_prompt
