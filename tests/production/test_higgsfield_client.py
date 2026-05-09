import io
import pytest
import requests
from unittest.mock import Mock, patch, call
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
    """Test happy path: submit → poll once (completed) → download returns PIL Image."""
    # Setup mocks
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

    # Execute
    client = HiggsfileClient(api_key="test-id:test-secret")
    result = client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    # Verify
    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (1, 1)


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_short_aspect_ratio(mock_sleep, mock_post, mock_get):
    """Verify '9:16' is passed to the POST body when called with aspect_ratio='9:16'."""
    # Setup mocks
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

    # Execute
    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="9:16")

    # Verify aspect_ratio and primary model in the POST request
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["aspect_ratio"] == "9:16"
    assert call_kwargs["json"]["model"] == "nano_banana_2"


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_falls_back_to_seedream_on_primary_failure(mock_sleep, mock_post, mock_get):
    """When nano_banana_2 fails, falls back to seedream_v5_lite and returns an image."""
    # First POST (primary) raises; second POST (fallback) succeeds
    primary_fail = Mock()
    primary_fail.raise_for_status.side_effect = RuntimeError("credits exhausted")
    fallback_ok = Mock()
    fallback_ok.json.return_value = {"results": [{"id": "job-fallback"}]}
    mock_post.side_effect = [primary_fail, fallback_ok]

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
    # Second call used the fallback model
    assert mock_post.call_count == 2
    fallback_call_kwargs = mock_post.call_args_list[1][1]
    assert fallback_call_kwargs["json"]["model"] == "seedream_v5_lite"


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_skips_model_fallback_on_5xx(mock_sleep, mock_post, mock_get):
    """On a 5xx HTTP error (e.g. 522 Cloudflare timeout), re-raises immediately without
    attempting the fallback model — the server is down, not the model."""
    fake_response = Mock()
    fake_response.status_code = 522
    http_err = requests.HTTPError(response=fake_response)
    mock_post.return_value.raise_for_status.side_effect = http_err

    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(requests.HTTPError):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    assert mock_post.call_count == 1  # no fallback model attempted


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_api_failure(mock_sleep, mock_post, mock_get):
    """Poll returns status='failed' → raises RuntimeError."""
    # Setup mocks
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "failed"
        }
    }
    mock_get.return_value = poll_response

    # Execute and verify
    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(RuntimeError, match="Higgsfield job job-abc failed"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_generate_image_raises_on_timeout(mock_sleep, mock_post, mock_get):
    """Poll always returns status='processing' for all _MAX_POLLS iterations → raises TimeoutError."""
    # Setup mocks
    mock_post.return_value.json.return_value = {"results": [{"id": "job-abc"}]}

    poll_response = Mock()
    poll_response.json.return_value = {
        "generation": {
            "status": "processing"
        }
    }
    mock_get.return_value = poll_response

    # Execute and verify — timeout on primary triggers fallback which also times out
    client = HiggsfileClient(api_key="test-id:test-secret")
    with pytest.raises(TimeoutError, match="Higgsfield job job-abc timed out"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    # Primary + fallback each poll _MAX_POLLS times
    assert mock_sleep.call_count == 48


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_basic_auth_header_sent(mock_sleep, mock_post, mock_get):
    """Verify that the Authorization header sent in the POST is Basic auth over 'id:secret'."""
    # Setup mocks
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

    # Execute
    client = HiggsfileClient(api_key="test-id:test-secret")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    # Verify Authorization header in POST is Basic auth over "test-id:test-secret"
    import base64
    expected = "Basic " + base64.b64encode(b"test-id:test-secret").decode()
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == expected
