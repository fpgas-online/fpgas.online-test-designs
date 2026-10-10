# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Measure the photo of the Acorn's underside (photos/acorn-cw.jpg), in photo pixels and in millimetres.

The photo is the board maker's "contents" photo, cut and turned by prep_photos.py: the end of the card away
from the M.2 edge, underside up, that end at the top, the two sockets on the left edge. Nothing about where
things are in it is typed in; it is measured here:

* the six contacts of each socket: small warm (gold) marks in the left quarter of the photo, in two runs of
  six down the photo. The upper run is P2 and the lower P1 (the card's own silkscreen, and prep_photos.py);
* the card's two long edges, on every row below the sockets where both are in the photo: the board is dark and
  the background paper. A straight line is fitted to each, because the card does not sit quite square in the
  photo. Their distance is the card's 22.00 mm width (wiring.toml [[sources]], "The card's form"): the scale;
* the check on that scale: the contacts of a Molex Pico-EZmate socket are 1.20 mm apart, so each run's fitted
  pitch must be 1.20 mm within 5 % at the edges' scale, or the script stops;
* each socket's box: the white outline the silkscreen draws round it, found outward from its contacts;
* the half-round plated pad at the card's end: the gold area that touches that end;
* pin 1 of each socket: the contact nearest the M.2 edge (wiring.toml's first [[sources]] line), which is off
  the bottom of this photo, so the contact with the largest y.

Run: uv run docs/wiring/acorn/measure_card.py           prints the pixel values, then the millimetre ones
     uv run docs/wiring/acorn/measure_card.py --check   fails unless geometry.toml has exactly these
test_card.py runs the check too.
"""

import math
import pathlib
import sys

import tomllib
from measure_hat import blobs, centre, fit_line
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).parent
PHOTO = "acorn-cw.jpg"

CARD_WIDTH = 22.00  # mm: M.2 2280 (wiring.toml [[sources]], "The card's form")
CONTACT_PITCH = 1.20  # mm: Molex Pico-EZmate
CONTACTS = 6
PAPER = 200  # the background is brighter than this (prep_photos.PAPER is about 250) and the card's edge darker
ROWS_NEEDED, EDGE_AGREES = 20, 2.0  # an edge: at least this many rows, each within this many px of its line
SILK = 80  # the silkscreen's white is brighter than this in every channel; the board and the mouldings darker
LINE = 0.2  # a row or column is part of a socket's outline when this fraction of it is silkscreen


def warm(rgb):
    """Gold in shadow or in light: the contacts."""
    return rgb[0] > 110 and rgb[0] - rgb[2] > 40


def gold(rgb):
    """Gold in full light: the plated pads."""
    return rgb[0] > 140 and rgb[0] - rgb[2] > 70


def white(rgb):
    """Silkscreen: light and without colour, and not the paper."""
    return min(rgb) > SILK and max(rgb) - min(rgb) < 40 and max(rgb) < PAPER + 35


def contact_runs(path, im, w, h):
    """The two runs of six contacts, upper first: [[(x, y)] * 6] * 2."""
    # A contact under a plug shows as two gold marks a few px apart: grown by 3 px, they are one.
    mask = Image.new("L", (w, h))
    mask.putdata([255 if warm(p) else 0 for p in im.get_flattened_data()])
    grown = [v > 0 for v in mask.filter(ImageFilter.MaxFilter(7)).get_flattened_data()]
    small = [b for b in blobs(grown, w, h, 15) if b[2] - b[0] < 30 and b[3] - b[1] < 30 and centre(b)[0] < w / 4]
    marks = sorted((centre(b) for b in small), key=lambda p: p[1])
    if len(marks) < 2 * CONTACTS:
        raise SystemExit(f"{path}: {len(marks)} gold marks near the left edge, fewer than two sockets' contacts")
    gaps = sorted(b[1] - a[1] for a, b in zip(marks, marks[1:], strict=False))
    step = gaps[len(gaps) // 2]
    runs = [[marks[0]]]
    for a, b in zip(marks, marks[1:], strict=False):
        if b[1] - a[1] > 1.5 * step or abs(b[0] - a[0]) > step:
            runs.append([])
        runs[-1].append(b)
    runs = [r for r in runs if len(r) >= 3]  # one or two marks alone are a part on the board, not a socket
    if len(runs) != 2 or any(len(r) != CONTACTS for r in runs):
        raise SystemExit(f"{path}: the sockets show {[len(r) for r in runs]} contacts, not two runs of {CONTACTS}")
    return runs


def edge_line(path, name, points):
    """The straight line x = a + b·y through an edge's [(y, x)], and how many rows lie within EDGE_AGREES of it."""
    for _ in range(3):  # a row that crosses something else (a cable, a nick) is dropped and the line fitted again
        a, b, _worst = fit_line(points)
        points = [(y, x) for y, x in points if abs(a + b * y - x) <= EDGE_AGREES]
        if len(points) < ROWS_NEEDED:
            raise SystemExit(f"{path}: the card's {name} edge is straight on only {len(points)} rows")
    a, b, _worst = fit_line(points)
    return a, b, len(points)


def outline(silk, w, lo, hi, start, step, span):
    """From `start`, going by `step` along rows (or columns), the first run that is outline: its two ends.

    `silk(i, j)` is asked across `span` = (j0, j1); a row counts when LINE of the span is silkscreen."""
    need = LINE * (span[1] - span[0])
    i = start
    while lo <= i < hi and sum(silk(i, j) for j in range(*span)) < need:
        i += step
    if not lo <= i < hi:
        return None
    first = i
    while lo <= i + step < hi and sum(silk(i + step, j) for j in range(*span)) >= need:
        i += step
    return min(first, i), max(first, i)


def measure(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    rgb = list(im.get_flattened_data())
    lum = list(im.convert("L").get_flattened_data())

    runs = contact_runs(path, im, w, h)
    fits = [fit_line([(i, y) for i, (_x, y) in enumerate(run)]) for run in runs]  # y = a + b·i down each socket
    for run, (_a, b, worst) in zip(runs, fits, strict=True):
        if worst > 0.15 * b:
            raise SystemExit(f"{path}: a socket's contacts are not evenly spaced: {run}")
    pitch_px = sum(b for _a, b, _r in fits) / 2

    # The long edges, on the rows below both sockets where neither the board nor anything dark on it runs off the
    # photo's side.
    first_row = round(fits[1][0] + (CONTACTS - 1 + 3) * fits[1][1])
    lefts, rights = [], []
    for y in range(first_row, h):
        row = lum[y * w : (y + 1) * w]
        if row[0] < PAPER or row[-1] < PAPER or min(row) >= PAPER:
            continue
        lefts.append((y, next(x for x in range(w) if row[x] < PAPER)))
        rights.append((y, next(x for x in range(w - 1, -1, -1) if row[x] < PAPER)))
    if len(lefts) < ROWS_NEEDED:
        raise SystemExit(f"{path}: both edges of the card are in the photo on only {len(lefts)} rows")
    la, lb, ln = edge_line(path, "left", lefts)
    ra, rb, rn = edge_line(path, "right", rights)
    mid = (lefts[0][0] + lefts[-1][0]) / 2
    lean = (lb + rb) / 2  # px across per px down: how far off square the card sits
    # Between the first dark pixel of one edge and the last of the other there are (difference + 1) pixels.
    width_px = (ra + rb * mid - (la + lb * mid) + 1) * math.cos(math.atan(lean))
    scale = width_px / CARD_WIDTH
    width_at = [ra + rb * y - (la + lb * y) + 1 for y in (lefts[0][0], lefts[-1][0])]

    pitches = [b / scale for _a, b, _r in fits]
    if any(abs(p - CONTACT_PITCH) / CONTACT_PITCH > 0.05 for p in pitches):
        raise SystemExit(
            f"{path}: the contacts are {pitches[0]:.3f} mm (P2) and {pitches[1]:.3f} mm (P1) apart at the "
            f"{scale:.3f} px/mm the card's width gives, not {CONTACT_PITCH} within 5 %: the photo is not square-on "
            f"or the edges were misread (edges x = {la:.2f} + {lb:.5f}·y and {ra:.2f} + {rb:.5f}·y, {width_px:.2f} px "
            f"apart; contacts {runs}; the contacts alone give {pitch_px / CONTACT_PITCH:.3f} px/mm)"
        )

    def left_at(y):
        return la + lb * y

    def silk(x, y):
        return left_at(y) + 1 < x and white(rgb[y * w + x])

    # Each socket's box: the silkscreen outline round it. Its long sides first, out from the contacts' column
    # across the rows the contacts span; then its ends, out from the end contacts across the width just found.
    sockets, contacts = {}, {}
    for name, run, (a, b, _r) in zip(("P2", "P1"), runs, fits, strict=True):
        x_mid = round(sum(x for x, _y in run) / CONTACTS)
        rows = (round(a - b / 2), round(a + (CONTACTS - 0.5) * b))
        across = [outline(silk, w, 0, w, x_mid, step, rows) for step in (-1, 1)]
        if None in across:
            raise SystemExit(f"{path}: {name}'s silkscreen outline was not found beside its contacts")
        cols = (across[0][0], across[1][1] + 1)

        def by_row(y, x):
            return silk(x, y)

        along = [outline(by_row, w, 0, h, rows[0] if step < 0 else rows[1], step, cols) for step in (-1, 1)]
        if None in along:
            raise SystemExit(f"{path}: {name}'s silkscreen outline was not found beyond its end contacts")
        sockets[name] = (cols[0], along[0][0], cols[1], along[1][1] + 1)
        x_mean = sum(x for x, _y in run) / CONTACTS
        contacts[name] = [(round(x_mean, 1), round(a + b * i, 1)) for i in range(CONTACTS)]
    if not sockets["P2"][3] <= sockets["P1"][1]:
        raise SystemExit(f"{path}: the sockets' outlines overlap: {sockets}")

    # The card's far end: the first row of the photo with card on it, on at least ROWS_NEEDED columns clear of the
    # long edges (the end is not quite level: the card leans).
    inside = range(round(max(la, 0)) + 5, round(ra) - 5)
    top = next((y for y in range(h) if sum(lum[y * w + x] < PAPER for x in inside) >= ROWS_NEEDED), None)
    if top is None or top == 0:
        raise SystemExit(f"{path}: the card's far end is not in the photo (first row of card: {top})")

    # The half-round pad: the gold that reaches the card's far end.
    plated = [b for b in blobs([gold(p) for p in rgb], w, h, 400) if b[1] - top <= scale]
    if len(plated) != 1:
        raise SystemExit(f"{path}: {len(plated)} plated pads at the card's end, not one: {plated}")
    pad = (plated[0][0], plated[0][1], plated[0][2] + 1, plated[0][3] + 1)
    pad_mid = (pad[0] + pad[2] - 1) / 2 - (left_at(pad[1]) + ra + rb * pad[1]) / 2
    if abs(pad_mid) > 0.5 * scale:
        raise SystemExit(f"{path}: the pad at the card's end is {pad_mid / scale:.2f} mm off the card's middle")

    # Where the left edge is beside the sockets: the card leans, and the sockets are what the edge is wanted for.
    beside = (sockets["P2"][1] + sockets["P1"][3]) / 2
    return {
        "scale_px_per_mm": round(scale, 3),
        "edges": {
            "rows": [lefts[0][0], lefts[-1][0]],
            "rows_with_both_edges": len(lefts),
            "rows_agreeing": [ln, rn],
            "left": [round(la, 2), round(lb, 5)],
            "right": [round(ra, 2), round(rb, 5)],
            "width_px": round(width_px, 2),
            "width_first_last_row_px": [round(v, 2) for v in width_at],
            "lean_degrees": round(math.degrees(math.atan(lean)), 2),
        },
        "contact_pitch_px": {"P2": round(fits[0][1], 2), "P1": round(fits[1][1], 2)},
        "contact_pitch_mm": {"P2": round(pitches[0], 3), "P1": round(pitches[1], 3)},
        "contact_fit_worst_px": round(max(r for _a, _b, r in fits), 2),
        "scale_from_contacts_px_per_mm": round(pitch_px / CONTACT_PITCH, 3),
        "contacts": contacts,
        "sockets": sockets,
        "pad": pad,
        "left": round(left_at(beside), 1),
        "top": top,
        "height": h,
    }


def measure_mm(path):
    """The card in millimetres, in its own frame: its top face from above, origin at the far-end corner, y toward
    the M.2 edge. The photo shows the bottom face, so x is mirrored across the card's width. What geometry.toml
    holds; `origin` is the photo pixel of the card's corner at the photo's top left, the point (22.00, 0)."""
    m = measure(path)
    s, left, top = m["scale_px_per_mm"], m["left"], m["top"]

    def x_mm(px):
        return round(CARD_WIDTH - (px - left) / s, 2)

    def y_mm(px):
        return round((px - top) / s, 2)

    def box(b):
        return [x_mm(b[2]), y_mm(b[1]), x_mm(b[0]), y_mm(b[3])]

    def pin1(name):
        x, y = m["contacts"][name][-1]  # the contact nearest the M.2 edge
        return [x_mm(x), y_mm(y)]

    return {
        "px_per_mm": s,
        "origin": [left, top],
        "length_shown": y_mm(m["height"]),
        "p1": box(m["sockets"]["P1"]),
        "p2": box(m["sockets"]["P2"]),
        "p1_pin1": pin1("P1"),
        "p2_pin1": pin1("P2"),
        "pad": box(m["pad"]),
        "contact_pitch_mm": {"P1": m["contact_pitch_mm"]["P1"], "P2": m["contact_pitch_mm"]["P2"]},
    }


def stored(mm):
    """What geometry.toml [things.acorn] must hold, by its own keys."""
    return {
        "photos.bottom.px_per_mm": mm["px_per_mm"],
        "photos.bottom.origin": mm["origin"],
        "photos.bottom.shown": [0, mm["length_shown"]],
        "items.p1.box": mm["p1"],
        "items.p1.pin1": mm["p1_pin1"],
        "items.p2.box": mm["p2"],
        "items.p2.pin1": mm["p2_pin1"],
        "items.pad.box": mm["pad"],
    }


def main(argv):
    path = HERE / "photos" / PHOTO
    for k, v in measure(path).items():
        print(f"{k} = {list(v) if isinstance(v, tuple) else v}")
    mm = measure_mm(path)
    print("in millimetres, as geometry.toml has them:")
    for k, v in mm.items():
        print(f"{k} = {v}")
    if "--check" in argv:
        acorn = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]
        wrong = []
        for key, want in stored(mm).items():
            have = acorn
            for part in key.split("."):
                have = have.get(part, {}) if isinstance(have, dict) else {}
            if have != want:
                wrong.append(f"{key}: geometry.toml {have}, measured {want}")
        if wrong:
            raise SystemExit("geometry.toml [things.acorn] is not what the photo measures:\n  " + "\n  ".join(wrong))
        print("geometry.toml matches the photo")


if __name__ == "__main__":
    main(sys.argv[1:])
