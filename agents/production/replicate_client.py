import io
import time
import requests
from PIL import Image

_BASE_URL = "https://api.replicate.com"
_PREDICTIONS_PATH = "/v1/models/bytedance/seedream-5-lite/predictions"
_SIZE = "2K"
_OUTPUT_FORMAT = "webp"
_POLL_INTERVAL = 5
_MAX_POLLS = 24  # 2 minutes max


class ReplicateClient:
    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("REPLICATE_API_KEY cannot be empty")
        self._headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }

    def generate_image(self, prompt: str, aspect_ratio: str) -> Image.Image:
        job_id = self._submit(prompt, aspect_ratio)
        raw_url = self._poll(job_id)
        return self._download(raw_url)

    def _submit(self, prompt: str, aspect_ratio: str) -> str:
        resp = requests.post(
            f"{_BASE_URL}{_PREDICTIONS_PATH}",
            headers=self._headers,
            json={
                "input": {
                    "prompt": prompt,
                    "size": _SIZE,
                    "aspect_ratio": aspect_ratio,
                    "output_format": _OUTPUT_FORMAT,
                }
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def _poll(self, job_id: str) -> str:
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            resp = requests.get(
                f"{_BASE_URL}/v1/predictions/{job_id}",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data["status"]
            if status == "succeeded":
                return data["output"][0]
            if status in ("failed", "canceled"):
                raise RuntimeError(f"Replicate job {job_id} ended with status: {status}")
        raise TimeoutError(f"Replicate job {job_id} timed out after {_MAX_POLLS * _POLL_INTERVAL}s")

    def _download(self, url: str) -> Image.Image:
        with requests.get(url, timeout=30) as resp:
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
