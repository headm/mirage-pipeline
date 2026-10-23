"""Spike 1.3: lip-sync your reference clip to an audio file with Mirage Avatar X.

Usage:
    python spike/avatar_test.py out/sample1.mp3 refs/reference.mp4 out/sample1_raw.mp4

Needs MIRAGE_API_KEY in the environment (see .env.example).
"""
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.mirage.app/v1"


def render(audio: Path, reference: Path, out: Path) -> None:
    headers = {"x-api-key": os.environ["MIRAGE_API_KEY"]}

    with audio.open("rb") as a, reference.open("rb") as v:
        resp = requests.post(
            f"{API}/videos",
            headers=headers,
            data={"model": "mirage-avatar-x"},
            files={"audio_reference": a, "video_reference": v},
            timeout=300,
        )
    if not resp.ok:
        sys.exit(f"submit failed {resp.status_code}: {resp.text}")
    video_id = resp.json()["id"]
    print(f"submitted {video_id}")

    started = time.time()
    while True:
        status = requests.get(f"{API}/videos/{video_id}", headers=headers, timeout=30).json()
        print(f"  {status['status']} {status.get('progress', '')}")
        if status["status"] == "COMPLETE":
            break
        if status["status"] in ("FAILED", "CANCELLED"):
            sys.exit(f"render {status['status']}: {status.get('error')}")
        time.sleep(10)

    content = requests.get(f"{API}/videos/{video_id}/content", headers=headers, timeout=300)
    content.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content.content)
    print(f"{out}: {len(content.content) / 1e6:.1f} MB in {time.time() - started:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    render(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
