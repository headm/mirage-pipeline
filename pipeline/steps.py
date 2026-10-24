"""Production steps for one video. Each writes its output files into the video's work folder;
VideoFolder.run uploads them and skips any step whose outputs already exist in the cloud."""
import base64
import json
import os
import re
import time

import requests

from . import edit, paper2
from .config import Config
from .video import Step, VideoFolder

CAPTION_PREFIX = paper2.BRAND["caption_prefix"]
SPOKEN_DISCLOSURE = paper2.BRAND["disclosure_spoken"]
BANNED = [r"\bguarantee", r"cheaper than", r"\d+(\.\d+)?\s*%(?![^.]*delivery)", r"\bwe at aria\b"]


def check_script(v: VideoFolder) -> None:
    """The cloud agent writes script.json by following instructions/script_writer.md; this checks it."""
    path = v.local / "script.json"
    if not path.exists():
        raise RuntimeError(f"write {path} first, following instructions/script_writer.md")
    s = json.loads(path.read_text())
    problems = [f"missing {k}" for k in ("topic_id", "hook", "script", "caption", "hashtags", "claims") if not s.get(k)]
    script = s.get("script", "")
    if not 300 <= len(script) <= 800:
        problems.append(f"script is {len(script)} characters, needs 300-800")
    sentences = paper2.split_sentences(script)
    if len(sentences) < 2 or paper2.normalize(sentences[1]) != paper2.normalize(SPOKEN_DISCLOSURE):
        problems.append(f"second sentence must be the disclosure: \"{SPOKEN_DISCLOSURE}\"")
    if not s.get("caption", "").startswith(CAPTION_PREFIX):
        problems.append(f"caption must start with '{CAPTION_PREFIX}'")
    for pattern in BANNED:
        if re.search(pattern, script, re.IGNORECASE):
            problems.append(f"script matches banned pattern {pattern}")
    problems += paper2.validate_moments(s.get("moments", []), s.get("on_screen_review", []))
    if problems:
        raise RuntimeError("script.json rejected: " + "; ".join(problems))


def voice(v: VideoFolder) -> None:
    script = json.loads(v.path("script.json").read_text())["script"]
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{os.environ['ELEVENLABS_VOICE_ID']}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": script, "model_id": os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")},
        timeout=180,
    )
    resp.raise_for_status()
    body = resp.json()
    seconds = body["alignment"]["character_end_times_seconds"][-1]
    if seconds > 60:
        raise RuntimeError(f"voice is {seconds:.0f}s; Mirage accepts at most 60s. Shorten the script.")
    (v.local / "voice.mp3").write_bytes(base64.b64decode(body["audio_base64"]))
    (v.local / "alignment.json").write_text(json.dumps(body["alignment"]))


def avatar(v: VideoFolder, cfg: Config) -> None:
    api = "https://api.mirage.app/v1"
    headers = {"x-api-key": os.environ["MIRAGE_API_KEY"]}

    # Save the job id before waiting, so a crash resumes this render instead of paying for another.
    if v.done("mirage_job.txt"):
        job = v.path("mirage_job.txt").read_text().strip()
    else:
        reference = v.store.download("refs/reference.mp4", cfg.work_dir / "reference.mp4") \
            if not (cfg.work_dir / "reference.mp4").exists() else cfg.work_dir / "reference.mp4"
        with v.path("voice.mp3").open("rb") as a, reference.open("rb") as r:
            resp = requests.post(f"{api}/videos", headers=headers, data={"model": "mirage-avatar-x"},
                                 files={"audio_reference": a, "video_reference": r}, timeout=300)
        if not resp.ok:
            raise RuntimeError(f"Mirage rejected the render {resp.status_code}: {resp.text}")
        job = resp.json()["id"]
        (v.local / "mirage_job.txt").write_text(job)
        v.save("mirage_job.txt")

    deadline = time.time() + 30 * 60
    while True:
        status = requests.get(f"{api}/videos/{job}", headers=headers, timeout=30).json()
        if status["status"] == "COMPLETE":
            break
        if status["status"] in ("FAILED", "CANCELLED") or time.time() > deadline:
            raise RuntimeError(f"Mirage render {job} ended as {status['status']}: {status.get('error')}")
        time.sleep(15)
    content = requests.get(f"{api}/videos/{job}/content", headers=headers, timeout=300)
    content.raise_for_status()
    (v.local / "raw.mp4").write_bytes(content.content)


def package(v: VideoFolder) -> None:
    s = json.loads(v.path("script.json").read_text())
    tags = " ".join("#" + t.lstrip("#") for t in s["hashtags"])
    (v.local / "caption.txt").write_text(f"{s['caption']}\n\n{tags}\n")
    queue = f"queue/{v.id}"
    v.store.upload(v.path("final.mp4"), f"{queue}/video.mp4")
    v.store.upload(v.path("cover.png"), f"{queue}/cover.png")
    v.store.upload(v.local / "caption.txt", f"{queue}/caption.txt")


def matte(v: VideoFolder) -> None:
    from .matte import make_matte  # onnxruntime is only needed for this step
    make_matte(v.path("raw.mp4"), v.local / "matte.mp4")


def production_steps(cfg: Config) -> list[Step]:
    if os.environ.get("TEMPLATE", "paper2") == "classic":
        edit_step = Step("edit", ("final.mp4", "cover.png", "edit.tsrct"), lambda v: edit.build(v, cfg))
    else:
        edit_step = Step("edit", ("final.mp4", "cover.png", "edit.tsrct", "layout.json"), lambda v: paper2.build(v, cfg))
    return [
        Step("script", ("script.json",), check_script),
        Step("voice", ("voice.mp3", "alignment.json"), voice),
        Step("avatar", ("raw.mp4",), lambda v: avatar(v, cfg)),
        Step("matte", ("matte.mp4",), matte),
        edit_step,
        Step("package", ("caption.txt",), package),
    ]
