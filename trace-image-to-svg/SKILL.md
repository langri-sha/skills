---
name: trace-image-to-svg
description: >-
  Use this skill to produce a pixel-faithful SVG vector recreation of a raster
  image (logo, wordmark, icon, glyph art) — real smooth Bezier paths,
  transparent background, no embedded raster, no font dependency. Use it
  whenever a redraw needs to match the source, not merely evoke it. Triggers:
  "trace this PNG to SVG", "vectorize this image/logo", "pixel-perfect SVG from
  a PNG", "convert this wordmark to vector", "recreate this image as clean SVG
  paths".
metadata:
  author: langri-sha
  version: '1.0.0'
  argument-hint: '[input.png] [output.svg]'
---

# Trace Image to SVG

Turn an antialiased raster (PNG) into clean, smooth, **pixel-faithful** SVG
Bezier paths.

## The one lesson that matters

**Do not hand-fit curves to eyeballed measurements.** Reconstructing letterforms
by placing control points from stroke-width/edge samples produces a _stylized
approximation_ — it will look "nothing like the input" and score ~0.89 IoU even
after heavy effort. Pixel-perfect requires **tracing the actual bitmap**, not
redrawing it.

The second lesson: **the antialiasing is the signal, not noise.** A source image
encodes each edge's true position to a fraction of a pixel in its gray ramp.
Thresholding to 1-bit throws that away and leaves you tracing pixel staircases
(the classic wobbly-autotrace look). Instead, read the edge straight out of the
coverage ramp with marching squares.

## Method (what the scripts implement)

1. **Coverage map, not threshold.** Normalize luminance to ink-coverage in
   `[0,1]` using the _actual_ background and ink levels. Ink is often not pure
   black (e.g. `#212121`), so a raw 127.5 threshold biases every stroke thinner
   — detect the levels instead.
2. **Subpixel contours.** Upsample the coverage map (bicubic) and run marching
   squares at the `0.5` iso-level. This recovers contours to a fraction of a
   pixel and tracks curvature a 1px grid would cut across.
3. **Corner detection.** Mark vertices where the contour turns sharply (turning
   angle over a small span). Serifs, apexes, and terminals stay crisp; only the
   genuinely smooth runs get curve-fit.
4. **Schneider curve fitting.** Fit each smooth run with the fewest cubic
   Beziers that hold the whole run within a pixel tolerance (least-squares fit
   with fixed endpoint tangents + Newton–Raphson reparameterization, recursive
   split at the worst point).
5. **One even-odd path.** Emit all contours into a single
   `<path fill-rule="evenodd">` so counters and holes (bowls, rings, star
   notches) punch through their parent regardless of winding. (Emitting one
   `<path>` per contour makes holes paint _over_ their parent — a common cause
   of filled-in counters.)
6. **Compact relative encoding.** Round once at emit time and accumulate in the
   rounded space so quantization can't drift across a contour.

## How to run it

Scripts live in `scripts/` beside this file. They need
`pillow numpy scikit-image` (and `cairosvg` for scoring) — install into a venv:

```bash
python3 -m venv /tmp/tracevenv
/tmp/tracevenv/bin/pip install -r scripts/requirements.txt
```

Trace, then score:

```bash
V=/tmp/tracevenv/bin/python
$V scripts/trace.py input.png output.svg           # auto ink/bg + auto viewBox
$V scripts/score.py output.svg                     # reads the sidecar mapping
```

`trace.py` writes `output.svg` plus `output.svg.trace.json` (records the source
PNG and the image→viewBox mapping so `score.py` can align exactly).

### Key flags (`trace.py`)

- `--tol 0.15` — curve error tolerance in **source pixels**. Lower = more
  curves, tighter fit. The accuracy/size knob. 0.10–0.20 is the useful range.
- `--upsample 8` — coverage-map supersample before marching squares. Higher =
  more subpixel accuracy, slower. 8 is the fidelity sweet spot; drop to 4 for
  speed on big images.
- `--decimals 2` — coordinate precision. 1 roughly halves file size for a small
  accuracy cost.
- `--viewbox "OX OY W H"` — override the auto framing to match an existing
  asset's coordinate system (e.g. reuse a repo's `viewBox="0 0 1360 220"` so the
  drop-in replacement renders identically). Auto-frames tight to the ink +
  `--pad` otherwise.
- `--fill '#212121'` — path fill. Defaults to the detected ink color.
- `--title "…"` — adds `<title>` + `role="img"` + `aria-label` for an
  accessible, production-ready file.
- `--bg N` / `--ink N` — override auto luminance detection (0–255) if the image
  is low-contrast or has an unusual background.

## What "pixel-perfect" means here — verify it

Do **not** trust binary IoU; it rounds away the subpixel edge quality that is
the whole point. Score with **coverage MAE at native resolution**: rasterize the
SVG at the PNG's own scale and compare per-pixel ink coverage against the PNG's
antialiased coverage. `score.py` prints:

- `coverage MAE` — mean absolute per-pixel coverage error. The floor is
  image-dependent (ink contrast, antialiasing width); expect low thousandths,
  roughly **0.003–0.006**. You can't beat it without embedding the raster.
- `px >25% off` — pixels off by more than 25% coverage. **The most robust
  signal** (calibration-independent). Should be a handful out of the whole
  frame.
- `max` — worst single-pixel error. Staying ≲0.35 means all error is a 1px edge
  fringe, i.e. no visible artifact.
- `nativeIoU` — reported for reference only.

MAE shifts with the detected ink level, so trust `px >25% off` and `max` as the
absolute quality bar, and use MAE for relative comparison between candidates
(they all share one reference). Pass `--diff out.png`: white interiors with a
faint edge outline is perfect; solid red/blue _inside_ a shape is a real defect
(filled counter, misplaced edge, dropped contour).

Then **look**. Render at 1× (should be indistinguishable from the source) and at
4–9× zoom on the hardest features — tight curves (S spines, bowls), counters and
holes, sharp points (stars, serifs, pointed terminals), and any hairline. The
trace should read as _cleaner_ than the source (no compression mottling inside
strokes) while matching every shape.

Sweep `--tol` (and `--decimals`) to pick the leanest file that stays at the
floor; the knee is usually around `--tol 0.15`.

## Deliverable checklist

- Real vector paths — **no** embedded `<image>`/base64, **no** `<text>`/font
  dependency, **no** background `<rect>` (transparent).
- Single even-odd `<path>`; counters/holes render correctly.
- viewBox matches the consuming markup's expected width/height (no aspect-ratio
  reflow) when replacing an existing asset.
- Scored at the noise floor and visually verified at zoom.
- If replacing a file in a repo, preserve unrelated work and confirm the served
  bytes match after install.

## Notes

- A native `potrace`/`potracer` pass is a useful sanity baseline, but it traces
  a hard threshold — it hits ~0.99 IoU yet balloons to thousands of segments
  (the staircase problem) and still bakes in the thinning bias. The
  coverage-map + Schneider path here is both smoother and leaner.
- `potracer` (pure-Python) **inverts** its input mask on construction: pass the
  background-true mask (`gray >= level`) if you use it as a baseline.
