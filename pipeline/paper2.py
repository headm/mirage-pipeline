"""Paper II style edit: cut-out avatar over paper-collage graphics, karaoke captions, punch-ins.

Text pieces (captions, tape labels, label-maker strips, title words) are rendered to PNG with
Pillow so per-word colours and outlines are exact; Tesseract does layout, timing, motion,
the person cutout (track matte) and export. See docs/paper2-spec.md for the style breakdown.

The cloud agent picks graphic "moments" in script.json:
    {"type": "banner",   "at_word": 4,  "label": "CARD FEES", "sticker": "terminal-blue"}
    {"type": "keyword",  "at_word": 18, "word": "Hidden"}
    {"type": "title",    "at_word": 30, "title": "free", "lines": ["STATEMENT", "ANALYSIS"]}
    {"type": "photo",    "at_word": 40, "photo": "cafe-sunlit"}
    {"type": "circle",   "at_word": 52, "circle": "sky-clouds", "stickers": ["coins", "receipt-cash"]}
The call to action is added automatically as a title card over the last seconds.
"""
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT, Config
from .video import VideoFolder

LIB = ROOT / "brand" / "paper2"
FONTS = LIB / "fonts"
BRAND = json.loads((ROOT / "brand" / "brand.json").read_text())
W, H = 1080, 1920
STOP_MOTION_FPS = 12
DURATIONS = {"banner": 2800, "keyword": 1600, "title": 3000, "photo": 2800, "circle": 3000}
CTA_MS = 3500
MOMENT_TYPES = set(DURATIONS)

POP = {"type": "cubicBezier", "x1": 0.2, "y1": 0.0, "x2": 0.2, "y2": 1.0}
LINEAR = {"type": "linear"}


# ---------- timing ----------

def word_timings(alignment: dict) -> list[tuple[str, int, int]]:
    words, current, start, end = [], "", None, 0.0
    for ch, s, e in zip(alignment["characters"], alignment["character_start_times_seconds"],
                        alignment["character_end_times_seconds"]):
        if ch.isspace():
            if current:
                words.append((current, int(start * 1000), int(end * 1000)))
            current, start = "", None
            continue
        start = s if start is None else start
        current += ch
        end = e
    if current:
        words.append((current, int(start * 1000), int(end * 1000)))
    return words


def phrases(words: list, max_words: int = 3) -> list[list[int]]:
    out, group = [], []
    for i, (w, _, _) in enumerate(words):
        group.append(i)
        if len(group) == max_words or re.search(r"[.?!,:;]$", w):
            out.append(group)
            group = []
    return out + ([group] if group else [])


def sentence_starts(words: list) -> list[int]:
    starts = [0]
    for i, (w, _, _) in enumerate(words[:-1]):
        if re.search(r"[.?!]$", w):
            starts.append(words[i + 1][1])
    return starts


# ---------- PNG rendering ----------

def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def caption_png(words: list[str], spoken: int, path: Path) -> tuple[int, int]:
    f = font("Poppins-Bold.ttf", 50)
    space = f.getlength(" ")
    widths = [f.getlength(w) for w in words]
    pad_x, pad_y, h = 30, 14, 82
    w = int(sum(widths) + space * (len(words) - 1) + 2 * pad_x)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=18, fill=(246, 246, 244, 250))
    x = pad_x
    for i, word in enumerate(words):
        d.text((x, h / 2), word, font=f, anchor="lm", fill=(40, 40, 40) if i <= spoken else (176, 176, 176))
        x += widths[i] + space
    im.save(path)
    return im.size


def on_strip(strip: str, text: str, fnt, fill, path: Path, pad: int, height: int,
             tracking: int = 0, stroke: int = 0, stroke_fill=None) -> tuple[int, int]:
    letters = list(text)
    width = sum(fnt.getlength(c) for c in letters) + tracking * (len(letters) - 1)
    size = (int(width + 2 * pad), height)
    im = Image.open(LIB / "paper" / strip).convert("RGBA").resize(size, Image.LANCZOS)
    d = ImageDraw.Draw(im)
    x = pad
    for c in letters:
        d.text((x, height / 2), c, font=fnt, anchor="lm", fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += fnt.getlength(c) + tracking
    im.save(path)
    return im.size


def tape_label(text: str, path: Path) -> tuple[int, int]:
    return on_strip("tape-black-1.png", text.upper(), font("Poppins-Bold.ttf", 78), (236, 230, 208), path, 60, 140)


def keyword_tape(word: str, path: Path) -> tuple[int, int]:
    return on_strip("tape-black-2.png", word, font("DMSerifDisplay-Regular.ttf", 110), (250, 248, 240), path,
                    55, 170, tracking=4, stroke=3, stroke_fill=(30, 30, 30))


def label_strip(text: str, path: Path, size: int = 40) -> tuple[int, int]:
    return on_strip("label-white.png", text.upper(), font("SpecialElite-Regular.ttf", size), (20, 20, 20), path,
                    22, int(size * 1.6), tracking=6)


def title_word(word: str, path: Path) -> tuple[int, int]:
    f = font("DMSerifDisplay-Regular.ttf", 210)
    w = int(f.getlength(word) + 40)
    im = Image.new("RGBA", (w, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((24, 136), word, font=f, anchor="lm", fill=(0, 40, 90, 120))  # soft offset shadow
    d.text((20, 130), word, font=f, anchor="lm", fill=(244, 238, 200))
    im.save(path)
    return im.size


# ---------- layers and actions ----------

class Builder:
    """Collects document layers (front first) and keyframe/effect actions."""

    def __init__(self):
        # front: persistent pieces and captions, front-most first. moments/behind_person: added in
        # build order and reversed at the end, so a piece added later sits in front of earlier ones.
        self.front, self.moments, self.behind_person, self.actions = [], [], [], []
        self.in_moment = False
        self.assets: dict[str, Path] = {}
        self.next_id = 100

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def image(self, path: Path, size: tuple[int, int], start: int, dur: int, center: tuple[float, float],
              width: float | None = None, rotation: float = 0, behind: bool = False, name: str = "") -> int:
        asset = "img-" + re.sub(r"[^a-zA-Z0-9_-]", "-", path.stem)[:40] + f"-{len(self.assets)}"
        self.assets[asset] = path
        w, h = size
        scale = 100 * (width / w) if width else 100
        lid = self.new_id()
        layer = {"type": "Image", "id": lid, "name": name or path.stem, "blendMode": "normal",
                 "activeRange": {"start": max(0, start), "duration": max(1, dur)},
                 "transform": {"anchorPoint": [w / 2, h / 2], "position": list(center),
                               "scale": [scale, scale], "rotation": rotation, "opacity": 100},
                 "source": {"assetId": asset, "fit": "contain", "sourceRect": {"x": 0, "y": 0, "width": w, "height": h}}}
        (self.behind_person if behind else self.moments if self.in_moment else self.front).append(layer)
        return lid

    def keys(self, lid: int, prop: str, frames: list[tuple[int, float, dict]]) -> None:
        self.actions.append({"type": "setFxPropertyKeyframes", "compositionId": "main",
                             "property": {"layerId": lid, "propertyType": prop},
                             "keyframes": [{"id": f"k{lid}-{prop}-{i}", "layerTime": max(0, t),
                                            "value": {"type": "float", "value": v}, "easing": e}
                                           for i, (t, v, e) in enumerate(frames)]})

    def stop_motion(self, lid: int) -> None:
        self.actions.append({"type": "addFxLayerEffect", "compositionId": "main", "layerId": lid,
                             "effectId": self.new_id(), "effect": {"type": "posterizeTime", "frameRate": STOP_MOTION_FPS}})

    def pop_in(self, lid: int, base_scale: float, at: int = 0, dur: int = 1000) -> None:
        self.keys(lid, "scaleX", [(at, base_scale * 0.6, LINEAR), (at + 220, base_scale * 1.06, POP),
                                  (at + 340, base_scale, POP)])
        self.keys(lid, "scaleY", [(at, base_scale * 0.6, LINEAR), (at + 220, base_scale * 1.06, POP),
                                  (at + 340, base_scale, POP)])
        self.keys(lid, "opacity", [(at, 0, LINEAR), (at + 60, 100, LINEAR), (dur - 120, 100, LINEAR), (dur, 0, LINEAR)])


def scale_for(size, width):
    return 100 * width / size[0]


# ---------- moments ----------

def banner(b: Builder, m: dict, t0: int, dur: int, tmp: Path) -> None:
    paper = LIB / "paper" / "banner-top.png"
    w, h = Image.open(paper).size  # transparent below the tear, so it can be taller than the paper
    lid = b.image(paper, (w, h), t0, dur, (540, h / 2), name="Banner paper")
    b.keys(lid, "positionY", [(0, -h / 2, LINEAR), (320, h / 2, POP), (dur - 320, h / 2, LINEAR), (dur, -h / 2 - 40, LINEAR)])
    b.stop_motion(lid)
    size = tape_label(m["label"], tmp / f"tape-{t0}.png")
    tl = b.image(tmp / f"tape-{t0}.png", size, t0 + 250, dur - 250, (520, 300), rotation=-4, name="Banner label")
    b.keys(tl, "positionY", [(dur - 570, 300, LINEAR), (dur - 250, -300, LINEAR)])
    b.pop_in(tl, 100, 0, dur - 250)
    b.stop_motion(tl)
    if m.get("sticker"):
        sp = LIB / "stickers" / f"{m['sticker']}.png"
        ss = Image.open(sp).size
        sl = b.image(sp, ss, t0 + 400, dur - 400, (820, 260), width=330, rotation=10, name="Banner sticker")
        sc = scale_for(ss, 330)
        b.pop_in(sl, sc, 0, dur - 400)
        b.keys(sl, "rotation", [(0, 18, LINEAR), (340, 10, POP), (dur - 400, 4, LINEAR)])
        b.stop_motion(sl)


def keyword(b: Builder, m: dict, t0: int, dur: int, tmp: Path) -> None:
    size = keyword_tape(m["word"], tmp / f"kw-{t0}.png")
    lid = b.image(tmp / f"kw-{t0}.png", size, t0, dur, (540, 300), rotation=-2, name="Keyword")
    b.pop_in(lid, 100, 0, dur)
    b.keys(lid, "rotation", [(0, -6, LINEAR), (340, -2, POP), (dur, 1, LINEAR)])
    b.stop_motion(lid)


def title_card(b: Builder, m: dict, t0: int, dur: int, tmp: Path) -> None:
    # Card torn down both sides: the torn left edge leads it in from the right, the torn right
    # edge trails it out to the left. Its canvas is wider than the frame, so neither tear shows
    # once it has settled.
    card_path = LIB / "paper" / "blue-paper-card.png"
    cw, ch = Image.open(card_path).size
    card = b.image(card_path, (cw, ch), t0, dur, (540, 960), name="Title paper")
    b.keys(card, "positionX", [(0, 540 + cw - 260, LINEAR), (300, 540, POP), (dur - 350, 540, LINEAR),
                               (dur, 540 - cw + 260, LINEAR)])
    size = title_word(m["title"], tmp / f"title-{t0}.png")
    tw = b.image(tmp / f"title-{t0}.png", size, t0 + 300, dur - 300, (540, 700), name="Title word")
    b.pop_in(tw, 100, 0, dur - 300)
    b.keys(tw, "positionX", [(dur - 650, 540, LINEAR), (dur - 300, -560, LINEAR)])
    b.stop_motion(tw)
    for i, line in enumerate(m.get("lines", [])[:3]):
        size = label_strip(line, tmp / f"label-{t0}-{i}.png")
        delay = 600 + i * 280
        ll = b.image(tmp / f"label-{t0}-{i}.png", size, t0 + delay, dur - delay, (540, 880 + i * 92),
                     rotation=(-1.5, 1, -0.5)[i], name=f"Title label {i + 1}")
        b.keys(ll, "opacity", [(0, 0, LINEAR), (40, 100, LINEAR)])
        b.keys(ll, "positionX", [(dur - delay - 350, 540, LINEAR), (dur - delay, -560, LINEAR)])
        b.stop_motion(ll)
    wipe = LIB / "paper" / "strip-newspaper.png"
    wl = b.image(wipe, Image.open(wipe).size, t0, 420, (540, 960), rotation=-12, name="Title wipe in")
    b.keys(wl, "positionX", [(0, 1900, LINEAR), (420, -900, LINEAR)])
    b.stop_motion(wl)


def photo(b: Builder, m: dict, t0: int, dur: int, tmp: Path) -> None:
    path = LIB / "photos" / f"{m['photo']}-torn.png"
    size = Image.open(path).size
    lid = b.image(path, size, t0, dur, (540, 470), width=900, rotation=-3, name="Photo insert")
    b.keys(lid, "positionX", [(0, 1650, LINEAR), (380, 540, POP), (dur - 380, 540, LINEAR), (dur, -700, LINEAR)])
    b.keys(lid, "rotation", [(0, 12, LINEAR), (380, -3, POP), (dur, -1, LINEAR)])
    b.stop_motion(lid)


def circle(b: Builder, m: dict, t0: int, dur: int, tmp: Path) -> None:
    path = LIB / "circles" / f"{m['circle']}.png"
    sc = scale_for((900, 900), 640)
    lid = b.image(path, (900, 900), t0, dur, (540, 560), width=640, behind=True, name="Halftone circle")
    b.pop_in(lid, sc, 0, dur)
    b.stop_motion(lid)
    spots = [((215, 430), -8), ((875, 360), 9), ((860, 760), -4)]
    for i, name in enumerate(m.get("stickers", [])[:3]):
        sp = LIB / "stickers" / f"{name}.png"
        ss = Image.open(sp).size
        (cx, cy), rot = spots[i]
        delay = 180 + i * 160
        sl = b.image(sp, ss, t0 + delay, dur - delay, (cx, cy), width=250, rotation=rot, name=f"Circle sticker {i + 1}")
        b.pop_in(sl, scale_for(ss, 250), 0, dur - delay)
        b.keys(sl, "rotation", [(0, rot * 2, LINEAR), (340, rot, POP), (dur - delay, -rot / 2, LINEAR)])
        b.stop_motion(sl)


BUILDERS = {"banner": banner, "keyword": keyword, "title": title_card, "photo": photo, "circle": circle}


def schedule(moments: list[dict], words: list, cta_start: int) -> list[tuple[dict, int, int]]:
    """Place each moment at its word, without overlaps, ending before the call to action."""
    placed, free_from = [], 0
    for m in sorted(moments, key=lambda m: m.get("at_word", 0)):
        if m.get("type") not in BUILDERS:
            continue
        idx = min(max(0, int(m.get("at_word", 0))), len(words) - 1)
        start = max(words[idx][1], free_from)
        dur = DURATIONS[m["type"]]
        if start + dur > cta_start - 200:
            print(f"skipping {m['type']} moment at word {idx}: it would run into the call to action")
            continue
        placed.append((m, start, dur))
        free_from = start + dur + 600
    return placed


def validate_moments(moments: list[dict]) -> list[str]:
    problems = []
    for m in moments:
        t = m.get("type")
        if t not in MOMENT_TYPES:
            problems.append(f"unknown moment type {t}")
            continue
        for key, folder in (("sticker", "stickers"), ("photo", "photos"), ("circle", "circles")):
            if key in m and not (LIB / folder / (m[key] + ("-torn.png" if key == "photo" else ".png"))).exists():
                problems.append(f"{t}: no {key} named {m[key]}")
        for s in m.get("stickers", []):
            if not (LIB / "stickers" / f"{s}.png").exists():
                problems.append(f"{t}: no sticker named {s}")
    return problems


# ---------- build ----------

def tsrct(cfg: Config, *args: str) -> dict:
    out = subprocess.run([cfg.tsrct, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"tsrct {' '.join(args)} failed: {out.stdout}{out.stderr}")
    lines = [l for l in out.stdout.strip().splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {}


def build(v: VideoFolder, cfg: Config) -> None:
    script = json.loads(v.path("script.json").read_text())
    words = word_timings(json.loads(v.path("alignment.json").read_text()))
    tmp = v.local / "paper2"
    tmp.mkdir(exist_ok=True)
    project = v.local / "edit.tsrct"
    project.unlink(missing_ok=True)
    p = str(project)

    tsrct(cfg, "project", "create", "-p", p)
    clip = tsrct(cfg, "project", "import-video", "-p", p, "--file", str(v.path("raw.mp4")), "--asset-id", "avatar")
    tsrct(cfg, "project", "import-video", "-p", p, "--file", str(v.path("matte.mp4")), "--asset-id", "matte")
    dur = clip["durationMs"]
    cta_start = max(0, dur - CTA_MS)
    b = Builder()

    # Persistent pieces, front-most first: halftone print texture, logo, then the disclosure,
    # which stays up only while the opening disclaimer sentence is spoken.
    b.image(LIB / "paper" / "halftone-overlay.png", (1080, 1920), 0, dur, (540, 960), name="Halftone overlay")
    b.image(ROOT / "brand" / "logo-small.png", (217, 240), 0, dur, (985, 215), width=96, name="Logo")
    size = label_strip(BRAND["disclosure"], tmp / "disclosure.png", size=30)
    disclaimer_end = next((e for w, _, e in words if re.search(r"[.?!]$", w)), 3000)
    shown = min(dur, max(2500, disclaimer_end + 400))
    dl = b.image(tmp / "disclosure.png", size, 0, shown, (40 + size[0] / 2, 205), rotation=-1, name="Disclosure")
    b.keys(dl, "opacity", [(shown - 250, 100, LINEAR), (shown, 0, LINEAR)])

    # Karaoke captions: one PNG per spoken word, each up until the next word starts.
    for g in phrases(words):
        texts = [words[i][0] for i in g]
        for k, i in enumerate(g):
            start = 0 if i == 0 else words[i][1]
            end = words[i + 1][1] if i + 1 < len(words) else dur
            path = tmp / f"cap-{i:03d}.png"
            size = caption_png(texts, k, path)
            b.image(path, size, start, end - start, (540, 1420), name=f"Caption {i + 1}")

    # Call to action as a closing title card, then the agent's moments.
    # "Free statement analysis / Link in bio" -> title "free" over the remaining words.
    cta_lines = [re.sub(r"^free\s+", "", l, flags=re.IGNORECASE) for l in BRAND["cta"].split("\n")]
    b.in_moment = True
    title_card(b, {"title": "free", "lines": cta_lines}, cta_start, dur - cta_start, tmp)
    for m, start, length in schedule(script.get("moments", []), words, cta_start):
        BUILDERS[m["type"]](b, m, start, length, tmp)

    for asset, path in b.assets.items():
        tsrct(cfg, "project", "import-asset", "-p", p, "--file", str(path), "--asset-id", asset, "--kind", "image")

    # Avatar three times: matte, cut-out copy (above circles), full plate with audio (bottom).
    def video(lid, name, asset, volume, extra=None):
        layer = {"type": "Video", "id": lid, "name": name,
                 "playback": {"type": "windowed", "inputRange": {"start": 0, "duration": dur},
                              "mapping": {"type": "linear", "input": {"start": 0, "duration": dur},
                                          "output": {"start": 0, "duration": dur}}, "inputOffsetMs": 0},
                 "sourceRange": {"start": 0, "duration": dur}, "sourceIntrinsicDuration": dur, "volume": volume,
                 "transform": {"anchorPoint": [540, 800], "position": [540, 800], "scale": [100, 100],
                               "rotation": 0, "opacity": 100},
                 "source": {"assetId": asset, "fit": "cover", "sourceRect": {"x": 0, "y": 0, "width": W, "height": H}}}
        layer.update(extra or {})
        return layer

    doc_file = v.local / "edit.json"
    tsrct(cfg, "project", "checkout", "-p", p, "-o", str(doc_file))
    doc = json.loads(doc_file.read_text())
    doc["duration"] = dur / 1000
    doc["composition"]["layers"] = (b.front + b.moments[::-1] + [video(3, "Avatar matte", "matte", None),
                                               video(2, "Avatar cutout", "avatar", None, {"trackMatte": {"layer": 3, "mode": "luma"}})]
                                    + b.behind_person[::-1] + [video(1, "Avatar plate", "avatar", 1.0)])
    doc_file.write_text(json.dumps(doc))
    tsrct(cfg, "project", "commit", "-p", p, "--file", str(doc_file))

    # Punch-in zooms: alternate framing at each new sentence, as jump cuts.
    zoom = []
    for n, t in enumerate(sentence_starts(words)):
        zoom.append((t, 112.0 if n % 2 else 100.0, {"type": "hold"}))
    for lid in (1, 2, 3):
        b.keys(lid, "scaleX", zoom)
        b.keys(lid, "scaleY", zoom)

    actions_file = v.local / "actions.json"
    actions_file.write_text(json.dumps(b.actions))
    tsrct(cfg, "project", "apply", "-p", p, "--actions", str(actions_file))

    tsrct(cfg, "preview", "-p", p, "-t", "0.6", "-o", str(v.local / "cover.png"))
    tsrct(cfg, "export", "-p", p, "-o", str(v.local / "final.mp4"), "--resolution", "1080p", "--fps", "30")
