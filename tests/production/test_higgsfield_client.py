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


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_returns_pil_image(mock_sleep, mock_post, mock_get):
    """Happy path: submit → poll once (completed) → download returns PIL Image."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "completed",
            "results": {"rawUrl": "https://cdn.higgsfield.ai/img.jpg"}
        }
    }

    download_response = Mock()
    download_response.content = _mock_image_bytes()
    download_response.__enter__ = Mock(return_value=download_response)
    download_response.__exit__ = Mock(return_value=False)

    mock_get.side_effect = [poll_response, download_response]

    client = HiggsfileClient(api_key="test-id:test-secret")
    result = client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (1, 1)


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_post_body(mock_sleep, mock_post, mock_get):
    """POST body contains prompt, aspect_ratio, and resolution — no model field."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "completed",
            "results": {"rawUrl": "https://cdn.higgsfield.ai/img.jpg"}
        }
    }

    download_response = Mock()
    download_response.content = _mock_image_bytes()
    download_response.__enter__ = Mock(return_value=download_response)
    download_response.__exit__ = Mock(return_value=False)

    mock_get.side_effect = [poll_response, download_response]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="9:16")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["aspect_ratio"] == "9:16"
    assert call_kwargs["json"]["resolution"] == "720p"
    assert "model" not in call_kwargs["json"]


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_api_failure(mock_sleep, mock_post, mock_get):
    """Poll returns status='failed' → raises RuntimeError."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {"generation": {"status": "failed"}}
    mock_get.return_value = poll_response

    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(RuntimeError, match="Higgsfield job job-abc failed"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_timeout(mock_sleep, mock_post, mock_get):
    """Poll always returns status='processing' for _MAX_POLLS iterations → raises TimeoutError."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {"generation": {"status": "processing"}}
    mock_get.return_value = poll_response

    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(TimeoutError, match="Higgsfield job job-abc timed out"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_sleep.call_count == 24


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_key_auth_header_sent(mock_sleep, mock_post, mock_get):
    """Authorization header is 'Key key_id:key_secret' — no base64 encoding."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "completed",
            "results": {"rawUrl": "https://cdn.higgsfield.ai/img.jpg"}
        }
    }

    download_response = Mock()
    download_response.content = _mock_image_bytes()
    download_response.__enter__ = Mock(return_value=download_response)
    download_response.__exit__ = Mock(return_value=False)

    mock_get.side_effect = [poll_response, download_response]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Key test-id:test-secret"


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_submit_uses_correct_endpoint(mock_sleep, mock_post, mock_get):
    """POST is sent to /higgsfield-ai/soul/standard."""
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "completed",
            "results": {"rawUrl": "https://cdn.higgsfield.ai/img.jpg"}
        }
    }

    download_response = Mock()
    download_response.content = _mock_image_bytes()
    download_response.__enter__ = Mock(return_value=download_response)
    download_response.__exit__ = Mock(return_value=False)

    mock_get.side_effect = [poll_response, download_response]

    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    mock_post.assert_called_once()
    call_args = mock_post.call_args[0]
    assert call_args[0] == "https://platform.higgsfield.ai/higgsfield-ai/soul/standard"
