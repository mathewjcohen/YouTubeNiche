import pytest
from unittest.mock import patch, MagicMock
from agents.shared.brand_generator import BrandGenerator, BrandPackage


@pytest.fixture
def gen():
    mock_sb = MagicMock()
    return BrandGenerator(supabase=mock_sb)


def test_generate_returns_brand_package(gen):
    with patch("agents.shared.brand_generator.complete_sonnet") as mock:
        mock.return_value = """Channel Name: LegallyYours
Tagline: Know your rights. Use them.
Primary Color: #1E3A5F
Accent Color: #F5C842
Font: Montserrat Bold / Open Sans
About: LegallyYours covers the legal situations real people face every day.
Thumbnail Layout: dark-left-title"""
        result = gen.generate(niche_name="know your legal rights", category="legal")
    assert isinstance(result, BrandPackage)
    assert result.channel_name == "LegallyYours"
    assert result.tagline == "Know your rights. Use them."
    assert result.primary_color == "#1E3A5F"


def test_generate_handles_malformed_response(gen):
    with patch("agents.shared.brand_generator.complete_sonnet") as mock:
        mock.return_value = "Some totally unexpected response format"
        result = gen.generate(niche_name="some niche", category="career")
    # Should not raise; defaults should fill in
    assert isinstance(result, BrandPackage)
    assert result.channel_name != ""
