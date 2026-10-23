"""Build the Paper II asset library in brand/paper2/ from the downloaded Pexels originals.

    python scripts/build_paper2_assets.py work/assets/originals

Originals are named <kind>_<name>.jpg (kind: sticker, photo, circle, paper). Stickers are
cut out with rembg; paper pieces (torn edges, tape, label strips) are cut from the paper
photos with generated ragged edges; the halftone overlay is generated from scratch.
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from rembg import new_session, remove

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "paper2"
ARIA_BLUE = (0, 126, 229)
random.seed(7)  # same ragged edges on every rebuild


def fit_width(im: Image.Image, width: int) -> Image.Image:
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


def cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(im, size, Image.LANCZOS)


def duotone(im: Image.Image, dark: tuple, light: tuple) -> Image.Image:
    return ImageOps.colorize(ImageOps.autocontrast(im.convert("L"), cutoff=1), dark, light)


def halftone(im: Image.Image, cell: int = 9) -> Image.Image:
    """Print-style dot screen: dot radius follows darkness."""
    gray = im.convert("L")
    out = Image.new("L", gray.size, 255)
    d = ImageDraw.Draw(out)
    small = gray.resize((gray.width // cell, gray.height // cell))
    for y in range(small.height):
        for x in range(small.width):
            r = (1 - small.getpixel((x, y)) / 255) * cell * 0.62
            if r > 0.4:
                cx, cy = x * cell + cell / 2, y * cell + cell / 2
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    return out


def ragged_mask(size: tuple[int, int], edges: str, depth: int = 14, step: int = 9) -> Image.Image:
    """Alpha mask with torn edges on the given sides ('t', 'b', 'l', 'r')."""
    w, h = size
    pts = []
    def jag(n):
        return [random.randint(0, depth) for _ in range(n)]
    top = jag(w // step + 2) if "t" in edges else [0] * (w // step + 2)
    bottom = jag(w // step + 2) if "b" in edges else [0] * (w // step + 2)
    left = jag(h // step + 2) if "l" in edges else [0] * (h // step + 2)
    right = jag(h // step + 2) if "r" in edges else [0] * (h // step + 2)
    pts += [(i * step, top[i]) for i in range(w // step + 1)] + [(w, top[-1])]
    pts += [(w - right[i], i * step) for i in range(h // step + 1)] + [(w - right[-1], h)]
    pts += [(w - i * step, h - bottom[i]) for i in range(w // step + 1)] + [(0, h - bottom[-1])]
    pts += [(left[i], h - i * step) for i in range(h // step + 1)]
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(0.8))


# Crop boxes (fractions of width/height) for originals that hold more than the one object we want.
CROPS = {"burger": (0.25, 0.0, 1.0, 0.27), "cash-bills": (0.0, 0.18, 1.0, 1.0),
         "phone-pay": (0.15, 0.0, 0.9, 0.72)}


def stickers(src: Path, session) -> None:
    dest = OUT / "stickers"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("sticker_*.jpg")):
        name = f.stem.removeprefix("sticker_")
        im = Image.open(f).convert("RGB")
        if name in CROPS:
            l, t, r, b = CROPS[name]
            im = im.crop((int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))
        cut = remove(fit_width(im, 1400), session=session)
        # Drop faint leftovers from the background, keep soft edges on the object.
        alpha = cut.getchannel("A").point(lambda a: 0 if a < 90 else a)
        cut.putalpha(alpha)
        cut = cut.crop(cut.getbbox())
        cut.thumbnail((800, 800), Image.LANCZOS)
        cut.save(dest / (name + ".png"))
        print("sticker", f.stem)


def photos(src: Path) -> None:
    dest = OUT / "photos"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("photo_*.jpg")):
        im = cover(Image.open(f).convert("RGB"), (1200, 900))
        im.save(dest / (f.stem.removeprefix("photo_") + ".jpg"), quality=88)
        # Grayscale variant with torn white border, as in the Paper II photo inserts.
        gray = ImageOps.grayscale(im).convert("RGB")
        white = Image.open(src / "paper_white-crumpled.jpg")
        frame = Image.new("RGBA", (1200 + 120, 900 + 120), (0, 0, 0, 0))
        frame.paste(gray, (60, 60))
        for k, side in enumerate(("bottom", "right", "top", "left")):
            frame = tear_side(frame, white, side, margin=90, seed=50 + 7 * k, big=22, mid=10, core=(10, 28), shadow=0.3)
        frame.save(dest / (f.stem.removeprefix("photo_") + "-torn.png"))
        print("photo", f.stem)


CIRCLE_INK, CIRCLE_PAPER = (20, 96, 120), (242, 238, 220)  # teal ink on cream, like the sample


def circle_treatment(gray: Image.Image) -> Image.Image:
    """Soft, light duotone underneath a fine dot screen. Dots alone (coarse, two-tone) turned
    anything busy into a blob; the tone underneath keeps shapes readable at video size."""
    gray = ImageOps.autocontrast(gray, cutoff=1)
    tone = ImageOps.colorize(gray.point(lambda v: 150 + v * 105 // 255), CIRCLE_INK, CIRCLE_PAPER)
    dots = ImageOps.colorize(halftone(gray, cell=5), CIRCLE_INK, CIRCLE_PAPER)
    dots = Image.blend(Image.new("RGB", dots.size, CIRCLE_PAPER), dots, 0.6)
    return ImageChops.multiply(tone, dots).point(lambda v: min(255, int(v * 1.06)))


def circle_mask(im: Image.Image) -> Image.Image:
    mask = Image.new("L", (900, 900), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 899, 899), fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def circles(src: Path, session) -> None:
    """circle_*.jpg: the whole photo (simple subjects such as sky). circlecut_*.jpg: the object
    is cut out and set in the upper part of a light disc, because in the edit the speaker's head
    covers the disc's lower half."""
    dest = OUT / "circles"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("circle_*.jpg")):
        im = ImageOps.grayscale(cover(Image.open(f).convert("RGB"), (900, 900)))
        circle_mask(circle_treatment(im)).save(dest / (f.stem.removeprefix("circle_") + ".png"))
        print("circle", f.stem)
    for f in sorted(src.glob("circlecut_*.jpg")):
        cut = remove(fit_width(Image.open(f).convert("RGB"), 1400), session=session)
        alpha = cut.getchannel("A").point(lambda a: 0 if a < 90 else a)
        cut, alpha = cut.crop(alpha.getbbox()), alpha.crop(alpha.getbbox())
        gray = ImageOps.autocontrast(ImageOps.grayscale(cut.convert("RGB")), cutoff=1)
        obj = Image.merge("RGBA", (gray, gray, gray, alpha))
        obj.thumbnail((620, 500), Image.LANCZOS)
        disc = Image.new("RGBA", (900, 900), (238, 238, 238, 255))
        disc.alpha_composite(obj, ((900 - obj.width) // 2, 60))
        circle = circle_treatment(ImageOps.grayscale(disc.convert("RGB")))
        circle_mask(circle).save(dest / (f.stem.removeprefix("circlecut_") + ".png"))
        print("circle", f.stem)


PAPER_BLUE = (40, 101, 192)  # measured from the Paper II sample's title card


def noise_field(size: tuple[int, int], blur: float, seed: int) -> Image.Image:
    """Smooth random field in 0..255, built small and scaled up so large blotches stay cheap."""
    rnd = random.Random(seed)
    w, h = size
    k = max(1, int(blur / 4))
    small = Image.new("L", (w // k + 1, h // k + 1))
    small.putdata([rnd.randint(0, 255) for _ in range(small.width * small.height)])
    field = small.resize(size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(blur / 2))
    return ImageOps.autocontrast(field)


def blue_paper(src: Path, size: tuple[int, int] = (1080, 1920)) -> Image.Image:
    """Matte royal-blue paper like the sample: faceted crumple shading (softened, no gloss),
    broad mottling, fibre speckle, a printed dot screen and a few white fibre flecks."""
    import numpy as np
    w, h = size
    def field(img):  # 0..255 image -> -1..1 array
        a = np.asarray(img, dtype=np.float32) / 127.5 - 1
        return a / max(1e-6, np.abs(a).max())
    photo = Image.open(src / "paper_white-crumpled.jpg")
    zoom = photo.crop((int(photo.width * 0.3), int(photo.height * 0.2), int(photo.width * 0.7), int(photo.height * 0.8)))
    crumple = ImageOps.autocontrast(ImageOps.grayscale(cover(zoom, size)), cutoff=2)  # zoomed in: fewer, bigger folds
    facets = field(crumple.filter(ImageFilter.GaussianBlur(1.6)))
    facets = np.clip(facets * 1.4, -1, 1)                       # flatten the brightest highlights
    blotches = field(noise_field(size, 260, 1))
    mottling = field(noise_field(size, 40, 2))
    speckle = field(noise_field(size, 1.0, 3))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    vignette = -np.clip(((xx / w - 0.5) ** 2 * 1.6 + (yy / h - 0.5) ** 2 * 1.2) * 1.4 - 0.08, 0, 1)
    lum = 0.24 * facets + 0.26 * blotches + 0.08 * mottling + 0.12 * speckle + 0.35 * vignette

    # Shade between a deep and a pale, slightly greyed blue; the midpoint is the sample's PAPER_BLUE.
    dark = np.array((16, 60, 172), dtype=np.float32)
    light = np.array((68, 140, 236), dtype=np.float32)
    t = np.clip(0.5 + lum * 1.1, 0, 1)[..., None]
    rgb = dark * (1 - t) + light * t

    # Printed dot screen: darker dots on a 10 px diagonal grid.
    dots = Image.new("L", size, 0)
    d = ImageDraw.Draw(dots)
    jitter = random.Random(5)
    for y in range(0, h, 10):
        for x in range((y // 10) % 2 * 5, w, 10):
            r = 3.4 + jitter.uniform(-0.6, 0.6)
            d.ellipse((x, y, x + r, y + r), fill=jitter.randint(170, 255))
    dot = np.asarray(dots.filter(ImageFilter.GaussianBlur(0.7)), dtype=np.float32)[..., None] / 255
    rgb = rgb * (1 - 0.18 * dot)

    # Light fibre speckle and a few short white flecks.
    rnd = random.Random(4)
    flecks = Image.new("L", size, 0)
    fd = ImageDraw.Draw(flecks)
    for _ in range(1600):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        fd.point((x, y), fill=rnd.randint(40, 120))
    for _ in range(12):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        fd.line((x, y, x + rnd.randint(-40, 40), y + rnd.randint(-12, 12)), fill=rnd.randint(110, 190), width=2)
    f = np.asarray(flecks.filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float32)[..., None] / 255
    rgb = rgb * (1 - f) + np.array([200, 222, 245], dtype=np.float32) * f
    return Image.fromarray(rgb.astype(np.uint8))


def tear_profile(width: int, base: float, seed: int, big: float, mid: float, fine: float) -> "np.ndarray":
    """y of a torn edge for every x: slow wandering + medium wobble + fine fibre jitter, no repeats."""
    import numpy as np
    rnd = np.random.default_rng(seed)
    x = np.arange(width, dtype=np.float32)
    y = np.full(width, base, dtype=np.float32)
    for wl in (720, 410, 260):                       # slow wandering, random phases
        y += big / 3 * np.sin(2 * np.pi * x / wl + rnd.uniform(0, 2 * np.pi))
    walk = np.cumsum(rnd.normal(0, 1, width))        # irregular medium wobble
    walk = np.convolve(walk - np.linspace(walk[0], walk[-1], width), np.ones(25) / 25, mode="same")
    y += mid * walk / max(1e-6, np.abs(walk).max())
    y += rnd.normal(0, fine, width)                  # fibre-scale jitter
    return y


# Rotation (counter-clockwise degrees) that turns the given side into the bottom edge.
TO_BOTTOM = {"bottom": 0, "right": -90, "top": 180, "left": 90}


def tear_side(img: Image.Image, white_src: Image.Image, side: str, margin: int, seed: int,
              big: float = 60, mid: float = 26, core: tuple[float, float] = (26, 72),
              shadow: float = 0.40) -> Image.Image:
    """Tear one side of an RGBA piece, like the Paper II sample: the surface tears back to a white
    fibrous core with jagged peaks, both edges of the core are fuzzy, and a soft shadow falls
    outward. `margin` is how far in from that side the tear runs; everything beyond it becomes
    transparent, so the layer's edge is the tear itself, never a straight cut."""
    import numpy as np
    angle = TO_BOTTOM[side]
    rot = img.convert("RGBA").rotate(angle, expand=True)
    w, h = rot.size
    yy = np.arange(h, dtype=np.float32)[:, None]
    lo, hi = core
    blue_edge = tear_profile(w, h - margin, seed, big=big, mid=mid, fine=0.2) + np.linspace(-big / 3, big / 3, w)
    width = (lo + hi) / 2 + (hi - lo) / 4 * np.sin(np.arange(w) / 83.0 + seed) + (hi - lo) / 8 * np.sin(np.arange(w) / 29.0)
    white_edge = blue_edge + np.clip(width, lo, hi) + tear_profile(w, 0, seed + 1, big=big / 4, mid=mid / 2, fine=0.3)

    fuzz = np.asarray(noise_field((w, h), 1.0, seed + 2), dtype=np.float32) / 255 - 0.5
    clumps = np.asarray(noise_field((w, h), 3.0, seed + 3), dtype=np.float32) / 255 - 0.5

    def soft(edge, amount):
        return np.clip((edge[None, :] - yy) / 1.5 + (0.15 * fuzz + clumps) * amount, 0, 1)

    src = np.asarray(rot, dtype=np.float32)
    src_rgb, src_a = src[..., :3], src[..., 3] / 255
    # The core only exists where the piece exists across the tear (not past its other edges).
    across = np.clip(src_a.max(axis=0, keepdims=True), 0, 1)
    surf_a = soft(blue_edge, 5.0) * src_a
    core_a = soft(white_edge, 9.0) * across * (1 - soft(blue_edge, 5.0) * (1 - src_a))

    sh = Image.fromarray((core_a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(8))
    shadow_a = np.roll(np.asarray(sh, dtype=np.float32) / 255, 8, axis=0) * shadow

    tex = np.asarray(ImageOps.grayscale(cover(white_src, (w, h))), dtype=np.float32)
    tex = (tex - tex.mean()) / max(1e-6, tex.std())
    lip = np.clip(1 - (yy - blue_edge[None, :]) / 10, 0, 1) * np.clip((yy - blue_edge[None, :]) / 2 + 1, 0, 1)
    shade = 240 + tex * 6 - lip * 18
    white_rgb = np.dstack([shade + 2, shade, shade - 4])

    rgb = white_rgb * core_a[..., None]
    a = core_a + shadow_a * (1 - core_a)
    rgb = rgb * (1 - surf_a[..., None]) + src_rgb * surf_a[..., None]
    a = surf_a + a * (1 - surf_a)
    rgb = np.where(a[..., None] > 1e-3, rgb / np.maximum(a[..., None], 1e-3), 0)
    out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.clip(a, 0, 1) * 255]).astype(np.uint8), "RGBA")
    return out.rotate(-angle, expand=True)


def torn_banner(paper: Image.Image, white_src: Image.Image, size: tuple[int, int] = (1080, 900)) -> Image.Image:
    """Top banner: blue paper torn across the bottom, transparent below the tear."""
    return tear_side(paper.crop((0, 0) + size), white_src, "bottom", margin=size[1] - 620, seed=11)


def torn_card(paper: Image.Image, white_src: Image.Image, pad: int = 230) -> Image.Image:
    """Full-screen card torn down its left and right edges. The canvas is `pad` wider on each side
    so the tears sit just offscreen when the card is centred, and lead/trail when it slides."""
    assert paper.width == 1080 + 2 * pad, "generate the paper 2 * pad wider than the frame"
    wide = tear_side(paper.convert("RGBA"), white_src, "right", margin=pad - 90, seed=31)
    return tear_side(wide, white_src, "left", margin=pad - 90, seed=37)


def paper(src: Path) -> None:
    dest = OUT / "paper"
    dest.mkdir(parents=True, exist_ok=True)
    full = blue_paper(src)
    full.save(dest / "blue-paper-full.jpg", quality=92)
    wide = blue_paper(src, size=(1080 + 2 * 230, 1920))
    white_photo = Image.open(src / "paper_white-crumpled.jpg")
    torn_card(wide, white_photo).save(dest / "blue-paper-card.png")
    print("paper blue-paper-card")
    print("paper blue-paper-full")

    # Top banner: blue paper torn along the bottom; the layer's alpha follows the tear itself.
    torn_banner(full, white_photo).save(dest / "banner-top.png")
    print("paper banner-top")


    # Tape strips and label-maker strips.
    black = Image.open(src / "paper_black-crumpled.jpg").convert("RGB")
    for i, (x, y) in enumerate([(100, 300), (400, 900)]):
        strip = ImageOps.grayscale(cover(black.crop((x, y, x + 1200, y + 260)), (900, 170))).convert("RGB")
        tape = Image.new("RGBA", strip.size, (0, 0, 0, 0))
        tape.paste(strip, (0, 0), ragged_mask(strip.size, "lr", depth=12, step=7))
        tape.save(dest / f"tape-black-{i + 1}.png")
    # Label-maker tape: near-white with a faint paper grain, so black text reads clearly.
    grain = ImageOps.grayscale(cover(Image.open(src / "paper_white-crumpled.jpg"), (700, 70)))
    label = Image.merge("RGB", [grain.point(lambda v: 236 + v * 18 // 255)] * 3)
    lab = Image.new("RGBA", label.size, (0, 0, 0, 0))
    lab.paste(label, (0, 0), ragged_mask(label.size, "lr", depth=4, step=5))
    lab.save(dest / "label-white.png")
    news = Image.open(src / "paper_newspaper.jpg").convert("RGB")
    strip = ImageOps.colorize(ImageOps.grayscale(cover(news, (1400, 200))), (60, 40, 30), (235, 220, 190))
    ns = Image.new("RGBA", (strip.width, strip.height + 120), (0, 0, 0, 0))
    ns.paste(strip, (0, 60))
    ns = tear_side(ns, white_photo, "bottom", margin=80, seed=41, big=20, mid=10, core=(8, 22), shadow=0.3)
    ns = tear_side(ns, white_photo, "top", margin=80, seed=43, big=20, mid=10, core=(8, 22), shadow=0.3)
    ns.save(dest / "strip-newspaper.png")
    print("paper tape, label, newspaper strip")

    # Halftone overlay for the whole frame (generated, no source).
    dots = Image.new("L", (1080, 1920), 0)
    d = ImageDraw.Draw(dots)
    for y in range(0, 1920, 6):
        for x in range((y // 6) % 2 * 3, 1080, 6):
            d.ellipse((x, y, x + 1.6, y + 1.6), fill=255)
    overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    overlay.putalpha(dots.point(lambda v: v * 0.22))
    overlay.save(dest / "halftone-overlay.png")
    print("paper halftone-overlay")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    session = new_session("isnet-general-use")
    stickers(src, session)
    photos(src)
    circles(src, session)
    paper(src)
