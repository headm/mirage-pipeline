"""Branded Tesseract edit: the avatar clip plus hook, captions, disclosure, logo and call to action.

Layout keeps text out of TikTok's covered areas: the top bar (~170 px), the right-hand
button column, and the caption/description area at the bottom (~ last 400 px).
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .config import ROOT, Config
from .video import VideoFolder

BRAND = json.loads((ROOT / "brand" / "brand.json").read_text())
LOGO = ROOT / "brand" / "logo-small.png"  # 217 x 240


def rgba(hex_color: str, alpha: float = 1.0) -> list[float]:
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [alpha]


CHARCOAL = BRAND["colors"]["charcoal"]
BLUE = BRAND["colors"]["blue"]
WHITE = [1, 1, 1, 1]


def caption_phrases(alignment: dict, max_words: int = 4) -> list[tuple[str, int, int]]:
    """Group ElevenLabs character timings into short phrases: (text, start_ms, end_ms)."""
    words, current, start, last_end = [], "", None, 0.0
    for ch, s, e in zip(alignment["characters"], alignment["character_start_times_seconds"],
                        alignment["character_end_times_seconds"]):
        if ch.isspace():
            if current:
                words.append((current, start, last_end))
            current, start = "", None
            continue
        if start is None:
            start = s
        current += ch
        last_end = e
    if current:
        words.append((current, start, last_end))

    phrases, group = [], []
    for word in words:
        group.append(word)
        if len(group) == max_words or re.search(r"[.?!,:;]$", word[0]):
            phrases.append(group)
            group = []
    if group:
        phrases.append(group)
    return [(" ".join(w[0] for w in g), int(g[0][1] * 1000), int(g[-1][2] * 1000)) for g in phrases]


def transform(x: float, y: float) -> dict:
    return {"anchorPoint": [0, 0], "position": [x, y], "scale": [100, 100], "rotation": 0, "opacity": 100}


def rect(layer_id, name, start, duration, pos, size, color):
    return {"type": "createFxRectLayer", "compositionId": "main", "insertIndex": 0, "layerId": layer_id,
            "name": name, "activeRange": {"start": start, "duration": duration},
            "transform": transform(*pos), "rect": {"size": size, "fillColor": color}}


def text(layer_id, name, words, start, duration, pos, box, size, font, justify="center"):
    return {"type": "createFxTextLayer", "compositionId": "main", "insertIndex": 0, "layerId": layer_id,
            "name": name, "activeRange": {"start": start, "duration": duration},
            "transform": transform(*pos),
            "sourceText": {"text": words, "fontFamily": font["fontFamily"], "fontStyle": font["fontStyle"],
                           "fontSize": size, "fillColor": WHITE, "justification": justify,
                           "boxText": True, "boxPosition": [0, 0], "boxSize": box}}


class Tsrct:
    def __init__(self, binary: str, project: Path):
        self.binary, self.project = binary, str(project)

    def __call__(self, *args: str) -> dict:
        out = subprocess.run([self.binary, *args], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"tsrct {' '.join(args)} failed: {out.stdout}{out.stderr}")
        lines = out.stdout.strip().splitlines()
        return json.loads(lines[-1]) if lines else {}


def encoder_args() -> list[str]:
    """Tesseract's Linux build has no H.264 encoder of its own; there it hands frames to the
    system ffmpeg (set TSRCT_FFMPEG, as cloud_setup.sh does). On a Mac the built-in one works."""
    path = os.environ.get("TSRCT_FFMPEG")
    return ["--encoder-backend", "external-ffmpeg-command", "--ffmpeg-path", path] if path else []


def build(v: VideoFolder, cfg: Config) -> None:
    script = json.loads(v.path("script.json").read_text())
    alignment = json.loads(v.path("alignment.json").read_text())
    project = v.local / "edit.tsrct"
    project.unlink(missing_ok=True)
    t = Tsrct(cfg.tsrct, project)

    t("project", "create", "-p", str(project))
    clip = t("project", "import-video", "-p", str(project), "--file", str(v.path("raw.mp4")), "--asset-id", "avatar")
    t("project", "import-asset", "-p", str(project), "--file", str(LOGO), "--asset-id", "logo", "--kind", "image")
    font = t("project", "import-font", "--project", str(project), "--file", str(cfg.font))
    dur = clip["durationMs"]

    # Footage and logo are structural layers: add them through checkout/commit.
    doc_file = v.local / "edit.json"
    t("project", "checkout", "-p", str(project), "-o", str(doc_file))
    doc = json.loads(doc_file.read_text())
    w, h = doc["dimensions"]["width"], doc["dimensions"]["height"]
    doc["duration"] = dur / 1000
    doc["composition"]["layers"] = [
        {"type": "Image", "id": 2, "name": "Logo", "blendMode": "normal",
         "activeRange": {"start": 0, "duration": dur}, "transform": transform(w - 150, 180),
         "source": {"assetId": "logo", "fit": "contain", "sourceRect": {"x": 0, "y": 0, "width": 108, "height": 120}}},
        {"type": "Video", "id": 1, "name": "Avatar",
         "playback": {"type": "windowed", "inputRange": {"start": 0, "duration": dur},
                      "mapping": {"type": "linear", "input": {"start": 0, "duration": dur},
                                  "output": {"start": 0, "duration": dur}}, "inputOffsetMs": 0},
         "sourceRange": {"start": 0, "duration": dur}, "sourceIntrinsicDuration": dur, "volume": 1.0,
         "transform": transform(0, 0),
         "source": {"assetId": "avatar", "fit": "cover", "sourceRect": {"x": 0, "y": 0, "width": w, "height": h}}},
    ]
    doc_file.write_text(json.dumps(doc, indent=2))
    t("project", "commit", "-p", str(project), "--file", str(doc_file))

    # Graphics as one action batch; each insert at index 0 lands in front of what came before.
    cta_start = max(0, dur - 4000)
    actions = [
        # Disclosure, visible for the whole video.
        rect(10, "Disclosure shade", 0, dur, [48, 190], [600, 64], rgba(CHARCOAL, 0.8)),
        text(11, "Disclosure", BRAND["disclosure"], 0, dur, [64, 203], [568, 44], 30, font, "left"),
        # Hook for the first 3 seconds.
        rect(12, "Hook shade", 0, 3000, [60, 300], [880, 220], rgba(CHARCOAL, 0.88)),
        rect(13, "Hook accent", 0, 3000, [60, 300], [14, 220], rgba(BLUE)),
        text(14, "Hook", script["hook"], 0, 3000, [100, 325], [810, 180], 66, font, "left"),
        # Caption bar behind the timed phrases.
        rect(20, "Caption shade", 0, cta_start, [90, 1400], [900, 150], rgba(CHARCOAL, 0.8)),
    ]
    # Each phrase stays up until the next one starts, so the bar is never empty between phrases.
    phrases = [p for p in caption_phrases(alignment) if p[1] < cta_start]
    next_id = 21
    for i, (words, start, _) in enumerate(phrases):
        start = 0 if i == 0 else start
        end = phrases[i + 1][1] if i + 1 < len(phrases) else cta_start
        actions.append(text(next_id, f"Caption {next_id - 20}", words, start,
                            max(1, min(end, cta_start) - start), [110, 1420], [860, 120], 56, font))
        next_id += 1
    # Call to action replaces the captions for the last 4 seconds.
    actions += [
        rect(next_id, "CTA shade", cta_start, dur - cta_start, [90, 1360], [900, 190], rgba(BLUE)),
        text(next_id + 1, "CTA", BRAND["cta"], cta_start, dur - cta_start, [120, 1385], [840, 150], 54, font),
    ]
    actions_file = v.local / "actions.json"
    actions_file.write_text(json.dumps(actions, indent=2))
    t("project", "apply", "-p", str(project), "--actions", str(actions_file))

    t("preview", "-p", str(project), "-t", "0.6", "-o", str(v.local / "cover.png"))
    t("export", "-p", str(project), "-o", str(v.local / "final.mp4"), "--resolution", "1080p", "--fps", "30", *encoder_args())
