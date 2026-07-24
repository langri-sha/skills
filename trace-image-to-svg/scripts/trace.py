#!/usr/bin/env python3
"""Trace an antialiased raster image to clean, smooth, pixel-faithful SVG paths.

This is faithful vectorization for logos / wordmarks / icons — NOT a stylized
redraw. It reads subpixel edge positions straight out of the source
antialiasing (marching squares on an ink-coverage map), detects corners by
turning angle so serifs/apexes stay crisp, and fits each smooth run with
Schneider's algorithm (the fewest cubic Beziers that hold the run within a
pixel tolerance). All contours go into one even-odd <path> so counters and
holes punch through their parent.

Writes OUTPUT.svg plus OUTPUT.svg.trace.json (the source PNG + image->viewBox
mapping) so score.py can align and grade the result.

Deps: pillow numpy scikit-image   (see requirements.txt)

    python trace.py INPUT.png OUTPUT.svg [options]

See --help. The two knobs that matter: --tol (fit tightness, in source pixels)
and --upsample (subpixel accuracy vs speed).
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image
from skimage import measure

# --- globals set by main() before build() runs ---------------------------
PNG = None
ORIGIN = (0.0, 0.0)   # image px -> viewBox px (subtract this)
VIEW = (0, 0)         # viewBox width, height
BG = 248.0            # background luminance
INK = 33.0            # solid-ink luminance
DEC = 2               # emitted coordinate decimals


# ----------------------------------------------------------------- detect
def detect_levels(a, bg=None, ink=None):
    """Background and solid-ink luminance.

    Background = median of the border ring. Ink = the modal luminance of the
    inked side (the solid-stroke plateau), NOT an extreme percentile: stroke
    interiors dominate the dark pixels and cluster tightly at the true ink
    value, whereas a low percentile chases the darkest antialiasing/JPEG
    outliers and biases the coverage reference too dark.
    """
    if bg is None:
        border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        bg = float(np.median(border))
    if ink is None:
        mid = (bg + float(a.min())) / 2.0
        dark = np.round(a[a <= mid]).astype(int)
        dark = dark[(dark >= 0) & (dark <= 255)]
        ink = float(np.argmax(np.bincount(dark, minlength=256))) if len(dark) \
            else float(a.min())
    if ink >= bg:                      # light-on-dark: swap sense
        ink, bg = bg, ink
    return bg, ink


def ink_color(rgb, cov):
    """Median RGB of the solidly-inked pixels -> default fill color."""
    solid = cov >= 0.5
    if not solid.any():
        return '#000000'
    med = np.median(rgb[solid], axis=0).astype(int)
    return '#%02x%02x%02x' % tuple(med)


def coverage(a):
    return np.clip((BG - a) / (BG - INK), 0, 1)


# ----------------------------------------------------------------- contours
def contours(upsample=8):
    """Subpixel closed contours at 50% ink coverage, in image-pixel coords.

    Operates on a coverage map (not raw luminance): ink is frequently not pure
    black, so the half-coverage edge sits at (BG+INK)/2 and a raw 127.5
    threshold biases strokes thinner. The map is upsampled first so marching
    squares can track curvature a 1px grid would cut across.
    """
    im = Image.open(PNG).convert('L')
    if upsample != 1:
        im = im.resize((im.width * upsample, im.height * upsample),
                       Image.BICUBIC)
    cov = coverage(np.array(im, dtype=float))
    out = []
    for c in measure.find_contours(cov, 0.5):
        pts = np.column_stack((c[:, 1], c[:, 0])) / upsample  # (r,c)->(x,y)
        if len(pts) > 3 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) >= 8:
            out.append(pts)
    return out


def resample(pts, step=1.0):
    """Arc-length resample so the fitter sees evenly spaced samples."""
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    n = max(16, int(round(total / step)))
    u = np.linspace(0, total, n, endpoint=False)
    x = np.interp(u, s, closed[:, 0])
    y = np.interp(u, s, closed[:, 1])
    return np.column_stack((x, y))


def smooth_closed(pts, passes=0, w=0.25):
    """Optional light Laplacian pass to shed sampling ripple. Off by default;
    at high upsample the contour is already smooth and this only rounds
    extremes."""
    for _ in range(passes):
        prev = np.roll(pts, 1, axis=0)
        nxt = np.roll(pts, -1, axis=0)
        pts = (1 - 2 * w) * pts + w * (prev + nxt)
    return pts


# ------------------------------------------------------------------ corners
def corners(pts, span=3, thresh_deg=38):
    """Indices where the contour turns sharply enough to be a real corner."""
    n = len(pts)
    a = pts[np.arange(n) - span]
    b = pts[(np.arange(n) + span) % n]
    v1 = pts - a
    v2 = b - pts
    n1 = np.linalg.norm(v1, axis=1)
    n2 = np.linalg.norm(v2, axis=1)
    ok = (n1 > 1e-9) & (n2 > 1e-9)
    cos = np.ones(n)
    cos[ok] = np.clip((v1[ok] * v2[ok]).sum(1) / (n1[ok] * n2[ok]), -1, 1)
    ang = np.degrees(np.arccos(cos))
    cand = np.where(ang > thresh_deg)[0]
    if not len(cand):
        return []
    picked, run = [], [cand[0]]
    for i in cand[1:]:
        if i - run[-1] <= span:
            run.append(i)
        else:
            picked.append(max(run, key=lambda k: ang[k]))
            run = [i]
    picked.append(max(run, key=lambda k: ang[k]))
    if len(picked) > 1 and picked[0] == 0 and (n - picked[-1]) <= span:
        picked.pop()
    return sorted(picked)


# ------------------------------------------------- Schneider curve fitting
def _bezier(c, t):
    mt = 1 - t
    return (mt ** 3 * c[0] + 3 * mt ** 2 * t * c[1]
            + 3 * mt * t ** 2 * c[2] + t ** 3 * c[3])


def _chord_params(p):
    d = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(d)])
    return s / s[-1] if s[-1] > 0 else np.linspace(0, 1, len(p))


def _fit_one(p, u, t1, t2):
    """Least-squares cubic with fixed endpoints and tangent directions."""
    mt = 1 - u
    A0 = 3 * mt ** 2 * u
    A1 = 3 * mt * u ** 2
    base = (mt ** 3)[:, None] * p[0] + (u ** 3)[:, None] * p[-1]
    rhs = p - base
    c11 = (A0 ** 2).sum() * (t1 @ t1)
    c12 = (A0 * A1).sum() * (t1 @ t2)
    c22 = (A1 ** 2).sum() * (t2 @ t2)
    x1 = (rhs * A0[:, None] @ t1).sum()
    x2 = (rhs * A1[:, None] @ t2).sum()
    det = c11 * c22 - c12 * c12
    lim = np.linalg.norm(p[-1] - p[0])
    if abs(det) < 1e-12:
        a1 = a2 = lim / 3.0
    else:
        a1 = (x1 * c22 - c12 * x2) / det
        a2 = (c11 * x2 - x1 * c12) / det
    if not (1e-6 < a1 < 3 * lim + 1e-6):
        a1 = lim / 3.0
    if not (1e-6 < a2 < 3 * lim + 1e-6):
        a2 = lim / 3.0
    return np.array([p[0], p[0] + a1 * t1, p[-1] + a2 * t2, p[-1]])


def _max_err(p, u, c):
    d = _bezier(c, u[:, None]) - p
    e = (d ** 2).sum(1)
    i = int(np.argmax(e))
    return e[i], i


def _reparam(p, u, c):
    """One Newton-Raphson step pulling each sample toward its closest point."""
    d1 = 3 * (c[1] - c[0]), 3 * (c[2] - c[1]), 3 * (c[3] - c[2])
    d2 = 2 * (d1[1] - d1[0]), 2 * (d1[2] - d1[1])
    t = u[:, None]
    mt = 1 - t
    q = _bezier(c, t) - p
    q1 = mt ** 2 * d1[0] + 2 * mt * t * d1[1] + t ** 2 * d1[2]
    q2 = mt * d2[0] + t * d2[1]
    num = (q * q1).sum(1)
    den = (q1 * q1).sum(1) + (q * q2).sum(1)
    step = np.where(np.abs(den) > 1e-12, num / np.where(den == 0, 1, den), 0)
    return np.clip(u - step, 0, 1)


def fit_run(p, t1, t2, tol, depth=0):
    """Recursively fit open polyline p within tol; returns a list of cubics."""
    if len(p) < 3:
        seg = np.linalg.norm(p[-1] - p[0]) / 3.0
        return [np.array([p[0], p[0] + seg * t1, p[-1] + seg * t2, p[-1]])]
    u = _chord_params(p)
    c = _fit_one(p, u, t1, t2)
    err, idx = _max_err(p, u, c)
    if err <= tol * tol:
        return [c]
    if err <= (tol * 4) ** 2 and depth < 12:
        for _ in range(12):
            u = _reparam(p, u, c)
            c = _fit_one(p, u, t1, t2)
            err, idx = _max_err(p, u, c)
            if err <= tol * tol:
                return [c]
    if depth >= 14 or idx <= 0 or idx >= len(p) - 1:
        return [c]
    v = p[min(idx + 1, len(p) - 1)] - p[max(idx - 1, 0)]
    nv = np.linalg.norm(v)
    tm = v / nv if nv > 1e-12 else t2
    return (fit_run(p[:idx + 1], t1, -tm, tol, depth + 1)
            + fit_run(p[idx:], tm, t2, tol, depth + 1))


def _tangent(pts, i, fwd, k=4):
    n = len(pts)
    acc = np.zeros(2)
    for j in range(1, k + 1):
        q = pts[(i + j) % n] if fwd else pts[(i - j) % n]
        acc += (1.0 / j) * (q - pts[i])
    nv = np.linalg.norm(acc)
    return acc / nv if nv > 1e-12 else np.array([1.0, 0.0])


def fit_contour(pts, tol):
    ks = corners(pts)
    n = len(pts)
    if len(ks) < 2:                    # smooth blob: quarter it for conditioning
        ks = [0, n // 4, n // 2, 3 * n // 4]
    out = []
    for a, b in zip(ks, ks[1:] + ks[:1]):
        idx = np.arange(a, b if b > a else b + n) % n
        run = np.vstack([pts[idx], pts[b % n]])
        out.extend(fit_run(run, _tangent(pts, a, True),
                           _tangent(pts, b % n, False), tol))
    return out


# -------------------------------------------------------------------- emit
def fmt(v):
    s = f'{v:.{DEC}f}'.rstrip('0').rstrip('.')
    if s in ('', '-0', '-'):
        return '0'
    if s.startswith('0.'):
        return s[1:]
    if s.startswith('-0.'):
        return '-' + s[2:]
    return s


def _join(nums):
    """Concatenate path numbers with the fewest legal separators. A leading
    '-' self-separates; a leading '.' abuts only when the previous token
    already holds a '.', else '5' + '.5' would merge into '5.5'."""
    out, prev = '', ''
    for n in nums:
        if out:
            sep = '' if n[0] == '-' else (' ' if n[0] != '.' else
                                          ('' if '.' in prev else ' '))
        else:
            sep = ''
        out += sep + n
        prev = n
    return out


def to_path(curves):
    """Relative cubics; round once at emit and accumulate in rounded space so
    quantization error can't drift across a contour."""
    ox, oy = ORIGIN
    sx, sy = fmt(curves[0][0][0] - ox), fmt(curves[0][0][1] - oy)
    d = ['M' + _join([sx, sy])]
    penx, peny = float(sx), float(sy)
    for c in curves:
        rel = []
        for k in (1, 2, 3):
            rel += [fmt(c[k][0] - ox - penx), fmt(c[k][1] - oy - peny)]
        d.append('c' + _join(rel))
        penx += float(rel[4])
        peny += float(rel[5])
    d.append('z')
    return ''.join(d)


def build(tol, upsample, smooth, fill, title=None):
    subpaths, ncurves = [], 0
    for pts in contours(upsample=upsample):
        pts = resample(pts, step=1.0)
        if smooth:
            pts = smooth_closed(pts, passes=smooth)
        curves = fit_contour(pts, tol)
        ncurves += len(curves)
        subpaths.append(to_path(curves))
    w, h = VIEW
    d = ''.join(subpaths)
    path = f'<path fill="{fill}" fill-rule="evenodd" d="{d}"/>'
    if title:
        svg = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
               f' role="img" aria-label="{title}">\n'
               f'  <title>{title}</title>\n  {path}\n</svg>\n')
    else:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" '
               f'viewBox="0 0 {w} {h}">\n  {path}\n</svg>\n')
    return svg, len(subpaths), ncurves


# -------------------------------------------------------------------- main
def main():
    global PNG, ORIGIN, VIEW, BG, INK, DEC
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--tol', type=float, default=0.15,
                    help='fit error tolerance in source px (default 0.15)')
    ap.add_argument('--upsample', type=int, default=8,
                    help='coverage-map supersample (default 8)')
    ap.add_argument('--smooth', type=int, default=0,
                    help='Laplacian passes before fitting (default 0)')
    ap.add_argument('--decimals', type=int, default=2)
    ap.add_argument('--pad', type=float, default=4.0,
                    help='padding around ink for auto viewBox (default 4)')
    ap.add_argument('--viewbox', default=None,
                    help='"OX OY W H" to override auto framing')
    ap.add_argument('--fill', default=None, help='path fill (default: detected)')
    ap.add_argument('--title', default=None,
                    help='add <title> + role/aria-label')
    ap.add_argument('--bg', type=float, default=None)
    ap.add_argument('--ink', type=float, default=None)
    a = ap.parse_args()

    PNG = a.input
    DEC = a.decimals
    im = Image.open(PNG).convert('RGB')
    lum = np.array(im.convert('L'), dtype=float)
    BG, INK = detect_levels(lum, a.bg, a.ink)
    cov = coverage(lum)

    if a.viewbox:
        ox, oy, w, h = (float(x) for x in a.viewbox.split())
        ORIGIN, VIEW = (ox, oy), (int(round(w)), int(round(h)))
    else:
        ys, xs = np.where(cov >= 0.5)
        if not len(xs):
            sys.exit('no ink detected (check --bg/--ink)')
        ox = float(xs.min()) - a.pad
        oy = float(ys.min()) - a.pad
        w = int(round(xs.max() - xs.min() + 1 + 2 * a.pad))
        h = int(round(ys.max() - ys.min() + 1 + 2 * a.pad))
        ORIGIN, VIEW = (ox, oy), (w, h)

    fill = a.fill or ink_color(np.array(im), cov)
    svg, ncontours, ncurves = build(a.tol, a.upsample, a.smooth, fill, a.title)
    with open(a.output, 'w') as f:
        f.write(svg)
    mapping = dict(png=PNG, origin=list(ORIGIN), view=list(VIEW),
                   bg=BG, ink=INK, fill=fill)
    with open(a.output + '.trace.json', 'w') as f:
        json.dump(mapping, f, indent=2)
    print(f'{a.output}: {ncontours} contours, {ncurves} curves, '
          f'{len(svg)} bytes  (fill {fill}, viewBox 0 0 {VIEW[0]} {VIEW[1]})')
    print(f'  bg={BG:.0f} ink={INK:.0f}  origin={ORIGIN}  -> {a.output}.trace.json')


if __name__ == '__main__':
    main()
