import io
import time
import requests
from PIL import Image

_BASE_URL = "https://platform.higgsfield.ai"
_SUBMIT_PATH = "/v1/text2image/soul"
_STYLES_PATH = "/v1/text2image/soul-styles"
_QUALITY = "720p"
_POLL_INTERVAL = 5
_MAX_POLLS = 24  # 2 minutes max

_ASPECT_RATIO_MAP = {
    "16:9": "2048x1152",
    "9:16": "1152x2048",
    "1:1": "1536x1536",
    "4:3": "2048x1536",
    "3:4": "1536x2048",
}


class HiggsfileClient:
    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("HIGGSFIELD_API_KEY cannot be empty")
        if ":" not in api_key:
            raise ValueError("HIGGSFIELD_API_KEY must be in format 'key_id:key_secret'")
        key_id, key_secret = api_key.split(":", 1)
        self._headers = {"hf-api-key": key_id, "hf-secret": key_secret}
        self._style_id: str | None = None

    def _get_style_id(self) -> str:
        if self._style_id is None:
            resp = requests.get(f"{_BASE_URL}{_STYLES_PATH}", headers=self._headers, timeout=15)
            resp.raise_for_status()
            styles = resp.json()
            if not styles:
                raise RuntimeError("No Soul styles available")
            self._style_id = styles[0]["id"]
        return self._style_id

    def generate_image(self, prompt: str, aspect_ratio: str) -> Image.Image:
        job_id = self._submit(prompt, aspect_ratio)
        raw_url = self._poll(job_id)
        return self._download(raw_url)

    def _submit(self, prompt: str, aspect_ratio: str) -> str:
        resp = requests.post(
            f"{_BASE_URL}{_SUBMIT_PATH}",
            headers=self._headers,
            json={
                "params": {
                    "prompt": prompt,
                    "quality": _QUALITY,
                    "style_id": self._get_style_id(),
                    "width_and_height": _ASPECT_RATIO_MAP.get(aspect_ratio, "2048x1152"),
                    "batch_size": 1,
                    "enhance_prompt": False,
                    "style_strength": 1,
                    "image_reference": None,
                    "custom_reference_id": "",
                    "custom_reference_strength": 1,
                },
                "webhook": None,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["request_id"]

    def _poll(self, job_id: str) -> str:
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            resp = requests.get(
                f"{_BASE_URL}/requests/{job_id}/status",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data["status"]
            if status == "completed":
                return data["results"]["rawUrl"]
            if status in ("failed", "nsfw", "canceled"):
                raise RuntimeError(f"Higgsfield job {job_id} ended with status: {status}")
        raise TimeoutError(f"Higgsfield job {job_id} timed out after {_MAX_POLLS * _POLL_INTERVAL}s")

    def _download(self, url: str) -> Image.Image:
        with requests.get(url, timeout=30) as resp:
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
