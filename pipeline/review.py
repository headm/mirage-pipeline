"""Review of a finished edit: automatic layout and media checks, plus a contact sheet of frames
for the agent to look at. Used by `python -m pipeline review <id>` (see ROUTINE.md).

Each problem says whether it can be fixed by changing the video's script.json (moments, their
timing, on-screen text, stickers). Anything else is a template or pipeline issue to report.
"""
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT

W, H, MARGIN = 1080, 1920, 6
TEXT = re.compile(r"^(Disclosure|Banner label|Keyword|Title word|Title label \d|Caption \d+)$")
STICKER = re.compile(r"^(Banner sticker|Circle sticker \d)$")
LOGO_BOX = (985 - 48, 215 - 53, 985 + 48, 215 + 53)


def bbox(layer: dict) -> tuple[float, float, float, float]:
    """Axis-aligned box of the (possibly rotated) layer at its resting position."""
    a = math.radians(layer["rotation"])
    hw, hh = layer["w"] / 2, layer["h"] / 2
    ex = abs(hw * math.cos(a)) + abs(hh * math.sin(a))
    ey = abs(hw * math.sin(a)) + abs(hh * math.cos(a))
    return layer["cx"] - ex, layer["cy"] - ey, layer["cx"] + ex, layer["cy"] + ey


def overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def area(box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def same_time(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def problem(check: str, detail: str, fixable: bool, hint: str) -> dict:
    return {"check": check, "detail": detail, "fixable_in_script": fixable, "hint": hint}


def layout_checks(layout: dict) -> list[dict]:
    layers, out = layout["layers"], []
    texts = [l for l in layers if TEXT.match(l["name"])]
    stickers = [l for l in layers if STICKER.match(l["name"])]

    for t in texts:
        x0, y0, x1, y1 = bbox(t)
        if x0 < MARGIN or y0 < MARGIN or x1 > W - MARGIN or y1 > H - MARGIN:
            out.append(problem("text off frame", f"{t['name']} at {t['start'] / 1000:.1f}s runs past the edge",
                               not t["name"].startswith(("Caption", "Disclosure")),
                               "shorten that moment's text"))

    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if a["name"].startswith("Caption") and b["name"].startswith("Caption"):
                continue
            smaller = min(area(bbox(a)), area(bbox(b)))
            if same_time(a, b) and smaller and overlap_area(bbox(a), bbox(b)) / smaller > 0.08:
                fixable = not (a["name"].startswith(("Caption", "Disclosure")) and b["name"].startswith(("Caption", "Disclosure")))
                out.append(problem("text collision", f"{a['name']} and {b['name']} overlap around "
                                   f"{max(a['start'], b['start']) / 1000:.1f}s", fixable,
                                   "move the moment to a different at_word"))

    for s in stickers:
        for t in texts:
            text_area = area(bbox(t))
            if same_time(s, t) and text_area and overlap_area(bbox(s), bbox(t)) / text_area > 0.25:
                out.append(problem("sticker covers text", f"{s['name']} covers {t['name']} around "
                                   f"{max(s['start'], t['start']) / 1000:.1f}s", True,
                                   "pick a different sticker or move the moment"))

    for l in layers:
        if l["name"] == "Logo":
            for o in layers:
                if o["name"] not in ("Logo", "Halftone overlay") and same_time(l, o) \
                        and overlap_area(LOGO_BOX, bbox(o)) > 0 and not o["behind_person"]:
                    out.append(problem("logo collision", f"{o['name']} covers the logo around "
                                       f"{max(l['start'], o['start']) / 1000:.1f}s", False, "template layout issue"))

    cta = [l for l in layers if l["name"] == "Title paper" and l["start"] == layout["cta_start"]]
    if not cta or cta[0]["end"] < layout["duration"] \
            or layout["last_positionX_key"].get(str(cta[0]["id"]), 0) > 300:
        out.append(problem("closing card", "the call-to-action card doesn't hold to the last frame",
                           False, "template issue"))

    for m in layout.get("skipped", []):
        out.append(problem("moment skipped", f"{m['type']} at word {m.get('at_word')} was dropped: {m['reason']}",
                           True, "use an earlier at_word, or drop the moment"))
    return out


def media_checks(video: Path, layout: dict) -> list[dict]:
    out = []
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                      "-of", "json", str(video)], capture_output=True, text=True).stdout)
    kinds = [s["codec_type"] for s in info.get("streams", [])]
    if "audio" not in kinds:
        out.append(problem("no audio", "the finished video has no audio track", False, "pipeline issue"))
    duration = float(info["format"]["duration"]) * 1000
    if abs(duration - layout["duration"]) > 400:
        out.append(problem("duration", f"video is {duration / 1000:.1f}s, edit is {layout['duration'] / 1000:.1f}s",
                           False, "pipeline issue"))
    black = subprocess.run(["ffmpeg", "-v", "info", "-i", str(video), "-vf", "blackdetect=d=0.4:pix_th=0.06",
                            "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    for start in re.findall(r"black_start:([\d.]+)", black):
        out.append(problem("black frames", f"black for 0.4s+ at {float(start):.1f}s", False, "pipeline issue"))
    return out


def frame_times(layout: dict) -> list[tuple[int, str]]:
    dur, times = layout["duration"], []
    for m in layout["placed"]:
        times.append((m["start"] + min(900, m["duration"] * 2 // 5), f"{m['type']}: in"))
        times.append((m["start"] + m["duration"] * 3 // 4, f"{m['type']}: settled"))
    disc = [l for l in layout["layers"] if l["name"] == "Disclosure"]
    if disc:
        times.append(((disc[0]["start"] + disc[0]["end"]) // 2, "disclosure"))
    times.append((layout["cta_start"] + 1500, "closing card"))
    times.append((dur - 150, "last frame"))
    busy = [(m["start"], m["start"] + m["duration"]) for m in layout["placed"]]
    quiet = [t for t in range(1500, layout["cta_start"], 1000) if not any(a <= t <= b for a, b in busy)]
    for t in quiet[:: max(1, len(quiet) // 2)][:2]:
        times.append((t, "talking"))
    return sorted(times)


def contact_sheet(video: Path, layout: dict, out: Path) -> list[str]:
    font = ImageFont.truetype(str(ROOT / "brand" / "paper2" / "fonts" / "Poppins-SemiBold.ttf"), 18)
    tiles, labels = [], []
    for ms, what in frame_times(layout):
        frame = out.parent / f"review_{ms}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ms / 1000:.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=270:-1", str(frame)], check=True)
        tiles.append(Image.open(frame).convert("RGB"))
        labels.append(f"{ms / 1000:.1f}s {what}")
        frame.unlink()
    cols = 4
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * 280, rows * 520), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(zip(tiles, labels)):
        x, y = (i % cols) * 280 + 5, (i // cols) * 520 + 5
        sheet.paste(tile, (x, y))
        d.text((x, y + 485), label, font=font, fill=(30, 30, 30))
    sheet.save(out)
    return labels
