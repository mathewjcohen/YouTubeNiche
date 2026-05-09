import io
import time
import requests
from PIL import Image

_BASE_URL = "https://platform.higgsfield.ai"
_SUBMIT_PATH = "/higgsfield-ai/soul/standard"
_RESOLUTION = "720p"
_POLL_INTERVAL = 5
_MAX_POLLS = 24  # 2 minutes max

class HiggsfileClient:
    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("HIGGSFIELD_API_KEY cannot be empty")
        if ":" not in api_key:
            raise ValueError("HIGGSFIELD_API_KEY must be in format 'key_id:key_secret'")
        self._headers = {"Authorization": f"Key {api_key}"}

    def generate_image(self, prompt: str, aspect_ratio: str) -> Image.Image:
        job_id = self._submit(prompt, aspect_ratio)
        raw_url = self._poll(job_id)
        return self._download(raw_url)

    def _submit(self, prompt: str, aspect_ratio: str) -> str:
        resp = requests.post(
            f"{_BASE_URL}{_SUBMIT_PATH}",
            headers=self._headers,
            json={"prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": _RESOLUTION},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["results"][0]["id"]

    def _poll(self, job_id: str) -> str:
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            resp = requests.get(
                f"{_BASE_URL}{_SUBMIT_PATH}/{job_id}",
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()["generation"]
            status = data["status"]
            if status == "completed":
                return data["results"]["rawUrl"]
            if status == "failed":
                raise RuntimeError(f"Higgsfield job {job_id} failed")
        raise TimeoutError(f"Higgsfield job {job_id} timed out after {_MAX_POLLS * _POLL_INTERVAL}s")

    def _download(self, url: str) -> Image.Image:
        with requests.get(url, timeout=30) as resp:
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
