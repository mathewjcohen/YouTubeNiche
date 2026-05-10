import io
import pytest
import requests
from unittest.mock import Mock, patch
from PIL import Image
from agents.production.higgsfield_client import HiggsfileClient


def _mock_image_bytes():
    """Generate a minimal 1x1 red JPEG for testing."""
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, "JPEG")
    buf.seek(0)
    return buf.read()


def _mock_styles_response():
    m = Mock()
    m.json.return_value = [{"id": "style-uuid-123", "name": "Default", "preview_url": "https://example.com/preview.jpg"}]
    return m


def _mock_poll_completed():
    m = Mock()
    m.json.return_value = {
        "status": "completed",
        "request_id": "job-abc",
        "results": {"rawUrl": "https://cdn.higgsfield.ai/img.jpg"},
    }
    return m


def _mock_download_response():
    m = Mock()
    m.content = _mock_image_bytes()
    m.__enter__ = Mock(return_value=m)
    m.__exit__ = Mock(return_value=False)
    return m


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_returns_pil_image(mock_sleep, mock_post, mock_get):
    """Happy path: fetch styles → submit → poll once (completed) → download returns PIL Image."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    mock_get.side_effect = [_mock_styles_response(), _mock_poll_completed(), _mock_download_response()]

    client = HiggsfileClient(api_key="test-id:test-secret")
    result = client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (1, 1)


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_post_body(mock_sleep, mock_post, mock_get):
    """POST body nests fields under params; aspect_ratio maps to width_and_height; no top-level model."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    mock_get.side_effect = [_mock_styles_response(), _mock_poll_completed(), _mock_download_response()]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="9:16")

    mock_post.assert_called_once()
    body = mock_post.call_args[1]["json"]
    params = body["params"]
    assert params["quality"] == "720p"
    assert params["width_and_height"] == "1152x2048"
    assert params["prompt"] == "test prompt"
    assert params["style_id"] == "style-uuid-123"
    assert params["custom_reference_id"] is None
    assert "model" not in body


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_api_failure(mock_sleep, mock_post, mock_get):
    """Poll returns status='failed' → raises RuntimeError."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    failed_poll = Mock()
    failed_poll.json.return_value = {"status": "failed", "request_id": "job-abc"}
    mock_get.side_effect = [_mock_styles_response(), failed_poll]

    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(RuntimeError, match="Higgsfield job job-abc ended with status: failed"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_timeout(mock_sleep, mock_post, mock_get):
    """Poll always returns status='in_progress' for _MAX_POLLS iterations → raises TimeoutError."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    in_progress = Mock()
    in_progress.json.return_value = {"status": "in_progress", "request_id": "job-abc"}
    mock_get.side_effect = [_mock_styles_response()] + [in_progress] * 24

    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(TimeoutError, match="Higgsfield job job-abc timed out"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_sleep.call_count == 24


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_separate_auth_headers_sent(mock_sleep, mock_post, mock_get):
    """Auth uses separate hf-api-key and hf-secret headers — no Authorization header."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    mock_get.side_effect = [_mock_styles_response(), _mock_poll_completed(), _mock_download_response()]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers["hf-api-key"] == "test-id"
    assert call_headers["hf-secret"] == "test-secret"
    assert "Authorization" not in call_headers


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_submit_uses_correct_endpoint(mock_sleep, mock_post, mock_get):
    """POST is sent to /v1/text2image/soul."""
    mock_post.return_value.json.return_value = {"id": "job-abc", "jobs": [{"id": "inner-abc", "status": "queued"}]}
    mock_get.side_effect = [_mock_styles_response(), _mock_poll_completed(), _mock_download_response()]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_post.call_args[0][0] == "https://platform.higgsfield.ai/v1/text2image/soul"
