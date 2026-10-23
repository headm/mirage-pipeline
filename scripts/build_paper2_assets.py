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
        frame = Image.new("RGBA", (1240, 940), (0, 0, 0, 0))
        paper = Image.new("RGBA", frame.size, (250, 248, 242, 255))
        frame.paste(paper, mask=ragged_mask(frame.size, "tblr", depth=18))
        frame.paste(gray, (20, 20), ragged_mask(gray.size, "tblr", depth=8))
        frame.save(dest / (f.stem.removeprefix("photo_") + "-torn.png"))
        print("photo", f.stem)


def circles(src: Path) -> None:
    dest = OUT / "circles"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("circle_*.jpg")):
        im = cover(Image.open(f).convert("RGB"), (900, 900))
        dots = halftone(im)
        toned = ImageOps.colorize(dots, (20, 90, 110), (236, 232, 205))  # teal ink on cream, like the sample
        mask = Image.new("L", (900, 900), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 899, 899), fill=255)
        out = toned.convert("RGBA")
        out.putalpha(mask)
        out.save(dest / (f.stem.removeprefix("circle_") + ".png"))
        print("circle", f.stem)


def paper(src: Path) -> None:
    dest = OUT / "paper"
    dest.mkdir(parents=True, exist_ok=True)
    blue = Image.open(src / "paper_blue-crumpled.jpg").convert("RGB")
    full = duotone(cover(blue, (1080, 1920)), (0, 70, 160), (60, 160, 245))
    full.save(dest / "blue-paper-full.jpg", quality=90)
    print("paper blue-paper-full")

    # Top banner: blue paper with a white torn strip along the bottom edge.
    banner = Image.new("RGBA", (1080, 720), (0, 0, 0, 0))
    banner.paste(full.crop((0, 0, 1080, 720)), (0, 0), ragged_mask((1080, 720), "b", depth=40, step=14))
    white = cover(Image.open(src / "paper_white-crumpled.jpg").convert("RGB"), (1080, 120))
    tear = Image.new("RGBA", (1080, 120), (0, 0, 0, 0))
    tear.paste(white, (0, 0), ragged_mask((1080, 120), "tb", depth=34, step=11))
    banner.alpha_composite(tear, (0, 640))
    banner.save(dest / "banner-top.png")
    print("paper banner-top")

    # Side wipe: a tall torn white edge that slides across the frame.
    wipe = Image.new("RGBA", (260, 1920), (0, 0, 0, 0))
    wipe.paste(cover(Image.open(src / "paper_white-crumpled-2.jpg").convert("RGB"), (260, 1920)),
               (0, 0), ragged_mask((260, 1920), "l", depth=60, step=16))
    wipe.save(dest / "wipe-torn-edge.png")
    print("paper wipe-torn-edge")

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
    ns = Image.new("RGBA", strip.size, (0, 0, 0, 0))
    ns.paste(strip, (0, 0), ragged_mask(strip.size, "tb", depth=16, step=9))
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
    stickers(src, new_session("isnet-general-use"))
    photos(src)
    circles(src)
    paper(src)
