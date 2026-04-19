"""Run this once to generate sample MP3s for each OpenAI TTS voice."""
import os
from pathlib import Path
from openai import OpenAI

SAMPLE = (
    "When the insurance company denied his claim, he thought it was over. "
    "But what happened next changed everything — and it's something every driver needs to know."
)

VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
out_dir = Path("output/voice_previews")
out_dir.mkdir(parents=True, exist_ok=True)

for voice in VOICES:
    path = out_dir / f"{voice}.mp3"
    print(f"Generating {voice}...")
    response = client.audio.speech.create(
        model="tts-1-hd",
        voice=voice,
        input=SAMPLE,
        response_format="mp3",
    )
    path.write_bytes(response.content)
    print(f"  → {path}")

print("\nDone. Open output/voice_previews/ to listen.")
