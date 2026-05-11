import pytest
from unittest.mock import MagicMock, call
from PIL import Image
from agents.shared.gate_client import GateNumber
from agents.production.thumbnail_gen import ThumbnailGenerator, _build_replicate_prompt


def _mock_gen(tmp_path, size=(1280, 720)):
    fake_img = Image.new("RGB", size, (100, 100, 200))
    mock_client = MagicMock()
    mock_client.generate_image.return_value = fake_img
    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    gen._replicate = mock_client
    return gen, mock_client


def test_render_creates_file(tmp_path):
    gen, _ = _mock_gen(tmp_path)
    out = gen.render(title="I Sued My Landlord And Won", category="legal", output_stem="test_thumbnail")
    assert out.exists()
    assert out.suffix == ".jpg"
    assert out.stat().st_size > 0


def test_render_long_uses_16_9(tmp_path):
    gen, mock_client = _mock_gen(tmp_path)
    gen.render("Tax Secrets Exposed", "tax", "test_long", video_type="long")
    call_args = mock_client.generate_image.call_args
    assert call_args.kwargs.get("aspect_ratio") == "16:9" or call_args.args[1] == "16:9"


def test_render_short_uses_9_16(tmp_path):
    gen, mock_client = _mock_gen(tmp_path, size=(1080, 1920))
    gen.render("Tax Secrets Exposed", "tax", "test_short", video_type="short")
    call_args = mock_client.generate_image.call_args
    assert call_args.kwargs.get("aspect_ratio") == "9:16" or call_args.args[1] == "9:16"


def test_render_raises_when_replicate_fails(tmp_path):
    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    mock_client = MagicMock()
    mock_client.generate_image.side_effect = RuntimeError("API error")
    gen._replicate = mock_client
    with pytest.raises(RuntimeError):
        gen.render("Tax Secrets Exposed", "tax", "test_fail", video_type="long")


def test_render_raises_without_replicate(tmp_path):
    gen = ThumbnailGenerator(output_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="REPLICATE_API_KEY"):
        gen.render("Tax Secrets Exposed", "tax", "test_no_key")


def test_build_replicate_prompt_includes_title_and_orientation():
    long_prompt = _build_replicate_prompt("Tax Secrets", "tax", is_short=False)
    short_prompt = _build_replicate_prompt("Tax Secrets", "tax", is_short=True)
    assert "Tax Secrets" in long_prompt
    assert "16:9" in long_prompt
    assert "Tax Secrets" in short_prompt
    assert "9:16" in short_prompt


def test_process_approved_scripts_skips_render_for_shorts(tmp_path):
    """Shorts auto-approve gate5 without calling Replicate."""
    gen, mock_replicate = _mock_gen(tmp_path)
    mock_gate = MagicMock()
    mock_sb = MagicMock()
    gen._gate = mock_gate
    gen._sb = mock_sb

    short_id = "aaaa-bbbb-cccc-dddd"
    script_row = {
        "id": "script-1234-5678-abcd",
        "youtube_title": "Why Your Landlord Can't Do That",
        "niches": {"category": "legal"},
        "videos": [{"id": short_id, "video_type": "short", "gate5_state": "awaiting_review"}],
    }
    (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
        .data
    ) = [script_row]

    gen.process_approved_scripts("niche-xyz")

    mock_replicate.generate_image.assert_not_called()
    mock_gate.advance_or_pause.assert_called_once_with(
        gate=GateNumber.THUMBNAIL,
        niche_id="niche-xyz",
        table="videos",
        item_id=short_id,
        gate_column="gate5_state",
        auto_state="approved",
        review_state="awaiting_review",
    )
