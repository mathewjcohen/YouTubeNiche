import io
import pytest
import requests
from unittest.mock import Mock, patch
from PIL import Image
from agents.production.replicate_client import ReplicateClient


def _mock_image_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, "JPEG")
    buf.seek(0)
    return buf.read()


def _mock_submit_response():
    m = Mock()
    m.json.return_value = {"id": "job-abc", "status": "starting"}
    return m


def _mock_poll_succeeded():
    m = Mock()
    m.json.return_value = {
        "id": "job-abc",
        "status": "succeeded",
        "output": ["https://cdn.replicate.delivery/img.webp"],
    }
    return m


def _mock_download_response():
    m = Mock()
    m.content = _mock_image_bytes()
    m.__enter__ = Mock(return_value=m)
    m.__exit__ = Mock(return_value=False)
    return m


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_generate_image_returns_pil_image(mock_sleep, mock_post, mock_get):
    """Happy path: submit → poll once (succeeded) → download returns PIL Image."""
    mock_post.return_value = _mock_submit_response()
    mock_get.side_effect = [_mock_poll_succeeded(), _mock_download_response()]

    client = ReplicateClient(api_key="test-replicate-key")
    result = client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (1, 1)


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_generate_image_post_body(mock_sleep, mock_post, mock_get):
    """POST body nests fields under 'input'; aspect_ratio passed directly."""
    mock_post.return_value = _mock_submit_response()
    mock_get.side_effect = [_mock_poll_succeeded(), _mock_download_response()]

    client = ReplicateClient(api_key="test-replicate-key")
    client.generate_image(prompt="test prompt", aspect_ratio="9:16")

    mock_post.assert_called_once()
    body = mock_post.call_args[1]["json"]
    inp = body["input"]
    assert inp["prompt"] == "test prompt"
    assert inp["aspect_ratio"] == "9:16"
    assert inp["size"] == "2K"
    assert inp["output_format"] == "jpeg"
    assert "version" not in body


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_generate_image_raises_on_api_failure(mock_sleep, mock_post, mock_get):
    """Poll returns status='failed' → raises RuntimeError."""
    mock_post.return_value = _mock_submit_response()
    failed_poll = Mock()
    failed_poll.json.return_value = {"id": "job-abc", "status": "failed"}
    mock_get.side_effect = [failed_poll]

    client = ReplicateClient(api_key="test-replicate-key")
    with pytest.raises(RuntimeError, match="Replicate job job-abc ended with status: failed"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_generate_image_raises_on_timeout(mock_sleep, mock_post, mock_get):
    """Poll always returns status='processing' for _MAX_POLLS iterations → TimeoutError."""
    mock_post.return_value = _mock_submit_response()
    in_progress = Mock()
    in_progress.json.return_value = {"id": "job-abc", "status": "processing"}
    mock_get.side_effect = [in_progress] * 24

    client = ReplicateClient(api_key="test-replicate-key")
    with pytest.raises(TimeoutError, match="Replicate job job-abc timed out"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_sleep.call_count == 24


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_auth_header_sent(mock_sleep, mock_post, mock_get):
    """Auth uses 'Authorization: Token <key>' header — no hf-api-key."""
    mock_post.return_value = _mock_submit_response()
    mock_get.side_effect = [_mock_poll_succeeded(), _mock_download_response()]

    client = ReplicateClient(api_key="r8_abc123")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers["Authorization"] == "Token r8_abc123"
    assert "hf-api-key" not in call_headers


@patch("agents.production.replicate_client.requests.get")
@patch("agents.production.replicate_client.requests.post")
@patch("agents.production.replicate_client.time.sleep")
def test_submit_uses_correct_endpoint(mock_sleep, mock_post, mock_get):
    """POST is sent to /v1/models/bytedance/seedream-5-lite/predictions."""
    mock_post.return_value = _mock_submit_response()
    mock_get.side_effect = [_mock_poll_succeeded(), _mock_download_response()]

    client = ReplicateClient(api_key="test-replicate-key")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_post.call_args[0][0] == "https://api.replicate.com/v1/models/bytedance/seedream-5-lite/predictions"


def test_empty_api_key_raises():
    with pytest.raises(ValueError, match="REPLICATE_API_KEY cannot be empty"):
        ReplicateClient(api_key="")
