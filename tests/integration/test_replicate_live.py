"""
Live integration test for ReplicateClient.

Submits a real Seedream 5.0 Lite image generation job, prints the raw status
response at each poll, and opens the result on success. Costs ~$0.035.

Usage:
    python3 tests/integration/test_replicate_live.py
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

if __name__ == "__main__":
    api_key = os.environ.get("REPLICATE_API_KEY")
    if not api_key:
        print("ERROR: REPLICATE_API_KEY not found in .env or environment")
        sys.exit(1)

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import requests, time

    print(f"Using key: {api_key[:8]}...{api_key[-4:]}")
    print()

    PREDICTIONS_URL = "https://api.replicate.com/v1/models/bytedance/seedream-5-lite/predictions"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }

    print("Submitting job...")
    resp = requests.post(
        PREDICTIONS_URL,
        headers=headers,
        json={
            "input": {
                "prompt": (
                    "YouTube thumbnail, horizontal 16:9, bold white text reading "
                    "'I QUIT MY JOB AND NEVER LOOKED BACK', shocked person reacting, "
                    "dramatic cinematic lighting, high contrast, photorealistic"
                ),
                "size": "2K",
                "aspect_ratio": "16:9",
                "output_format": "jpeg",
            }
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
            f"https://api.replicate.com/v1/predictions/{job_id}",
            headers=headers,
            timeout=15,
        )
        data = poll.json()
        print(f"  Poll {i+1}: status={data.get('status')}  logs={str(data.get('logs', ''))[:80]}")

        status = data.get("status")
        if status == "succeeded":
            output = data.get("output", [])
            if not output:
                print(f"\nERROR: status=succeeded but no output in response")
                print(f"Full response: {data}")
                sys.exit(1)
            raw_url = output[0]
            print(f"\nSUCCESS — url: {raw_url}")

            img_resp = requests.get(raw_url, timeout=30)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(img_resp.content)
            tmp.close()
            print(f"Saved to: {tmp.name}")
            subprocess.run(["open", tmp.name])
            sys.exit(0)

        if status in ("failed", "canceled"):
            print(f"\nFAILED — job ended with status: {status}")
            print(f"Error: {data.get('error')}")
            sys.exit(1)

    print("\nTIMEOUT — job did not complete in 2 minutes")
    sys.exit(1)
