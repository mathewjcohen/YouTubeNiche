"""
Live integration test for HiggsfileClient.

Submits a real image generation job, prints the raw status response at each
poll, and opens the result on success. Consumes one credit.

Usage:
    python3 tests/integration/test_higgsfield_live.py
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Load .env from repo root
env_path = Path(__file__).resolve().parents[2] / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

api_key = os.environ.get("HIGGSFIELD_API_KEY")
if not api_key:
    print("ERROR: HIGGSFIELD_API_KEY not found in .env or environment")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.production.higgsfield_client import HiggsfileClient

print(f"Using key: {api_key[:8]}...{api_key[-4:]}")
print()

client = HiggsfileClient(api_key=api_key)

style_id = client._get_style_id()
print(f"Style ID: {style_id}")
print()

print("Submitting job...")
import requests, time, io
from agents.production.higgsfield_client import _BASE_URL, _SUBMIT_PATH, _QUALITY, _ASPECT_RATIO_MAP

resp = requests.post(
    f"{_BASE_URL}{_SUBMIT_PATH}",
    headers=client._headers,
    json={
        "params": {
            "prompt": "A dramatic YouTube thumbnail, bold lighting, high contrast, cinematic",
            "quality": _QUALITY,
            "style_id": style_id,
            "width_and_height": _ASPECT_RATIO_MAP["16:9"],
            "batch_size": 1,
            "enhance_prompt": False,
            "style_strength": 1,
            "image_reference": None,
            "custom_reference_id": None,
            "custom_reference_strength": 1,
        },
        "webhook": None,
    },
    timeout=30,
)
print(f"POST status: {resp.status_code}")
print(f"POST response: {resp.json()}")
print()

submit_data = resp.json()
job_id = submit_data.get("id")
if not job_id:
    print("ERROR: No id in submit response")
    sys.exit(1)

print(f"Job ID: {job_id}")
print("Polling...")

for i in range(24):
    time.sleep(5)
    poll = requests.get(
        f"{_BASE_URL}/requests/{job_id}/status",
        headers=client._headers,
        timeout=15,
    )
    data = poll.json()
    print(f"  Poll {i+1}: {data}")

    status = data.get("status")
    if status == "completed":
        images = data.get("images", [])
        if not images:
            print(f"\nERROR: status=completed but no images in response")
            print(f"Full response: {data}")
            sys.exit(1)
        raw_url = images[0]["url"]
        print(f"\nSUCCESS — rawUrl: {raw_url}")

        img_resp = requests.get(raw_url, timeout=30)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(img_resp.content)
        tmp.close()
        print(f"Saved to: {tmp.name}")
        subprocess.run(["open", tmp.name])
        sys.exit(0)

    if status in ("failed", "nsfw", "canceled"):
        print(f"\nFAILED — job ended with status: {status}")
        sys.exit(1)

print("\nTIMEOUT — job did not complete in 2 minutes")
sys.exit(1)
