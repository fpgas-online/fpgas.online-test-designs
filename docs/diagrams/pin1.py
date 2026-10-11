# SPDX-License-Identifier: Apache-2.0
"""Pin 1 of a connector: which side of it the marker stands on, how far it reaches, and the marker drawn."""

import math

from . import model
from .canvas import BOX, INK

CONNECTORS = ("header", "socket")  # the kinds that carry a pin 1 marker
TRI, INSET_TRI = 10, 6  # px: the pin 1 triangle, in the picture and on the inset
TAG_GAP = 3  # px between the pin 1 triangle and its "1"
MARKER = TRI + TAG_GAP + 16  # px a pin 1 marker reaches out from its item: the triangle, the gap, the "1"
MARKER_HALF = 9  # px either side of the marker's line
CLEAR = 6  # px a pin 1 marker keeps off the other parts


def owns(item, other):
    """`other` is `item` or a part of it (a pin of a header)."""
    return other.id == item.id or other.id.startswith(item.id + ".")


def distances(item):
    """How far pin 1 is from each side of its item's box (x0, x1, y0, y1), in millimetres."""
    b, (x, y) = item.box, item.pin1
    return {"x0": x - b.x0, "x1": b.x1 - x, "y0": y - b.y0, "y1": b.y1 - y}


def room_beyond(item, room):
    """How much of `room` (a box) lies beyond each side of the item's box."""
    b = item.box
    return {"x0": b.x0 - room.x0, "x1": room.x1 - b.x1, "y0": b.y0 - room.y0, "y1": room.y1 - b.y1}


def clear_sides(item, others, scale):
    """The sides whose pin 1 marker, at `scale`, keeps CLEAR px off every box of `others`."""
    return {
        s
        for s in ("x0", "x1", "y0", "y1")
        if all(marker_box_mm(item, s, scale).grow(CLEAR / scale).intersect(o) is None for o in others)
    }


def side(item, room, sides=("x0", "x1", "y0", "y1")):
    """Of `sides` of the item's box, the one nearest its pin 1 point; of two as near, the one with more of `room`
    beyond it, so the marker does not crowd the frame's edge."""
    near, beyond = distances(item), room_beyond(item, room)
    least = min(near[s] for s in sides)
    return max((s for s in sides if near[s] <= least + 0.05), key=lambda s: (beyond[s], s))


def sides(marked, room, parts, scale):
    """The side each marked connector's pin 1 marker stands on. Markers keep off the other parts; connectors
    shown together take one side between them where they can, so the reader finds every pin 1 the same way."""
    clear = {i.id: clear_sides(i, [o.box for o in parts if not owns(i, o)], scale) for i in marked}
    common = set.intersection(*clear.values()) if len(marked) > 1 else set()
    if common:
        best = min(
            sorted(common),
            key=lambda s: (sum(distances(i)[s] for i in marked), -sum(room_beyond(i, room)[s] for i in marked)),
        )
        return {i.id: best for i in marked}
    return {i.id: side(i, room, sorted(clear[i.id]) or ("x0", "x1", "y0", "y1")) for i in marked}


def line(item, side):
    """Where the marker touches the item's edge, and the way out from it, in millimetres."""
    b, (x, y) = item.box, item.pin1
    return {
        "x0": ((b.x0, y), (-1, 0)),
        "x1": ((b.x1, y), (1, 0)),
        "y0": ((x, b.y0), (0, -1)),
        "y1": ((x, b.y1), (0, 1)),
    }[side]


def marker_box_mm(item, side, scale):
    (ex, ey), (dx, dy) = line(item, side)
    out, half = MARKER / scale, MARKER_HALF / scale
    xs = (ex, ex + dx * out, ex - dy * half, ex + dy * half)
    ys = (ey, ey + dy * out, ey - dx * half, ey + dx * half)
    return model.Box(min(xs), min(ys), max(xs), max(ys))


def draw(pic, item, side, tri, number=True):
    """The pin 1 marker: a triangle outside the item pointing at pin 1, and a "1" beyond it."""
    fr = pic.frame
    (ex, ey), (dx, dy) = line(item, side)
    tip = fr.to_px(ex, ey)
    out = fr.to_px(ex + dx, ey + dy)
    n = math.hypot(out[0] - tip[0], out[1] - tip[1])
    ux, uy = (out[0] - tip[0]) / n, (out[1] - tip[1]) / n
    bx, by = tip[0] + ux * tri, tip[1] + uy * tri
    half = tri * 0.6
    points = (tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half))
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points) + " Z"
    pic.sh.add(f'<g data-pin1-of="{item.id}"><path d="{d}" fill="{BOX}" stroke="{INK}" stroke-width="1.2"/>')
    if number:
        cx, cy = tip[0] + ux * (tri + TAG_GAP + 8), tip[1] + uy * (tri + TAG_GAP + 8)
        x0, x1 = pic.sh.tag(cx, cy, "1", BOX, size=11, h=16, anchor="middle", pad=4, fg=INK, stroke=INK)
        pic.taken.append((x0, cy - 8, x1, cy + 8, f"pin 1 of {item.id}"))
    pic.sh.add("</g>")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pic.taken.append((min(xs), min(ys), max(xs), max(ys), f"pin 1 of {item.id}"))
