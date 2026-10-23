# Paper II style: breakdown and build plan

Source: a 30.6 s Paper II sample exported from the Captions app (kept privately in
`refs/paper2-sample.mp4`, not in git). Frames reviewed at 2 fps plus full-resolution stills.

## Elements

| # | Element | What it looks like | When | How we build it in Tesseract |
|---|---|---|---|---|
| 1 | Karaoke captions | White rounded pill, dark bold geometric sans (Poppins-like); spoken words dark, upcoming words light gray; 2-4 words per phrase; mid-lower frame | Whole video | Per-word timings from ElevenLabs; one text state per word (spoken/upcoming colors) over a rounded rect; position moves up when a graphic needs the lower area |
| 2 | Torn-paper top banner | Blue crumpled-paper panel over the top ~35%, white torn edge along the bottom; black tape label with one keyword (sans, slight tilt); one topical cutout sticker overlapping the label | ~3 s, early (hook) | Image layers: blue paper texture + torn-edge PNG; rect + text for the tape label; sticker PNG; slide-down/settle keyframes |
| 3 | Keyword tape | Dark distressed tape strip, top of frame, one word in an outlined serif | ~1.5 s, on a key word | Rect with grain/texture image + outlined serif text (stroke style); pop-in keyframes |
| 4 | Full-screen paper title card | Whole frame blue crumpled paper; big serif word (cream, slight gradient); 2-3 embossed label-maker strips (white tape, black monospace caps) appearing one by one; enters with a vintage paper-strip wipe, exits with a blur and a torn-edge wipe from the right | ~3 s, middle | Paper texture image; serif + monospace text on white rects; staggered keyframes; gaussian blur effect on exit; torn-edge wipe PNG sliding across |
| 5 | Torn-edge photo insert | Grayscale photo with torn white edges, top ~45% of frame, slides in from the right with a slight rotation | ~3 s | Image layer (topical photo) with desaturate + torn-edge frame PNG; slide/rotate keyframes |
| 6 | Halftone circle + stickers behind the person | Circular halftone image (clouds/sky) behind the head, 2-3 cutout stickers around it; the person stays in front | ~3 s | Person matte (Robust Video Matting) as track matte; circle image with halftone effect behind the cut-out avatar; sticker PNGs with small float/jitter |
| 7 | Halftone print texture | Faint dot pattern over all footage | Whole video | Halftone/dot overlay image at low opacity, or a posterize/grain effect |
| 8 | Punch-in zooms | Alternates tight and wide framing between phrases; occasional brief blur | Every few seconds | Keyframed scale on the avatar (and its matte) at sentence boundaries |

Rhythm: one graphic moment every ~4-6 s, never two at once, each 1.5-3 s, alternating types.

## How a video gets its moments

The cloud agent adds a `moments` list to `script.json`, choosing type, word to trigger on, and
assets from a fixed library, e.g.:

```json
"moments": [
  {"type": "banner", "at_word": 3, "label": "CARD FEES", "sticker": "card-terminal"},
  {"type": "keyword", "at_word": 18, "word": "Hidden"},
  {"type": "title_card", "at_word": 30, "title": "free", "lines": ["STATEMENT", "ANALYSIS", "LINK IN BIO"]},
  {"type": "halftone_circle", "at_word": 52, "image": "sky", "stickers": ["coins", "receipt"]}
]
```

## Assets to source

- Paper: blue crumpled paper texture, white torn-edge strips (top/bottom/side), vintage
  paper-strip wipe, distressed dark tape, white label-maker tape.
- Halftone dot overlay; a few halftone background images for circles.
- Sticker library (transparent PNG cutouts) for Aria topics: card terminal, credit card,
  receipt, cash, coins, cash register, food truck, coffee cup, burger, storefront, calculator,
  phone with tap-to-pay, delivery bag, kiosk.
- Photo inserts: restaurant counter, café, food truck, salon, retail checkout.
- Fonts (Google Fonts, OFL): Poppins Bold (captions), a display serif for title cards
  (e.g. DM Serif Display), a typewriter mono for label-maker tape (e.g. Special Elite).

All assets must be licensed for commercial use and stored in `brand/paper2/`.
