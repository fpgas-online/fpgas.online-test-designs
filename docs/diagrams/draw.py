# SPDX-License-Identifier: Apache-2.0
"""A view's render layer drawn on a canvas: the board, its parts, the highlight, pin 1, the labels and the inset.

render() returns the drawing with colour tokens (palette.resolve() makes the light and the dark SVG of it) and
the facts the manifest and the tests read. A view that breaks a rule stops with a DiagramError naming it.

A view about some parts (its highlight) draws them at full strength, a `mark` outline round them; every other
part is muted: its outline only, in one grey, and its name in the same grey. A view with no highlight mutes
nothing. The board is the ground and is never muted.
"""

import math
from dataclasses import dataclass

from . import frame, model, pin1, views
from .canvas import BODY, BOX, GOLD, INK, MUTED, Sheet
from .errors import DiagramError
from .palette import role

BORDER = 12  # px round the frame: a label may use it, nothing else does
INSET = 110  # px: the inset's longer side
INSET_PAD, INSET_GAP = 6, 6  # px: the inset's box round its drawing, and its distance from the frame's corner
INSET_COVER = 0.1  # the most of a highlighted item the inset may cover
MARK_PAD = 4  # px between an item and its mark outline
LABEL_SIZE, LABEL_H, LABEL_GAP = 13, 20, 4  # a label: its words, its tag, its distance from its item
NUMBERED_PITCH = 22  # px: pins this far apart or more carry their number
NUMBER_SIDE = 26  # px: the most a numbered pin is drawn wider than its own box
EDGE_TOL = 0.01  # mm: an item this near its thing's edge is cut by it
WORDS = 4  # the most words a label holds
TEXT_MARGIN = 8  # px: the canvas refuses text nearer its edge than this

BOARD, PART, PART_EDGE = role("render-board"), role("render-part"), role("render-part-edge")
GREY = role("render-muted")
MARK, MARK_EDGE, ON_MARK, ON_GOLD = role("mark"), role("mark-edge"), role("on-mark"), role("on-gold")


@dataclass
class Picture:
    """What is being drawn: the canvas, the frame, and what is already on it that a label must keep off."""

    sh: Sheet
    frame: frame.Frame
    view: views.View
    taken: list  # px boxes: (x0, y0, x1, y1, what)
    thing_px: tuple = ()  # the whole board on the canvas
    board_clip: str = ""  # the id of the clip path of the board's outline


def _meets(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _within(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _cut(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _make_frame(thing, view, box, origin=(BORDER, BORDER), width=None):
    w, h = box.x1 - box.x0, box.y1 - box.y0
    across = h if view.turn in (90, 270) else w
    return frame.Frame(box, thing.size, view.face, view.turn, (width or view.width) / across, origin)


def _parent(item_id):
    """The header a pin belongs to: hat.header.pin.19 -> hat.header."""
    head, sep, _ = item_id.rpartition(".pin.")
    return head if sep else None


# ---- pin 1 -----------------------------------------------------------------------------------
def _grow_for_pin1(thing, view, box, marked, sides):
    """The frame box grown until every marked connector's pin 1 marker is inside it."""
    for _ in range(20):
        scale = _make_frame(thing, view, box).scale
        need = box
        for item in marked:
            need = need.union(pin1.marker_box_mm(item, sides[item.id], scale))
        if box.contains(need, slack=1e-6):
            return box
        box = need
    raise DiagramError(f"view {view.id}: the frame does not settle round its pin 1 markers")


# ---- the board and its parts -------------------------------------------------------------------
def _on_thing_edge(thing, item):
    """Whether the item's box touches the edge of its thing, in millimetres, to EDGE_TOL."""
    b, (w, h) = item.box, thing.size
    return min(b.x0, b.y0, w - b.x1, h - b.y1) <= EDGE_TOL


def _board_edge(board, box):
    """The side of the board on the canvas ("left", "right", "top", "bottom") that a part's box lies nearest."""
    gaps = {"left": abs(box[0] - board[0]), "top": abs(box[1] - board[1]), "right": abs(box[2] - board[2])}
    gaps["bottom"] = abs(box[3] - board[3])
    return min(gaps, key=gaps.get)


def _board(pic, thing, clip):
    x0, y0, x1, y1 = pic.frame.box_px(model.Box(0, 0, *thing.size))
    pic.thing_px = (x0, y0, x1, y1)
    pic.board_clip = f"{clip}-board"
    pic.sh.add(f'<clipPath id="{pic.board_clip}"><rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" ')
    pic.sh.add(f'height="{y1 - y0:.1f}"/></clipPath>')
    pic.sh.add(f'<g id="{thing.key}" clip-path="url(#{clip})">')
    pic.sh.rect(x0, y0, x1 - x0, y1 - y0, fill=BOARD, stroke=MUTED, sw=1.5)
    pic.sh.add("</g>")


def _pitch_px(thing, scale):
    """Per header, the distance between neighbouring pins on the canvas."""
    centres = {}
    for item in thing.items.values():
        head = _parent(item.id)
        if head is not None:
            b = item.box
            centres.setdefault(head, []).append(((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2))
    out = {}
    for head, cs in centres.items():
        gaps = [math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(cs) for b in cs[i + 1 :]]
        out[head] = (min(gaps) if gaps else 0.0) * scale
    return out


def _part(pic, thing, item, muted, pitch, inset=False):
    """One item, in its own group. Returns its box on the canvas, or None if it is too small to draw."""
    sh, fr = pic.sh, pic.frame
    x0, y0, x1, y1 = fr.box_px(item.box)
    w, h = x1 - x0, y1 - y0
    if inset and min(w, h) < 2:
        return None
    sh.add(f'<g id="{item.id}">' if not inset else "<g>")
    outline = {"fill": "none", "stroke": GREY, "sw": 1.5}
    if item.kind == "pin":
        # a muted pin keeps its name, its number, in grey (issue 267)
        numbered = not inset and pitch.get(_parent(item.id), 0) >= NUMBERED_PITCH
        if numbered:
            side = max(w, min(0.8 * pitch[_parent(item.id)], NUMBER_SIDE))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            x0, y0, x1, y1, w, h = cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2, side, side
        sh.rect(x0, y0, w, h, **(outline if muted else {"fill": GOLD}))
        frame_px = (BORDER, BORDER, BORDER + fr.px_size[0], BORDER + fr.px_size[1])
        if numbered and _within((x0, y0, x1, y1), frame_px):
            size = max(9.0, min(22.0, side * 0.45))
            fg = GREY if muted else ON_GOLD
            sh.text((x0 + x1) / 2, (y0 + y1) / 2 + size * 0.35, item.label, size, "bold", fg, "middle")
    elif item.kind in ("standoff", "hole", "pad"):
        fill = "none" if muted else (GOLD if item.kind == "pad" else PART)
        stroke = GREY if muted else ("none" if item.kind == "pad" else PART_EDGE)
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, w / 2, h / 2
        if _on_thing_edge(thing, item):  # cut by the board's edge, as a half-round pad is: its centre is on it
            edge = _board_edge(pic.thing_px, (x0, y0, x1, y1))
            cx, cy, rx, ry = {"left": (x0, cy, w, ry), "right": (x1, cy, w, ry), "top": (cx, y0, rx, h)}.get(
                edge, (cx, y1, rx, h)
            )
        sh.add(
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5" clip-path="url(#{pic.board_clip})"/>'
        )
    elif item.kind == "header":
        sh.rect(x0, y0, w, h, **(outline if muted else {"fill": BODY}))
    elif item.kind == "contact":
        sh.rect(x0, y0, w, h, **(outline if muted else {"fill": GOLD}))
    else:  # socket, slot
        sh.rect(x0, y0, w, h, **(outline if muted else {"fill": PART, "stroke": PART_EDGE, "sw": 1.5}))
    sh.add("</g>")
    return (x0, y0, x1, y1)


def _mark(pic, box):
    x0, y0, x1, y1 = box
    pic.sh.add('<g data-mark="1">')
    pic.sh.rect(x0, y0, x1 - x0, y1 - y0, stroke=MARK_EDGE, sw=5.5, rx=4)
    pic.sh.rect(x0, y0, x1 - x0, y1 - y0, stroke=MARK, sw=3, rx=4)
    pic.sh.add("</g>")


# ---- labels ------------------------------------------------------------------------------------
def _label(pic, item, around, muted, board_px):
    """The item's name beside it, on the side with most free room that keeps off everything else: on a yellow
    tag when the view is about it, in grey on the board when it is muted, on a plain tag in a view about nothing."""
    sh, view = pic.sh, pic.view
    if muted:
        w, h = sh.width(item.label, LABEL_SIZE, "bold") + 4, LABEL_SIZE + 4
    else:
        w, h = sh.width(item.label, LABEL_SIZE, "bold") + 14, LABEL_H
    ax0, ay0, ax1, ay1 = around
    canvas = (TEXT_MARGIN, TEXT_MARGIN, sh.w - TEXT_MARGIN, sh.h - TEXT_MARGIN)
    room = {"right": canvas[2] - ax1, "left": ax0 - canvas[0], "below": canvas[3] - ay1, "above": ay0 - canvas[1]}
    places = []
    for side in sorted(room, key=lambda s: -room[s]):
        if side in ("right", "left"):
            x = ax1 + LABEL_GAP if side == "right" else ax0 - LABEL_GAP - w
            ys = ((ay0 + ay1 - h) / 2, ay0, ay1 - h)
            places += [(x, y) for y in ys]
        else:
            y = ay1 + LABEL_GAP if side == "below" else ay0 - LABEL_GAP - h
            xs = ((ax0 + ax1 - w) / 2, ax0, ax1 - w)
            places += [(x, y) for x in xs]
    own = (item.id, f"{item.id}.")
    for x, y in places:
        box = (x, y, x + w, y + h)
        if not _within(box, board_px if muted else canvas):
            continue
        if any(_meets(box, t[:4]) for t in pic.taken if not str(t[4]).startswith(own)):
            continue
        sh.add(f'<g data-label-of="{item.id}">')
        if muted:
            sh.text(x + w / 2, y + h / 2 + LABEL_SIZE * 0.35, item.label, LABEL_SIZE, "bold", GREY, "middle")
        elif view.highlight:
            sh.tag(x, y + h / 2, item.label, MARK, size=LABEL_SIZE, h=h, fg=ON_MARK, stroke=MARK_EDGE)
        else:
            sh.tag(x, y + h / 2, item.label, BOX, size=LABEL_SIZE, h=h, fg=INK, stroke=INK)
        sh.add("</g>")
        pic.taken.append((*box, f"label {item.label!r}"))
        return
    raise DiagramError(f"view {view.id}: label {item.label!r} of {item.id} has no room beside it in the frame")


# ---- the inset ---------------------------------------------------------------------------------
def _inset_place(pic, thing, targets, keep):
    """The inset's box in the corner of the frame farthest from `targets` that covers at most a tenth of
    each of them and none of `keep`."""
    fr, view = pic.frame, pic.view
    w, h = thing.size
    if view.turn in (90, 270):
        w, h = h, w
    k = INSET / max(w, h)
    iw, ih = w * k + 2 * INSET_PAD, h * k + 2 * INSET_PAD
    fx0, fy0 = BORDER, BORDER
    fx1, fy1 = BORDER + fr.px_size[0], BORDER + fr.px_size[1]
    corners = [
        (fx0 + INSET_GAP, fy0 + INSET_GAP),
        (fx1 - INSET_GAP - iw, fy0 + INSET_GAP),
        (fx0 + INSET_GAP, fy1 - INSET_GAP - ih),
        (fx1 - INSET_GAP - iw, fy1 - INSET_GAP - ih),
    ]
    tx = sum((t[0] + t[2]) / 2 for t in targets) / len(targets)
    ty = sum((t[1] + t[3]) / 2 for t in targets) / len(targets)
    corners.sort(key=lambda c: -math.hypot(c[0] + iw / 2 - tx, c[1] + ih / 2 - ty))
    for x, y in corners:
        box = (x, y, x + iw, y + ih)
        if not _within(box, (fx0, fy0, fx1, fy1)):
            continue
        if any(_area(_cut(box, t)) > INSET_COVER * _area(t) for t in targets):
            continue
        if any(_meets(box, t) for t in keep):
            continue
        return box, k
    raise DiagramError(f"view {view.id}: no corner has room for the inset")


def _inset(pic, thing, place, k, marked):
    (x0, y0, x1, y1), view = place, pic.view
    sh = pic.sh
    sh.add('<g data-inset="1">')
    sh.rect(x0, y0, x1 - x0, y1 - y0, fill=BOX, stroke=INK, sw=1.5, rx=3)
    whole = model.Box(0, 0, *thing.size)
    inner = frame.Frame(whole, thing.size, view.face, view.turn, k, (x0 + INSET_PAD, y0 + INSET_PAD))
    small = Picture(sh, inner, view, [])
    ix0, iy0, ix1, iy1 = inner.box_px(whole)
    sh.add(f'<clipPath id="inset-frame"><rect x="{ix0:.1f}" y="{iy0:.1f}" width="{ix1 - ix0:.1f}" ')
    sh.add(f'height="{iy1 - iy0:.1f}"/></clipPath>')
    _board(small, thing, "inset-frame")
    for item in _on_face(thing, view, whole):
        _part(small, thing, item, True, {}, inset=True)
    for item in _on_face(thing, view, whole):
        if item.id in marked:  # pin 1 of the connectors marked in the picture, no other
            pin1.draw(small, item, pin1.side(item, whole), pin1.INSET_TRI, number=False)
    mx0, my0, mx1, my1 = inner.box_px(pic.frame.box.intersect(whole) or pic.frame.box)
    sh.rect(mx0, my0, mx1 - mx0, my1 - my0, stroke=MARK_EDGE, sw=3.5, rx=2)
    sh.rect(mx0, my0, mx1 - mx0, my1 - my0, stroke=MARK, sw=1.8, rx=2)
    sh.add("</g>")


# ---- the view ----------------------------------------------------------------------------------
def _on_face(thing, view, box):
    """The items of the thing on the face shown whose box meets `box`, by z."""
    items = [
        i
        for i in thing.items.values()
        if i.kind != "board" and i.face == view.face and i.box.intersect(box) is not None
    ]
    return sorted(items, key=lambda i: i.z)


def render(scene, view):
    """The view drawn: (the SVG with colour tokens, its facts)."""
    thing = scene.things[view.thing]
    highlight = [i.id for s in view.highlight for i in scene.select(s)]
    headers = [h for h in highlight if scene.item(h).kind == "header"]
    full = set(highlight) | {i for i in thing.items if _parent(i) in headers}

    crop = views.crop_box(scene, view)
    for item_id in highlight:
        if frame.visible_fraction(scene.item(item_id).box, crop, []) < 0.5:
            raise DiagramError(f"view {view.id}: less than half of {item_id} shows")
    if view.highlight:
        marked = [scene.item(i) for i in highlight if scene.item(i).kind in pin1.CONNECTORS]
    else:
        marked = [i for i in _on_face(thing, view, crop) if i.kind in pin1.CONNECTORS and crop.contains(i.box)]
    marked = [i for i in marked if i.pin1 is not None]
    scale = _make_frame(thing, view, crop).scale
    parts = _on_face(thing, view, crop)
    sides = pin1.sides(marked, crop, parts, scale)
    box = _grow_for_pin1(thing, view, crop, marked, sides)
    fr = _make_frame(thing, view, box)
    pw, ph = fr.px_size
    sh = Sheet(round(pw) + 2 * BORDER, math.ceil(ph - 1e-6) + 2 * BORDER)
    pic = Picture(sh, fr, view, [])

    drawn = _on_face(thing, view, box)
    for item in drawn:
        if item.label and item.kind != "pin" and len(item.label.split()) > WORDS:
            raise DiagramError(f"view {view.id}: label {item.label!r} of {item.id} has more than four words")
    muted = [i.id for i in drawn if view.highlight and i.id not in full]

    frame_px = (BORDER, BORDER, BORDER + pw, BORDER + ph)
    sh.add(f'<clipPath id="frame"><rect x="{BORDER}" y="{BORDER}" width="{pw:.1f}" height="{ph:.1f}"/></clipPath>')
    _board(pic, thing, "frame")
    board_px = _cut(fr.box_px(model.Box(0, 0, *thing.size)), frame_px)
    pitch = _pitch_px(thing, fr.scale)
    seen = {}
    sh.add('<g clip-path="url(#frame)">')
    for item in drawn:
        seen[item.id] = _cut(_part(pic, thing, item, item.id in muted, pitch), frame_px)
    sh.add("</g>")
    for item_id, b in seen.items():
        pic.taken.append((*b, item_id))
    marks = {}
    for s in view.highlight:
        boxes = [seen[i.id] for i in scene.select(s) if i.id in seen]
        b = boxes[0]
        for o in boxes[1:]:
            b = (min(b[0], o[0]), min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3]))
        marks[s] = (b[0] - MARK_PAD, b[1] - MARK_PAD, b[2] + MARK_PAD, b[3] + MARK_PAD)
        _mark(pic, marks[s])
        pic.taken.append((*marks[s], s))
    for item in marked:
        pin1.draw(pic, item, sides[item.id], pin1.TRI)

    inset = None
    if view.crop:
        targets = [seen[i] for i in highlight if i in seen] or [
            seen[i.id] for s in view.crop for i in scene.select(s) if i.id in seen
        ]
        keep = [t[:4] for t in pic.taken if str(t[4]).startswith("pin 1 of")]
        inset = _inset_place(pic, thing, targets, keep)
        pic.taken.append((*inset[0], "the inset"))

    labels, muted_labels = [], []
    for item in drawn:
        if not item.label or item.kind == "pin":
            continue
        is_muted = item.id in muted
        around = marks.get(item.id, seen[item.id])
        _label(pic, item, around, is_muted, board_px)
        (muted_labels if is_muted else labels).append(item.label)

    if inset is not None:
        _inset(pic, thing, *inset, {i.id for i in marked})
    try:
        sh.check(view.id)
    except SystemExit as e:
        raise DiagramError(f"view {view.id}: {e}") from None
    facts = {
        "size": [sh.w, sh.h],
        "items": [i.id for i in drawn],
        "highlight": highlight,
        "muted": muted,
        "inset": inset is not None,
        "labels": labels,
        "muted_labels": muted_labels,
        "pin1": [i.id for i in marked],
        "frame_mm": [round(v, 3) for v in (box.x0, box.y0, box.x1, box.y1)],
    }
    return sh.svg(), facts
