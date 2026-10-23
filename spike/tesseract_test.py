"""Spike 1.4: edit the raw avatar clip into a TikTok with the Tesseract CLI, unattended.

Usage:
    python spike/tesseract_test.py out/sample1_raw.mp4 out/sample1.alignment.json \
        spike/scripts/sample1.txt out/sample1_final.mp4

Builds a project with the clip, a hook line for the first 3 seconds, timed captions
from the ElevenLabs alignment, and a disclosure line at the end, then exports 1080x1920.
Set TSRCT to the tsrct binary (defaults to tsrct on PATH) and FONT to a TTF file.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TSRCT = os.environ.get("TSRCT", "tsrct")
FONT = os.environ.get("FONT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
DISCLOSURE = "Not financial advice · [Brokerage] · Lic. #[0000000]"
WHITE = [1, 1, 1, 1]
SHADE = [0, 0, 0, 0.55]


def tsrct(*args: str) -> dict:
    out = subprocess.run([TSRCT, *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"tsrct {' '.join(args)} failed:\n{out.stdout}\n{out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}


def caption_phrases(alignment: dict, max_words: int = 4) -> list[tuple[str, int, int]]:
    """Group the character timings into short phrases: (text, start_ms, end_ms)."""
    words, current, start = [], "", None
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    for ch, s, e in zip(chars, starts, ends):
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
        if len(group) == max_words or re.search(r"[.?!,:]$", word[0]):
            phrases.append(group)
            group = []
    if group:
        phrases.append(group)
    return [(" ".join(w[0] for w in g), int(g[0][1] * 1000), int(g[-1][2] * 1000)) for g in phrases]


def transform(x: float, y: float) -> dict:
    return {"anchorPoint": [0, 0], "position": [x, y], "scale": [100, 100], "rotation": 0, "opacity": 100}


def text_layer(layer_id, name, text, start, duration, pos, box, size, font):
    return {
        "type": "createFxTextLayer", "compositionId": "main", "insertIndex": 0,
        "layerId": layer_id, "name": name,
        "activeRange": {"start": start, "duration": duration},
        "transform": transform(*pos),
        "sourceText": {"text": text, "fontFamily": font["fontFamily"], "fontStyle": font["fontStyle"],
                       "fontSize": size, "fillColor": WHITE, "justification": "center",
                       "boxText": True, "boxPosition": [0, 0], "boxSize": box},
    }


def rect_layer(layer_id, name, start, duration, pos, size):
    return {
        "type": "createFxRectLayer", "compositionId": "main", "insertIndex": 0,
        "layerId": layer_id, "name": name,
        "activeRange": {"start": start, "duration": duration},
        "transform": transform(*pos),
        "rect": {"size": size, "fillColor": SHADE},
    }


def build(clip: Path, alignment_file: Path, script_file: Path, output: Path) -> None:
    work = output.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    project = str(work / "edit.tsrct")
    Path(project).unlink(missing_ok=True)

    tsrct("project", "create", "-p", project)
    video = tsrct("project", "import-video", "-p", project, "--file", str(clip), "--asset-id", "avatar")
    font = tsrct("project", "import-font", "--project", project, "--file", FONT)
    dur = video["durationMs"]

    # Footage goes in through checkout/commit (media-layer structure).
    doc_file = work / "doc.json"
    tsrct("project", "checkout", "-p", project, "-o", str(doc_file))
    doc = json.loads(doc_file.read_text())
    doc["duration"] = dur / 1000
    doc["composition"]["layers"] = [{
        "type": "Video", "id": 1, "name": "Avatar",
        "playback": {"type": "windowed", "inputRange": {"start": 0, "duration": dur},
                     "mapping": {"type": "linear", "input": {"start": 0, "duration": dur},
                                 "output": {"start": 0, "duration": dur}},
                     "inputOffsetMs": 0},
        "sourceRange": {"start": 0, "duration": dur},
        "sourceIntrinsicDuration": dur, "volume": 1.0,
        "transform": transform(0, 0),
        "source": {"assetId": "avatar", "fit": "cover",
                   "sourceRect": {"x": 0, "y": 0, "width": doc["dimensions"]["width"],
                                  "height": doc["dimensions"]["height"]}},
    }]
    doc_file.write_text(json.dumps(doc, indent=2))
    tsrct("project", "commit", "-p", project, "--file", str(doc_file))

    # Graphics go in as one action batch; each insert at index 0 lands in front.
    script = script_file.read_text().strip()
    hook = re.split(r"(?<=[.?!])\s", script, maxsplit=1)[0]
    actions = [
        rect_layer(10, "Hook shade", 0, 3000, [60, 220], [960, 300]),
        text_layer(11, "Hook", hook, 0, 3000, [90, 250], [900, 240], 72, font),
        rect_layer(20, "Caption shade", 0, dur, [70, 1530], [940, 220]),
    ]
    next_id = 21
    for text, start, end in caption_phrases(json.loads(alignment_file.read_text())):
        start = min(start, dur - 1)
        actions.append(text_layer(next_id, f"Caption {next_id - 20}", text, start,
                                  max(1, min(end, dur) - start), [90, 1560], [900, 180], 64, font))
        next_id += 1
    actions.append(text_layer(next_id, "Disclosure", DISCLOSURE, max(0, dur - 4000), min(4000, dur),
                              [90, 1790], [900, 60], 30, font))
    actions_file = work / "actions.json"
    actions_file.write_text(json.dumps(actions, indent=2))
    tsrct("project", "apply", "-p", project, "--actions", str(actions_file))

    for t in ("1.5", f"{dur / 2000:.1f}", f"{(dur - 2000) / 1000:.1f}"):
        tsrct("preview", "-p", project, "-t", t, "-o", str(work / f"preview_{t}.png"))

    started = time.time()
    tsrct("export", "-p", project, "-o", str(output), "--resolution", "1080p", "--fps", "30")
    print(f"{output}: exported in {time.time() - started:.0f}s ({len(actions)} graphics layers)")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    build(*(Path(a) for a in sys.argv[1:]))
