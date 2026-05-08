import base64
import io
import time
import requests
from PIL import Image

_BASE_URL = "https://api.higgsfield.ai"
_POLL_INTERVAL = 5
_MAX_POLLS = 24  # 2 minutes max
_PRIMARY_MODEL = "nano_banana_2"
_FALLBACK_MODEL = "seedream_v5_lite"

class HiggsfileClient:
    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("HIGGSFIELD_API_KEY cannot be empty")
        if ":" not in api_key:
            raise ValueError("HIGGSFIELD_API_KEY must be in format 'key_id:key_secret'")
        token = base64.b64encode(api_key.encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}

    def generate_image(self, prompt: str, aspect_ratio: str) -> Image.Image:
        try:
            job_id = self._submit(prompt, aspect_ratio, _PRIMARY_MODEL)
            raw_url = self._poll(job_id)
        except Exception as primary_err:
            print(f"[higgsfield] {_PRIMARY_MODEL} failed ({primary_err}), falling back to {_FALLBACK_MODEL}")
            job_id = self._submit(prompt, aspect_ratio, _FALLBACK_MODEL)
            raw_url = self._poll(job_id)
        return self._download(raw_url)

    def _submit(self, prompt: str, aspect_ratio: str, model: str) -> str:
        resp = requests.post(
            f"{_BASE_URL}/v1/generations",
            headers=self._headers,
            json={"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["results"][0]["id"]

    def _poll(self, job_id: str) -> str:
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            resp = requests.get(
                f"{_BASE_URL}/v1/generations/{job_id}",
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
