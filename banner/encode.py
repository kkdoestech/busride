"""Turn the recorded frames into the README banner.

    uv run --with pillow --with numpy python banner/encode.py

Reads banner/.frames/ (from `npm run record`) and writes docs/banner.gif, the looping banner,
and docs/banner.png, a still of the solved moment for reduced motion and link previews.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "banner" / ".frames"
DOCS = ROOT / "docs"
SIZE = (900, 300)
POSTER_T = 5.2  # seconds into the loop: all four cards dealt, the title still warm
CLEAR = 255  # palette index kept for "same as the last frame"
TOLERANCE = 15  # summed RGB difference below which a pixel is left as it was
# The prompt, the repo name, the gold odds, the red status and the cream text (see site/hud.js).
SWATCHES = ["#7dd3fc", "#fbbf24", "#f2c45c", "#ff5f5f", "#e5383b", "#f4e9d8", "#b8ab9c", "#a89a8a"]
GIF_BUDGET = 6_000_000
PNG_BUDGET = 400_000


def main() -> None:
    meta = json.loads((FRAMES / "meta.json").read_text())
    paths = sorted(FRAMES.glob("[0-9][0-9][0-9][0-9].png"))
    if len(paths) != meta["frames"]:
        raise SystemExit(f"expected {meta['frames']} frames in {FRAMES}, found {len(paths)}")
    frames = [Image.open(p).convert("RGB").resize(SIZE, Image.Resampling.LANCZOS) for p in paths]

    # One 255-colour palette for the whole loop, from a sheet of sample frames plus swatches of
    # the small text colours, which would otherwise lose their slot to the big dark areas.
    sample = frames[:: max(1, len(frames) // 24)]
    sheet = Image.new("RGB", (SIZE[0], SIZE[1] * (len(sample) + 1)))
    for i, f in enumerate(sample):
        sheet.paste(f, (0, SIZE[1] * i))
    step = SIZE[0] // len(SWATCHES)
    top = SIZE[1] * len(sample)
    for i, colour in enumerate(SWATCHES):
        sheet.paste(ImageColor.getrgb(colour), (i * step, top, (i + 1) * step, sheet.height))
    palette_img = sheet.quantize(CLEAR, method=Image.Quantize.MEDIANCUT)
    flat = palette_img.getpalette()[: CLEAR * 3]
    flat += [0, 0, 0] * (256 - len(flat) // 3)

    # Each frame stores only the pixels whose source colour moved since they were last stored;
    # the rest are transparent, so the previous frame shows through and the GIF stays small.
    out: list[Image.Image] = []
    sent = None
    for f in frames:
        dithered = f.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
        idx = np.array(dithered, np.uint8)
        target = np.array(f, np.int16)
        if sent is None:
            sent = target
        else:
            changed = np.abs(target - sent).sum(axis=2) > TOLERANCE
            sent[changed] = target[changed]
            idx = np.where(changed, idx, CLEAR).astype(np.uint8)
        img = Image.fromarray(idx, "P")
        img.putpalette(flat)
        out.append(img)

    fps = meta["fps"]
    durations = [round((i + 1) * 1000 / fps) - round(i * 1000 / fps) for i in range(len(frames))]
    gif = DOCS / "banner.gif"
    out[0].save(
        gif,
        save_all=True,
        append_images=out[1:],
        duration=durations,
        loop=0,
        disposal=1,
        transparency=CLEAR,
        optimize=False,
    )

    png = DOCS / "banner.png"
    frames[round(POSTER_T * fps)].save(png, optimize=True)

    for path, budget in ((gif, GIF_BUDGET), (png, PNG_BUDGET)):
        size = path.stat().st_size
        verdict = "ok" if size <= budget else f"OVER the {budget / 1e6:.1f} MB budget"
        print(f"{path.relative_to(ROOT)}  {size / 1e6:.2f} MB  {verdict}")


if __name__ == "__main__":
    main()
