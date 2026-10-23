"""Spike 1.2: speak a script in your cloned voice with ElevenLabs.

Usage:
    python spike/tts_test.py spike/scripts/sample1.txt out/sample1

Writes <out>.mp3 and <out>.alignment.json (character timings, used later for captions).
Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in the environment (see .env.example).
"""
import base64
import json
import os
import sys
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"
MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")


def speak(text: str, out_base: Path) -> None:
    voice_id = os.environ["ELEVENLABS_VOICE_ID"]
    resp = requests.post(
        f"{API}/text-to-speech/{voice_id}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": MODEL_ID},
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()

    out_base.parent.mkdir(parents=True, exist_ok=True)
    out_base.with_suffix(".mp3").write_bytes(base64.b64decode(body["audio_base64"]))
    out_base.with_suffix(".alignment.json").write_text(json.dumps(body["alignment"], indent=2))

    ends = body["alignment"]["character_end_times_seconds"]
    seconds = ends[-1] if ends else 0
    print(f"{out_base.with_suffix('.mp3')}: {seconds:.1f}s")
    if seconds > 60:
        print("WARNING: over 60s, Mirage will reject this audio. Shorten the script.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    speak(Path(sys.argv[1]).read_text().strip(), Path(sys.argv[2]))
