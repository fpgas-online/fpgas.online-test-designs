# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Measure the HAT photo the sheets draw on (wiring.toml [carriers.pi5.hat] `photo`), in photo pixels.

The photo is Waveshare's dimension drawing of the PoE M.2 HAT+ (B), cut and turned by prep_photos.py: header
on the right edge, pin 1 at the top. Everything wiring.toml says about where things are in it comes from here:

* the scale, from the four HAT mounting holes, whose 58.00 × 49.00 mm pitch the drawing prints;
* which way up it is, proved and not assumed: the holes are 3.50 mm in from one end of the 85.00 mm board and
  23.50 mm in from the other (the drawing's figures), and pin 1 is at the 3.50 mm end (Raspberry Pi's header);
* the header: every pad of its 2 × 20 pins found in the photo, and the two column centres, the first row's
  centre and the pitch fitted to them. The pitch is checked against 2.54 mm at the holes' scale, and the odd
  column (pin 1's) against the board edge: on a Raspberry Pi it is the inner one;
* the M.2 socket, a grey moulding on the black board, boxed where it is;
* from those, the boxes the drawings use: `pin1_box` (pins 1 to 26 on the wiring sheet), `crop` (the strip of
  the header the cable pictures show) and `m2_slot`.

Run: uv run docs/wiring/acorn/measure_hat.py           prints the values, as wiring.toml has them
     uv run docs/wiring/acorn/measure_hat.py --check   fails unless wiring.toml has exactly these
test_wiring.py runs the check too.
"""

import pathlib
import sys

import tomllib
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).parent

# What Waveshare print on the (B)'s dimension drawing, in millimetres.
HOLE_PITCH_LONG, HOLE_PITCH_SHORT = 58.00, 49.00
HOLE_EDGE, BOARD_LONG = 3.50, 85.00
PIN_PITCH = 2.54  # the Raspberry Pi 40-pin header's
ROWS = 20
PAD = 62  # blurred, a pad is brighter than this and the board between two pads darker


def blobs(mask, w, h, min_px):
    """Connected True regions of `mask` (a flat list, row by row): [(x0, y0, x1, y1, size)]."""
    seen = bytearray(w * h)
    out = []
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        stack, size = [start], 0
        x0, y0, x1, y1 = w, h, 0, 0
        while stack:
            i = stack.pop()
            size += 1
            x, y = i % w, i // w
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w, i + w):
                if 0 <= j < w * h and mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        if size >= min_px:
            out.append((x0, y0, x1, y1, size))
    return out


def centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def fit_line(points):
    """Least squares a + b·i over [(i, v)]: (a, b, worst residual)."""
    n = len(points)
    si = sum(i for i, _ in points)
    sv = sum(v for _, v in points)
    sii = sum(i * i for i, _ in points)
    siv = sum(i * v for i, v in points)
    b = (n * siv - si * sv) / (n * sii - si * si)
    a = (sv - b * si) / n
    return a, b, max(abs(a + b * i - v) for i, v in points)


def measure(path):
    im = Image.open(path).convert("L")
    w, h = im.size
    lum = list(im.get_flattened_data())

    # The four mounting holes: white silkscreen rings about 6 mm across on the black board, each round a hole the
    # paper shows through (white at its centre, where an M.2 standoff of the same size is dark).
    rings = [
        b
        for b in blobs([v > 200 for v in lum], w, h, 400)
        if 40 <= b[2] - b[0] <= 62
        and 40 <= b[3] - b[1] <= 62
        and lum[round(centre(b)[1]) * w + round(centre(b)[0])] > 230
    ]
    if len(rings) != 4:
        raise SystemExit(f"{path}: {len(rings)} mounting-hole rings found, not 4: {rings}")
    holes = sorted(centre(b) for b in rings)
    (lt, lb), (rt, rb) = sorted(holes[:2], key=lambda p: p[1]), sorted(holes[2:], key=lambda p: p[1])
    long_px = ((lb[1] - lt[1]) + (rb[1] - rt[1])) / 2  # down the photo: the 58.00 mm pitch
    short_px = ((rt[0] - lt[0]) + (rb[0] - lb[0])) / 2  # across it: the 49.00 mm pitch
    scale = long_px / HOLE_PITCH_LONG
    if abs(short_px / HOLE_PITCH_SHORT - scale) / scale > 0.01:
        raise SystemExit(f"{path}: the holes give {scale:.3f} px/mm down and {short_px / HOLE_PITCH_SHORT:.3f} across")
    top_holes, bottom_holes = (lt[1] + rt[1]) / 2, (lb[1] + rb[1]) / 2

    # The header: pads brighter than the board, in the strip between the right-hand holes' column and the edge.
    # A pad is solder round a pin, bright in patches: blurred over about half a millimetre, each is one blob.
    soft = list(im.filter(ImageFilter.GaussianBlur(0.5 * scale)).get_flattened_data())
    x_from = round(rt[0] - 5 * scale)
    strip = [soft[y * w + x] > PAD if x >= x_from else False for y in range(h) for x in range(w)]
    size = PIN_PITCH * scale
    pads = [
        centre(b)
        for b in blobs(strip, w, h, 12)
        if 0.2 * size <= b[2] - b[0] <= 0.85 * size and 0.2 * size <= b[3] - b[1] <= 0.85 * size
    ]
    pads = [p for p in pads if top_holes < p[1] < bottom_holes]
    # The two columns: the two most crowded half-pitch-wide bins of the pads' x; a pad more than a quarter pitch off
    # its column's line is something else on the board.
    bins = {}
    for x, _ in pads:
        bins[round(x / (size / 2))] = bins.get(round(x / (size / 2)), 0) + 1
    lines = sorted(sorted(bins, key=bins.get)[-2:])
    found = []
    for k in lines:
        near = [p for p in pads if abs(p[0] - k * size / 2) <= size / 2]
        mid = sorted(x for x, _ in near)[len(near) // 2]
        found.append(sorted((y, x) for x, y in near if abs(x - mid) <= size / 4))
    first = min(col[0][0] for col in found)  # pin 1's row: where the first pad of either column is
    columns, fits, worst = [], [], 0.0
    for col in found:
        index = {}
        for y, x in col:
            index.setdefault(round((y - first) / size), []).append((y, x))
        single = [(i, v[0]) for i, v in index.items() if len(v) == 1 and 0 <= i < ROWS]  # one pad to a row, or none
        if len(single) < ROWS - 4:
            raise SystemExit(f"{path}: a header column with {len(single)} of its {ROWS} pads found")
        a, b, r = fit_line([(i, y) for i, (y, _x) in single])
        worst = max(worst, r)
        columns.append(sum(x for _i, (_y, x) in single) / len(single))
        fits.append((a, b, len(single)))
    row0 = sum(a for a, _b, _n in fits) / 2
    pitch = sum(b for _a, b, _n in fits) / 2
    if abs(pitch - size) / size > 0.02:
        raise SystemExit(f"{path}: the pads are {pitch:.2f} px apart; 2.54 mm at the holes' scale is {size:.2f}")
    if abs(row0 + (ROWS - 1) / 2 * pitch - (top_holes + bottom_holes) / 2) > scale:
        raise SystemExit(f"{path}: the header is not centred between the mounting holes: a row is missed at an end")

    # Which way up: pin 1's end has its holes 3.50 mm in from the board's end, the other end 23.50 mm.
    def board_end(x, rows):
        return next(y for y in rows if lum[y * w + round(x)] < 200)

    top = board_end(columns[0], range(h))
    bottom = board_end(columns[0], range(h - 1, -1, -1))
    ends = ((top_holes - top) / scale, (bottom - bottom_holes) / scale)
    if abs(ends[0] - HOLE_EDGE) > 1 or abs(ends[1] - (BOARD_LONG - HOLE_EDGE - HOLE_PITCH_LONG)) > 1:
        raise SystemExit(
            f"{path}: the holes are {ends[0]:.2f} and {ends[1]:.2f} mm from the board's ends: upside down?"
        )
    if abs((bottom - top) / scale - BOARD_LONG) > 1:
        raise SystemExit(f"{path}: the board is {(bottom - top) / scale:.2f} mm long, not {BOARD_LONG}")
    right = next(x for x in range(w - 1, -1, -1) if lum[round(row0) * w + x] < 200)
    if not right - columns[1] < right - columns[0]:
        raise SystemExit(f"{path}: the odd column (pin 1's) is not the inner one")

    # The M.2 socket: grey moulding on the black board, between the left-hand holes and the header, above the
    # top holes' line plus 8 mm.
    x0, x1 = round(lt[0] + 3.5 * scale), round(columns[0] - 15 * scale)
    y1 = round(top_holes + 8 * scale)
    grey = [x0 <= x < x1 and y < y1 and 66 < lum[y * w + x] < 200 for y in range(h) for x in range(w)]
    socket = max(blobs(grey, w, h, 500), key=lambda b: b[4])
    long_mm = (socket[2] - socket[0]) / scale
    if not 18 <= long_mm <= 26:
        raise SystemExit(f"{path}: the M.2 socket found is {long_mm:.1f} mm long, not about 22")

    half = pitch / 2
    last26 = row0 + 12 * pitch  # the row of pins 25 and 26
    return {
        "scale_px_per_mm": round(scale, 3),
        "holes_from_ends_mm": tuple(round(e, 2) for e in ends),
        "board_mm": round((bottom - top) / scale, 2),
        "pads_found": [n for _a, _b, n in fits],
        "pad_fit_worst_px": round(worst, 2),
        "columns": [round(x, 1) for x in columns],
        "row": round(row0, 1),
        "pitch": round(pitch, 2),
        "pin1_box": [
            round(v) for v in (columns[0] - 1.2 * half, row0 - 1.8 * half, columns[1] + 1.5 * half, last26 + half)
        ],
        "crop": [
            round(columns[0] - 22.1 * scale),
            round(row0 - 5.2 * scale),
            w,
            min(h, round(row0 + (ROWS - 1) * pitch + 2.8 * scale)),
        ],
        "m2_slot": [socket[0], socket[1], socket[2] + 1, socket[3] + 1],
        "socket_mm": (round(long_mm, 2), round((socket[3] - socket[1]) / scale, 2)),
    }


STORED = ("columns", "row", "pitch", "pin1_box", "crop", "m2_slot")


def main(argv):
    hat = tomllib.loads((HERE / "wiring.toml").read_text())["carriers"]["pi5"]["hat"]
    got = measure(HERE / "photos" / hat["photo"])
    for k, v in got.items():
        print(f"{k} = {list(v) if isinstance(v, tuple) else v}")
    if "--check" in argv:
        wrong = [f"{k}: wiring.toml {hat[k]}, measured {got[k]}" for k in STORED if hat[k] != got[k]]
        if wrong:
            raise SystemExit("wiring.toml [carriers.pi5.hat] is not what the photo measures:\n  " + "\n  ".join(wrong))
        print("wiring.toml matches the photo")


if __name__ == "__main__":
    main(sys.argv[1:])
