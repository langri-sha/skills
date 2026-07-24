#!/usr/bin/env python3
"""Grade a traced SVG against its source PNG the way it is actually seen.

"Pixel perfect" is measured as coverage MAE at the PNG's native resolution:
rasterize the SVG at source scale and compare per-pixel ink coverage against
the PNG's own antialiased coverage. Binary IoU rounds away the subpixel edge
quality that is the whole point, so it is reported only for reference.

Reads the mapping (source PNG + image->viewBox origin/size + bg/ink levels)
from the SVG's sidecar <svg>.trace.json written by trace.py, or from explicit
flags.

Deps: cairosvg pillow numpy   (see requirements.txt)

    python score.py OUTPUT.svg [--diff OUTPUT.diff.png]
    python score.py OUT.svg --png src.png --origin "OX OY" --view "W H" \
        [--bg 248 --ink 33]
"""
import argparse
import json
import os
import sys

import cairosvg
import numpy as np
from PIL import Image


def load_mapping(svg, args):
    side = svg + '.trace.json'
    m = {}
    if os.path.exists(side):
        with open(side) as f:
            m = json.load(f)
    if args.png:
        m['png'] = args.png
    if args.origin:
        m['origin'] = [float(x) for x in args.origin.split()]
    if args.view:
        m['view'] = [int(float(x)) for x in args.view.split()]
    if args.bg is not None:
        m['bg'] = args.bg
    if args.ink is not None:
        m['ink'] = args.ink
    for k in ('png', 'origin', 'view'):
        if k not in m:
            sys.exit(f'missing {k}: no sidecar {side} and no --{k} given')
    m.setdefault('bg', 248.0)
    m.setdefault('ink', 33.0)
    return m


def coverage_ref(m):
    a = np.array(Image.open(m['png']).convert('L'), dtype=float)
    cov = np.clip((m['bg'] - a) / (m['bg'] - m['ink']), 0, 1)
    ox, oy = m['origin']
    w, h = m['view']
    ox, oy = int(round(ox)), int(round(oy))
    return cov[oy:oy + h, ox:ox + w]


def render(svg, w, h, scale):
    cairosvg.svg2png(url=svg, write_to='_score_tmp.png',
                     output_width=w * scale, output_height=h * scale)
    return np.array(Image.open('_score_tmp.png').convert('RGBA'))[:, :, 3] / 255.0


def score(svg, m, scale=1, diff_out=None):
    ref = coverage_ref(m)
    w, h = m['view']
    got = render(svg, w, h, scale)
    if got.shape != ref.shape:  # guard against off-by-one from rounding
        h2, w2 = min(got.shape[0], ref.shape[0]), min(got.shape[1], ref.shape[1])
        got, ref = got[:h2, :w2], ref[:h2, :w2]
    err = np.abs(got - ref)
    mae = err.mean()
    bad = int((err > 0.25).sum())
    worst = float(err.max())
    mm, rr = got > 0.5, ref > 0.5
    iou = (mm & rr).sum() / max(1, (mm | rr).sum())
    print(f'{svg}: coverage MAE={mae:.5f}  px>25% off={bad}  '
          f'max={worst:.2f}  nativeIoU={iou:.5f}  '
          f'(ink {int(rr.sum())}px in {w}x{h})')
    if diff_out:
        vis = np.zeros(ref.shape + (3,), dtype=np.uint8)
        vis[:, :, 0] = np.clip((ref - got) * 510, 0, 255)   # red: SVG too thin
        vis[:, :, 2] = np.clip((got - ref) * 510, 0, 255)   # blue: SVG too fat
        Image.fromarray(255 - vis).save(diff_out)
        print(f'  wrote diff -> {diff_out}')
    return mae


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('svg')
    ap.add_argument('--png', default=None)
    ap.add_argument('--origin', default=None, help='"OX OY"')
    ap.add_argument('--view', default=None, help='"W H"')
    ap.add_argument('--bg', type=float, default=None)
    ap.add_argument('--ink', type=float, default=None)
    ap.add_argument('--diff', default=None, help='write a red/blue diff PNG')
    a = ap.parse_args()
    score(a.svg, load_mapping(a.svg, a), diff_out=a.diff)


if __name__ == '__main__':
    main()
