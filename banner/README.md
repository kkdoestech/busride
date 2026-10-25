# The README banner

`docs/banner.gif` at the top of the README is a three.js scene, recorded frame by frame. The same
scene runs live at <https://kkdoestech.github.io/busride/> (deployed from `site/` by
`.github/workflows/pages.yml`).

## Rebuild it

You need Node 20+ and [uv](https://docs.astral.sh/uv/). From this folder:

```sh
npm install                                                       # Playwright, once
npm run record                                                    # 100 frames -> .frames/
uv run --with pillow --with numpy python encode.py                # -> docs/banner.gif + docs/banner.png
```

`npm run serve` shows the live page on <http://127.0.0.1:8173/>. To check one moment,
`npm run stills -- 2.3 3.6` writes `.frames/stills/t2.30.png` and `t3.60.png`.

## What happens (one 6 s loop, 900×300, 60 ms frames)

The magic plays on the left. The title, tagline and status row on the right are always readable;
the title burns the whole time and glitches in short bursts.

| Time | Beat |
| --- | --- |
| 0–0.5 s | The avatar holds the deck. Status: "4 calls · 52 cards". |
| 0.5–1.3 s | **The book of 52.** He tosses the deck; it opens like a book, each card turning over like a page. |
| 1.05–3.4 s | **The pulsar.** A red circle draws itself, he glows red with an orb in his hands, and a pulsar lights up in front of the circle: spiral arms, sweeping beams, streaks falling in. It pulls every card off the book and down its spiral, shrinking and stretching. Status: "pulsar eating 17/52". |
| 3.4–3.6 s | It collapses... |
| 3.6 s | **BOOM.** Flash, shockwave, a screen-wide glitch, the camera shakes and the title blazes. |
| 3.6–4.8 s | **The deal.** Four cards fly out of the explosion into the slots on the right and flip face up: a winning ride (7♥, Q♠, 9♦, 3♣). Under each, its odds count up: 50.0%, 36.2%, 23.8%, 6.3%. Status: "dealing 1/4" to "4/4". |
| 4.8–5.35 s | **Solved.** He hops, a hot band sweeps the title. Status: "solved ✓ exact odds". |
| 5.35–6 s | Every card streams back into his hands, and the loop starts again on exactly the first frame. |

The odds are the spec's known survival values for perfect play (0.50000, 0.36199, 0.23771,
0.06307; `docs/SPEC.md`), drawn in gold, not green or red, so the banner never clashes with the
app's rule that colour means expected value.

## Credits

The avatar (`site/avatar.png`) and the pulsar's look come from the
[kkdoestech profile](https://github.com/kkdoestech/kkdoestech): `assets/avatars/2.png` and
`tools/make_pulsar.py` (three log-spiral arms, lighthouse beams, a pulsing core, streaks falling in).

## How it works

- Every frame is a pure function of time (`site/util.js`): no clocks, and randomness only from a
  seeded generator. A recording is reproducible and frame 6 s is pixel-identical to frame 0.
- `?record` gives a fixed 900×300 page at 2× pixels that draws only when `record.mjs` asks.
- `site/pulsar.js` draws the pulsar in a shader; `site/cards.js` draws the 52 faces on a canvas and
  moves each card from the hands to the book, down the spiral, into a slot and home again;
  `site/hud.js` draws the words, the title's fire and its glitch; `site/glitch.js` is the
  screen-wide glitch.
- `encode.py` shrinks the frames to 900×300, picks one palette for the whole loop, and stores in
  each frame only the pixels that changed, which keeps the GIF under 6 MB.
