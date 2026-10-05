# SPDX-License-Identifier: Apache-2.0
"""A picture for each step of building the two cables, from wiring.toml, on the sheets' canvas and photos.

cable(): "which wire goes in which cavity" for one cable of one carrier. Top to bottom, the half cable as
the reader holds it: the card with the socket and its pin 1, the Pico-EZmate plug with its six wires
hanging down, and the Dupont housing seen from the wire side, large, with in each cavity the number of
the wire that goes in it.

The pictures are narrower than a sheet and their text larger, so that at a page's text width (700 px on
screen, 180 mm on paper) nothing is smaller than about 15 px. gen.py's build() calls build() here, so they
are part of generated/ and of `gen.py --check`.
"""

import itertools
import math
import re
from dataclasses import dataclass

import wiring
from gen import (
    acorn_photo_down,
    blade_photos,
    crossings,
    draw_wires,
    highlight,
    pin_label,
    wedge,
)
from sheetlib import BODY, GOLD, INK, MUTED, PAPER, RED, SIGNALS, Sheet, label_of

W = 780  # canvas width; the height follows from what the cable needs
T = 17  # body text: 15 px where the picture is shown 700 px wide
LINE = 22  # from one line of body text to the next
PITCH = 60  # between two wires at the plug, as drawn: a whole number of lanes, so a wire is on a lane or well off it
LANE = 20  # between two wires running side by side
CAV_W, CAV_H, ROWS = 118, 44, 52  # a cavity, and from one row of cavities to the next
WIRE, HALO = 5.5, 11
GREY = "#9aa0a8"  # a wire that is cut back and is not VCC

# (carrier, connector) of every cable picture.
CABLES = [("blade", "P1"), ("blade", "P2"), ("pi5", "P1"), ("pi5", "P2")]

# What every picture rests on that nobody has yet checked with the parts in the hand. One list: when a
# photograph or a built cable settles a line, remove it here and it leaves every picture.
ASSUMPTIONS = [
    "the wire-side view is not mirrored",
    "the header's pin numbers run as shown",
    "plug pin 1 is nearest the M.2 edge",
    "the plug's shape, drawn from a photo",
    "where the housing's windows are",
]
ASSUMED = ("Not yet checked against a cable in the hand:", "Check wire 1 with a meter before trusting this view.")

# hat-ccw.jpg, in photo pixels: the part shown, the centres of the header's two columns, the centre of
# its first row, and from one row to the next.
HAT = {"crop": (260, 40, 510, 520), "columns": (449, 471), "row": 84, "pitch": 21.68}


@dataclass
class Housing:
    """The Dupont housing one cable ends in."""

    header: str  # key of the header it sits on
    first: int  # the header pins it covers, first to last
    last: int
    cavities: dict  # header pin -> the signal whose wire goes in that cavity, or None: stays empty
    cut: list  # the connector's signals that go in no cavity: cut back


def housing(c, connector):
    """Which wire of `connector` goes in which cavity of its housing on carrier `c`."""
    pins = wiring.CONNECTORS[connector]["pins"]
    wired = {s: c.wires[s] for s in pins if s in c.wires}
    headers = {h for h, _ in wired.values()}
    if len(headers) != 1:
        raise wiring.WiringError(f"{c.key}: the wires of {connector} go to {len(headers)} headers, not one")
    key = headers.pop()
    spans = {span for _, pin in wired.values() for span in c.headers[key].housings if span[0] <= pin <= span[1]}
    if len(spans) != 1:
        raise wiring.WiringError(f"{c.key}: the wires of {connector} go to {len(spans)} housings, not one")
    first, last = spans.pop()
    cavities = dict.fromkeys(range(first, last + 1))
    for s, (_, pin) in wired.items():
        cavities[pin] = s
    return Housing(key, first, last, cavities, [s for s in pins if s not in wired])


def turned(c, plan):
    """{signal: the name of the pin its wire sits on when the housing is turned end for end}.

    Turned by half a turn, the cavity of pin n sits on pin first + last - n, however the numbers run.
    """
    pins = c.headers[plan.header].pins
    return {s: pin_label(pins[plan.first + plan.last - n]["name"]) for n, s in plan.cavities.items() if s}


def turned_warning(c, plan):
    """What turning the housing round does, in a sentence; it names a supply rail only if a wire lands on one."""
    rails = {}
    for s, name in turned(c, plan).items():
        if name in ("5 V", "3.3 V"):
            rails.setdefault(name, []).append(label_of(s))
    if rails:
        hits = " and ".join(
            f"{rail} on the {' and '.join(sigs)} wire{'s' if len(sigs) > 1 else ''}" for rail, sigs in rails.items()
        )
        return f"Turned round, the housing puts {hits}."
    return "Turned round, the housing puts its wires on the wrong pins."


# The cable's wires are all black (the note on the cable in wiring.toml's parts): the drawn colours are the signals'.
COLOURS = "Wire colours are for this picture only: the real wires are all black. Count from the plug's pin 1 end."
# How the card lies in the turned photo (gen.acorn_photo_down), for the reader holding it.
CARD_WAY_UP = "Acorn turned underside up, M.2 edge to your left."


def host_pin(c, name):
    """A pin's name with the host before it where the name alone does not say whose it is: "blade TX"."""
    if name in ("GND", "5 V", "3.3 V") or re.fullmatch(r"(GPIO|IO)\d+", name):
        return name
    return f"{c.host} {name}"


def file_name(c, connector):
    return f"acorn-cable-{c.key}-{connector.lower()}.svg"


# ----------------------------------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------------------------------
def wrap(sh, text, width, size=T, face="regular"):
    lines, line = [], ""
    for word in text.split(" "):
        trial = f"{line} {word}".strip()
        if line and sh.width(trial, size, face) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return [*lines, line]


def para(sh, x, y, text, width, face="regular", fill=INK, size=T):
    """`text` in lines no wider than `width`, the first with its baseline at y. Returns the next baseline."""
    for line in wrap(sh, text, width, size, face):
        sh.text(x, y, line, size, face, fill)
        y += LINE
    return y


def token(sh, cx, cy, n, s=30):
    """A wire's number, as it is shown wherever that wire is: in its place in the plug and in its cavity."""
    box = (cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)
    sh.rect(box[0], box[1], s, s, fill=GOLD, stroke=BODY, sw=1.5, rx=4)
    sh.text(cx, cy + s * 0.25, str(n), s * 0.7, "bold", BODY, "middle", box=box, on_wire=True)


# ----------------------------------------------------------------------------------------------
# Pieces
# ----------------------------------------------------------------------------------------------
def assumptions(sh, x, y, w):
    """The box of what is not yet checked. Returns its bottom."""
    pad, gap = 8, 24
    col_w = (w - 2 * pad - gap) / 2
    items = [wrap(sh, item, col_w - 14) for item in ASSUMPTIONS]
    # two columns of items, split where the taller column is shortest
    split = min(range(len(items) + 1), key=lambda k: max(sum(map(len, items[:k])), sum(map(len, items[k:]))) * 10 - k)
    columns = [items[:split], items[split:]]
    rows = max(sum(map(len, col)) for col in columns)
    h = (2 + rows) * LINE + 2 * pad - 2
    box = (x, y, x + w, y + h)
    sh.rect(x, y, w, h, fill="#fff8e1", stroke=INK, sw=1.5, rx=8)
    top = y + pad + T * 0.8
    sh.text(x + pad, top, ASSUMED[0], T, "bold", INK, box=box)
    for i, col in enumerate(columns):
        cx, ty = x + pad + i * (col_w + gap), top + LINE
        for item in col:
            sh.add(f'<circle cx="{cx + 4}" cy="{ty - T * 0.3:.1f}" r="3" fill="{INK}"/>')
            for line in item:
                sh.text(cx + 14, ty, line, T, "regular", INK, box=box)
                ty += LINE
    sh.text(x + pad, top + (1 + rows) * LINE, ASSUMED[1], T, "bold", INK, box=box)
    return y + h


def plug(sh, x1, y, pins):
    """The Pico-EZmate plug seen from above as it sits in the card's socket, its wires leaving downwards.

    Sketched from the plug seated in P1 in the card photo (the block, the row of contacts showing through
    its top, the wires out of one long side): no latch or key is drawn, because none is established.
    x1: the x of wire 1. Returns ({signal: where its wire leaves}, the body's rect).
    """
    body = (x1 - 34, y, x1 + 5 * PITCH + 34, y + 58)
    sh.rect(body[0], body[1], body[2] - body[0], 58, fill=BODY, rx=7)
    sh.rect(body[0] + 8, y + 46, body[2] - body[0] - 16, 12, fill="#3a3d42")  # the side the wires leave by
    out = {}
    for i, sig in enumerate(pins):
        token(sh, x1 + i * PITCH, y + 24, i + 1)
        out[sig] = (x1 + i * PITCH, y + 58)
    return out, body


def cut_ends(sh, c, pins, out, cut, y, right, notes_y=0):
    """The wires that go in no cavity: each a short stub ending in a piece of heat-shrink tube, with why.

    Neighbours cut for the same reason share one note. The notes are in a column to the right of the last
    wire, each naming its wires. Returns (the bottom of the stubs, the bottom of the notes, the notes' x).
    """
    groups = []  # [[signals], reason], from the right
    for sig in reversed(cut):
        what = wiring.SIGNALS[sig]["what"]
        why = f"{what}: it must never reach the host." if sig == "VCC" else f"{what}: not used on a {c.name}."
        if groups and groups[-1][1] == why and pins.index(groups[-1][0][-1]) == pins.index(sig) + 1:
            groups[-1][0].append(sig)
        else:
            groups.append([[sig], why])
    x, ty = max(out[s][0] for s in cut) + 20, max(y, notes_y) + 15  # the notes: below whatever is above them
    for sigs, why in groups:
        colour = RED if "VCC" in sigs else GREY
        for sig in sigs:
            wx, y0 = out[sig]
            sh.add(f'<line x1="{wx}" y1="{y0}" x2="{wx}" y2="{y + 6}" stroke="{colour}" stroke-width="{WIRE}"/>')
            sh.rect(wx - 8, y, 16, 28, fill=colour, stroke=INK, sw=1.5, rx=5)
        numbers = sorted(pins.index(s) + 1 for s in sigs)
        who = f"wire {numbers[0]}" if len(numbers) == 1 else "wires " + " and ".join(str(n) for n in numbers)
        fill = RED if "VCC" in sigs else INK
        ty = para(sh, x, ty, f"{who}: cut back, heat shrink over the end", right - x, "bold", fill)
        ty = para(sh, x, ty, why, right - x, "regular", fill) + 6
    return y + 28, ty - LINE, x


def choose_lanes(wires):
    """Give each wire a lane: the order with the fewest crossings, on the way to the lanes and at the cavities.

    A wire is {"row": its cavity's row, "side": -1 if it turns left into its cavity, 1 if right}, in the
    order of the plug. Returns ((crossings, crossings on the way to the lanes), the lane of each wire).
    """
    best = None
    for order in itertools.permutations(range(len(wires))):
        swaps = sum(1 for i, j in itertools.combinations(range(len(wires)), 2) if order[i] > order[j])
        over = 0  # a wire turning into its cavity crosses each lane on that side whose wire goes further down
        for (a, la), (b, lb) in itertools.permutations(zip(wires, order, strict=True), 2):
            if (lb < la if a["side"] < 0 else lb > la) and b["row"] > a["row"]:
                over += 1
            if a["row"] == b["row"] and a["side"] < b["side"] and la > lb:
                over += 100  # two cavities of one row: their wires would meet between them
        if best is None or (swaps + over, swaps) < best[0]:
            best = ((swaps + over, swaps), order)
    return best


def route(wires, lanes, top, cavity_edge):
    """Each wire down from the plug, across to its lane at a level of its own, down the lane and into its cavity.

    Returns (paths, (crossings, shared tracks, tight spots)), as gen.py's route().
    """
    order = choose_lanes(wires)[1]
    levels = [top + LANE * k for k in range(len(wires))]

    def build(level_of):
        paths = []
        for w, lane, level in zip(wires, order, level_of, strict=True):
            x, y = w["start"]
            lx = lanes[lane]
            path = [(x, y), (x, level), (lx, level), (lx, w["cy"]), (cavity_edge(w), w["cy"])]
            paths.append(path if x != lx else [path[0], path[3], path[4]])
        return paths

    def cost(level_of):
        cross, shared, tight = crossings(build(level_of))
        return shared * 1000 + tight * 40 + cross * 10

    best = min(itertools.permutations(levels), key=cost)
    paths = build(best)
    return paths, crossings(paths)


def view_sketch(sh, x, y):
    """ "Seen from the wire side", side on: a housing on header pins, its wires out of the top, and the eye
    above them. The same on every picture. Returns its bottom."""
    sh.rect(x + 6, y + 100, 112, 7, fill="#c9ced6", stroke=MUTED, sw=1)  # the board
    sh.rect(x + 30, y + 90, 64, 10, fill=BODY)  # the header's plastic base
    for px in (46, 62, 78):
        sh.rect(x + px - 2, y + 72, 4, 18, fill=GOLD)
    sh.rect(x + 28, y + 46, 68, 36, fill="#3a3d42", stroke=INK, sw=1.5, rx=3)  # the housing
    sh.rect(x + 91, y + 62, 6, 12, fill=PAPER, stroke=INK, sw=1)  # a window in its side
    for px, bend in ((46, -1), (78, 1)):
        sh.add(
            f'<path d="M{x + px},{y + 46} v-12 q0,-12 {12 * bend},-16 l{10 * bend},-4" fill="none" stroke="{BODY}" '
            f'stroke-width="4.5" stroke-linecap="round"/>'
        )
    ex, ey = x + 62, y + 9
    sh.add(f'<path d="M{ex - 15},{ey} q15,-13 30,0 q-15,13 -30,0 z" fill="#fff" stroke="{INK}" stroke-width="1.8"/>')
    sh.add(f'<circle cx="{ex}" cy="{ey}" r="4" fill="{INK}"/>')
    sh.add(f'<path d="M{ex},{ey + 11} v20" stroke="{INK}" stroke-width="2.5"/>')
    sh.add(f'<path d="M{ex - 6},{ey + 27} l6,10 l6,-10 z" fill="{INK}"/>')
    for ly, label in ((26, "wires"), (52, "housing"), (74, "window"), (96, "pins")):
        sh.add(f'<path d="M{x + 100},{y + ly - 5} h10" stroke="{MUTED}" stroke-width="1.2"/>')
        sh.text(x + 114, y + ly, label, T, "regular", MUTED)
    sh.text(x, y + 132, "You are looking down", T, "bold")
    sh.text(x, y + 132 + LINE, "on the wires.", T, "bold")
    return y + 132 + LINE + 6


# ----------------------------------------------------------------------------------------------
# Where the housing goes on each host: a block `w` wide from (x, y), its words on the left and the close-up
# the housing is drawn like on the right. Returns its bottom.
# ----------------------------------------------------------------------------------------------
def host_blade(sh, c, plan, x, y, w):
    data = c.headers[plan.header]
    close = 150  # the close-up's width
    tw = w - close - 14
    ty = para(sh, x, y + 14, f"{c.name}, from above", tw, "bold")
    hl, (_ix, iy, _iw, ih) = blade_photos(
        sh, x, ty - 8, tw, (x + tw + 14, y, close), only=plan.header, title=0, beside=True
    )
    # narrower than the board: the cone from the header on the board to the close-up passes on the right
    ty = para(sh, x, ty + tw * 521 / 3120 + 26, "Housing drawn as in the close-up.", tw * 0.8)
    rect = hl[plan.header]
    name_w = sh.width(data.name, T, "bold") + 12
    centre = min((rect[0] + rect[2]) / 2, x + w - name_w / 2)
    sh.tag(centre, iy + ih + 17, data.name, "#fff", size=T, h=24, anchor="middle", fg=INK, stroke=INK, pad=6)
    return max(ty - LINE + 8, iy + ih + 31)


def host_pi5(sh, c, plan, x, y, w):
    data = c.headers[plan.header]
    crop, (left, right) = HAT["crop"], HAT["columns"]
    photo = 119  # the photo's width
    tw = w - photo - 62  # the pin numbers are either side of the header, which is at the photo's right edge
    (px, py, _pw, ph), k = sh.photo("hat-ccw.jpg", x + tw + 22, y, photo, crop=crop)
    rows = data.grid(1, data.count)
    r0, r1 = (next(r for r, row in enumerate(rows) if n in row) for n in (plan.first, plan.last))
    if rows[0][0] != 1 or len(rows[0]) != 2:
        raise wiring.WiringError(f"{c.key}: the photo of the {data.name} is of two columns with pin 1 top left")

    def row_y(r):
        return py + (HAT["row"] + HAT["pitch"] * r - crop[1]) * k

    half = HAT["pitch"] * k / 2
    frame = (px + (left - crop[0] - 11) * k, row_y(r0) - half, px + (right - crop[0] + 11) * k, row_y(r1) + half)
    highlight(sh, frame)
    # the housing's first pin beside its first row, its last pin beside its last row, and pin 1 if there is room
    style = {"size": T, "h": 20, "fg": INK, "stroke": INK, "pad": 4}
    sh.tag(frame[0] - 5, row_y(r0), str(plan.first), "#fff", anchor="end", **style)
    sh.tag(frame[2] + 5, row_y(r1), str(plan.last), "#fff", **style)
    if r0 >= 2:
        # above its row, clear of the housing's own number, with a line to the pin
        sh.tag(frame[0] - 5, row_y(0) - 12, "pin 1", "#fff", anchor="end", **style)
        pin1 = px + (left - crop[0]) * k
        sh.add(
            f'<path d="M{frame[0] - 5:.1f},{row_y(0) - 12:.1f} L{pin1:.1f},{row_y(0):.1f}" stroke="{INK}" '
            'stroke-width="2"/>'
        )
    ty = para(sh, x, y + 14, "Pi 5 with the PoE M.2 HAT+, from above", tw, "bold")
    ty = para(
        sh,
        x,
        ty + 4,
        f"Pins {plan.first} to {plan.last} are rows {r0 + 1} to {r1 + 1} of {len(rows)}, counted from pin 1.",
        tw,
    )
    ty = para(sh, x, ty + 4, "The photo shows the HAT without its stacking header.", tw, fill=MUTED)
    return max(ty - LINE + 8, py + ph)


HOSTS = {"blade": host_blade, "pi5": host_pi5}


# ----------------------------------------------------------------------------------------------
# The picture
# ----------------------------------------------------------------------------------------------
def cable(c, connector):
    """The picture for one cable. Returns (svg, (crossings, shared tracks, tight spots))."""
    conn = wiring.CONNECTORS[connector]
    pins = conn["pins"]
    plan = housing(c, connector)
    data = c.headers[plan.header]
    grid = data.grid(plan.first, plan.last)
    cols = data.columns
    if cols > 2:
        raise wiring.WiringError(f"{c.key}: a housing of {cols} columns is not drawn yet")
    shape = f"{cols}×{len(grid)}"
    sh = Sheet(W, 100)  # the height is set once everything is placed

    sh.text(30, 34, f"{connector} cable ({conn['what']}) for a {c.name}:", 26, "bold")
    sh.text(30, 58, f"which wire goes in which cavity of the {shape} Dupont housing", 19, "bold", MUTED)
    sh.add(f'<line x1="30" y1="70" x2="{W - 10}" y2="70" stroke="{INK}" stroke-width="1.5"/>')

    # The card, and under its socket the plug the same way round; beside the card, where the housing will go.
    sockets, (px, py, pw, ph) = acorn_photo_down(sh, 30, 132, 360, T, crop=(0, 60, 160, 590))
    host_bottom = HOSTS[c.key](sh, c, plan, px + pw + 20, 84, W - 10 - (px + pw + 20))
    x1 = 164
    out, body = plug(sh, x1, max(py + ph + 30, host_bottom - 30), pins)
    # the cone is as wide on the plug as the socket it leaves, so it never spreads into the words beside it
    half = (sockets[connector][2] - sockets[connector][0]) / 2
    middle = (body[0] + body[2]) / 2
    wedge(sh, sockets[connector], (middle - half, body[1], middle + half, body[3]), down=True)
    note_x = body[2] + 14
    ty = para(sh, note_x, max(body[1] + 20, host_bottom + 24), "The plug, seen from above", W - 10 - note_x, "bold")
    ty = para(sh, note_x, ty, "as it sits in the socket.", W - 10 - note_x, "bold")
    ty = para(sh, note_x, ty, CARD_WAY_UP, W - 10 - note_x)
    tag_y = body[3] + 24
    stubs_bottom, cut_bottom, cut_x = cut_ends(sh, c, pins, out, plan.cut, tag_y + 18, W - 10, ty - LINE + 8)

    # The housing: where its cavities and the wires' lanes are.
    wired = [s for s in pins if s not in plan.cut]
    where = {n: (r, col) for r, row in enumerate(grid) for col, n in enumerate(row)}
    names = {n: host_pin(c, pin_label(data.pins[n]["name"])) for n in plan.cavities}
    resistors = [s for s in wired if s in c.resistors]
    if resistors and cols > 1:
        raise wiring.WiringError(f"{c.key}: a series resistor at a housing of two columns is not drawn yet")
    r_w = sh.width(c.resistor_value, T, "bold") + 16 if resistors else 0
    gap = r_w + 60 if resistors else 16  # between the lanes and a single column: room for the resistor
    wires = []
    for sig in wired:
        n = next(pin for pin, s in plan.cavities.items() if s == sig)
        wires.append({"sig": sig, "pin": n, "colour": SIGNALS[sig][0], "start": out[sig], "row": where[n][0]})
    # The way each wire turns into its cavity. Two columns: outwards from the channel between them. One
    # column: the wires come down on whichever side of it gives fewer crossings.
    for w in wires:
        w["side"] = -1 if where[w["pin"]][1] == 0 else 1
    if cols == 1 and choose_lanes([{**w, "side": -1} for w in wires])[0] < choose_lanes(wires)[0]:
        for w in wires:
            w["side"] = -1
    # The lanes are on the grid the plug's wires are on (PITCH is a whole number of lanes), so that a wire
    # coming down from the plug is either on a lane or well clear of the next one.
    if cols == 2 or wires[0]["side"] > 0:
        centre = x1 + 2.5 * PITCH if cols == 2 else sum(out[s][0] for s in wired) / len(wired)
        first_lane = x1 + LANE * math.floor((centre - x1) / LANE - (len(wired) - 1) / 2)
    else:  # the column is at the left margin, behind the names of its pins, and the lanes beyond it
        cav = 30 + max(sh.width(name, T, "bold") for name in names.values()) + 26
        first_lane = x1 + LANE * math.ceil((cav + CAV_W + gap + LANE - x1) / LANE)
    lanes = [first_lane + LANE * i for i in range(len(wired))]
    if cols == 2:
        cav_x = (lanes[0] - LANE - CAV_W, lanes[-1] + LANE)
    else:
        cav_x = (lanes[-1] + LANE + gap,) if wires[0]["side"] > 0 else (cav,)
    body_x = (cav_x[0] - 10, cav_x[-1] + CAV_W + 10)
    level0 = stubs_bottom + 10  # the first level a wire may cross to its lane at: below the cut ends
    hy = level0 + LANE * (len(wired) - 1) + 32
    if body_x[1] + 80 > cut_x:  # the housing reaches under the notes of the cut wires
        hy = max(hy, cut_bottom + 40)

    def cavity(n):
        r, col = where[n]
        return cav_x[col], hy + 10 + r * ROWS

    for w in wires:
        w["cy"] = cavity(w["pin"])[1] + CAV_H / 2
    paths, score = route(wires, lanes, level0, lambda w: cavity(w["pin"])[0] + (CAV_W if w["side"] < 0 else 0))
    if score[1]:
        raise SystemExit(f"{file_name(c, connector)}: {score[1]} wires share a track")

    body_h = len(grid) * ROWS + 10
    sh.rect(body_x[0], hy, body_x[1] - body_x[0], body_h, fill="#f1f3f5", stroke=INK, sw=3, rx=10)
    draw_wires(sh, wires, paths, WIRE, HALO)
    for sig, (x, _y) in out.items():  # the signal's tag on every wire as it leaves the plug
        colour = RED if sig == "VCC" else SIGNALS[sig][0] if sig in wired else GREY
        sh.tag(x, tag_y, label_of(sig), colour, size=T, h=24, anchor="middle", pad=5, on_wire=True)

    for n, sig in plan.cavities.items():
        x, y = cavity(n)
        col = where[n][1]
        cy = y + CAV_H / 2
        box = (x, y, x + CAV_W, y + CAV_H)
        name = names[n]
        rail = name in ("5 V", "3.3 V")
        # the side of the housing this cavity is on: its own column's, or the side away from the wires
        outer = (-1 if col == 0 else 1) if cols == 2 else wires[0]["side"]
        edge = body_x[0] if outer < 0 else body_x[1]
        sh.rect(edge - 4, cy - 9, 8, 18, fill=INK, rx=2)  # its window
        sh.add(f'<g id="cavity-{n}">')  # what is in the cavity, as one group: test_steps.py reads it back
        if sig:
            sh.rect(x, y, CAV_W, CAV_H, fill="#fff", stroke=SIGNALS[sig][0], sw=4, rx=6)
            token(sh, x + 24, cy, pins.index(sig) + 1)
            sh.tag(x + 46, cy + 9, label_of(sig), SIGNALS[sig][0], size=T, h=23, pad=5)
            sh.contain.append((sh.boxes[-1][0], box, f"the {label_of(sig)} tag of cavity {n}"))
        else:
            danger = name == "5 V"
            sh.rect(
                x, y, CAV_W, CAV_H, fill="#fdecea" if danger else "#d9dbde", stroke=RED if danger else MUTED,
                sw=3 if danger else 1.5, rx=6, extra="" if danger else 'stroke-dasharray="5 4"',
            )  # fmt: skip
            sh.text(x + 9, cy + 6, "empty", T, "bold" if danger else "regular", RED if danger else MUTED, box=box)
            if danger:
                sh.text(x + CAV_W - 8, cy + 17, name, T, "bold", RED, "end", box=box)
        sh.text(x + CAV_W - 8, cy - 9, str(n), T, "regular", MUTED, "end", box=box)
        sh.add("</g><!--/cavity-->")
        note_fill, face = (RED, "bold") if name == "5 V" else (INK, "regular") if sig or rail else (MUTED, "regular")
        sh.text(edge + outer * 12, cy + 6, name, T, face, note_fill, "end" if outer < 0 else "start")
    for sig in resistors:  # in the wire's last run, beside its cavity, under heat shrink
        w = next(w for w in wires if w["sig"] == sig)
        near = lanes[-1] + LANE if w["side"] > 0 else lanes[0] - LANE  # where the lanes end, on the housing's side
        cx, cy = (near + (body_x[0] if w["side"] > 0 else body_x[1])) / 2, w["cy"]
        sh.rect(cx - r_w / 2 - 12, cy - 19, r_w + 24, 38, fill="#fff", stroke=INK, sw=1.5, rx=12, extra='opacity="0.9"')
        sh.rect(cx - r_w / 2, cy - 12, r_w, 24, fill="#fff", stroke=w["colour"], sw=3, rx=3)
        sh.text(cx, cy + 6, c.resistor_value, T, "bold", w["colour"], "middle", on_wire=True)
        sh.text(cx, cy - 26, "in heat shrink", T, "regular", INK, "middle")
    kx, ky = body_x[0] + 3, hy + 3  # pin `first` is the top left cavity (Header.grid): its corner is the one to mark
    if where[plan.first] != (0, 0):
        raise wiring.WiringError(f"{c.key}: pin {plan.first} is not the top left cavity of its housing")
    sh.add(f'<polygon points="{kx},{ky} {kx + 20},{ky} {kx},{ky + 20}" fill="{RED}"/>')
    sh.text(body_x[0], hy - 9, "mark this corner", T, "bold", RED)

    # Beside the housing, how it is seen.
    side_x = W - 10 - 185
    side_y = view_sketch(sh, side_x, max(hy - 4, cut_bottom + 16))
    on = data.name if (plan.first, plan.last) == (1, data.count) else f"{data.name} pins {plan.first} to {plan.last}"
    view = (
        f"{shape} Dupont housing, seen from the wire side,",
        f"as it will sit on the {on} with the {c.name} seen from above.",
    )
    y = hy + body_h
    if cols == 2:
        y += LINE + 2
        sh.text(body_x[0], y, "The two columns are drawn apart to let the wires through.", T, "regular", MUTED)
    # the view in words: under the sketch if that ends about level with the housing, else under the housing
    lines = sum(len(wrap(sh, text, 185, face="bold")) for text in view)
    if side_y + lines * LINE <= y + 24:
        tx, ty, tw = side_x, side_y + LINE, 185
    else:
        tx, ty, tw = 30, max(y, side_y) + LINE + 4, W - 40
    for text in view:
        ty = para(sh, tx, ty, text, tw, "bold")
    # the next line: a full line below words that span the picture, a little less below words at the side
    y = max(y + 18, side_y + 18, ty - LINE + 21 if tx == side_x else ty + 2)

    # What the marks mean, the warnings, what is not yet checked, and whose photos these are.
    y = para(sh, 30, y, COLOURS, W - 40) + 6
    token(sh, 43, y - 6, "n", 26)
    x = 64 + sh.text(64, y, "wire number: its place in the plug", T) + 28
    sh.text(x, y, "n", T, "regular", MUTED)
    how = "printed beside the header" if data.printed else "counted on the header"
    sh.text(x + 18, y, f"pin number, {how}", T)
    ty = y + LINE + 4
    sh.rect(39, ty - 15, 8, 18, fill=INK, rx=2)
    ty = para(sh, 64, ty, "a small window in the side of the housing: a terminal's latch will face it", W - 74)
    for sig in resistors:
        ty = para(
            sh,
            30,
            ty + 6,
            f"{c.resistor_value} resistor: soldered into wire {pins.index(sig) + 1} ({label_of(sig)}), "
            "heat shrink over it and both joints.",
            W - 40,
            "bold",
        )
    ty = para(
        sh,
        30,
        ty + 8,
        f"Mark the pin {plan.first} corner first. {turned_warning(c, plan)}",
        W - 40,
        "bold",
        RED,
    )
    ty = assumptions(sh, 30, ty - LINE + 8, W - 40) + LINE
    sh.h = math.ceil(ty - LINE + 4)
    sh.check(file_name(c, connector))
    return sh.svg(), score


def build():
    """{file name: svg} for every cable picture."""
    out = {}
    for key, connector in CABLES:
        c = wiring.CARRIERS[key]
        svg, (cross, _shared, tight) = cable(c, connector)
        out[file_name(c, connector)] = svg
        print(f"{file_name(c, connector)}: {len(svg) // 1024} KiB, {cross} crossings, {tight} tight spots")
    return out
