import io
import pytest
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
    client = HiggsfileClient(api_key="test-key")
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
    client = HiggsfileClient(api_key="test-key")
    client.generate_image(prompt="test prompt", aspect_ratio="9:16")

    # Verify aspect_ratio in the POST request
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["aspect_ratio"] == "9:16"


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
    client = HiggsfileClient(api_key="test-key")
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

    # Execute and verify
    client = HiggsfileClient(api_key="test-key")
    with pytest.raises(TimeoutError, match="Higgsfield job job-abc timed out"):
        client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    # Verify sleep was called _MAX_POLLS times
    assert mock_sleep.call_count == 24


@patch("agents.production.higgsfield_client.requests.get")
@patch("agents.production.higgsfield_client.requests.post")
@patch("agents.production.higgsfield_client.time.sleep")
def test_bearer_auth_header_sent(mock_sleep, mock_post, mock_get):
    """Verify that the Authorization header sent in the POST is 'Bearer test-key'."""
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
    client = HiggsfileClient(api_key="test-key")
    client.generate_image(prompt="test prompt", aspect_ratio="16:9")

    # Verify Authorization header in POST
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
