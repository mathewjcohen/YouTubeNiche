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
