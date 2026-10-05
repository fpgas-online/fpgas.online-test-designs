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

import tables
import wiring
from gen import (
    CREDITS,
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
    "which face of the plug shows its contacts",
    "the card's mounting pad is ground (from the M.2 standard, not measured on this card)",
]
ASSUMED = (
    "Not yet checked against a cable in the hand:",
    "Check wire 1 with a meter before cutting anything: the flag step shows how.",
)
BOX_LINE = 20  # from line to line in the box of assumptions
ACORN_PAD = (188, 0, 308, 80)  # the plated half-round mounting pad at the end of the card, in acorn-cw.jpg

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


def turned_rails(c, plan):
    """{supply rail: the signals whose wires land on it when the housing is turned end for end}."""
    rails = {}
    for s, name in turned(c, plan).items():
        if name in ("5 V", "3.3 V"):
            rails.setdefault(name, []).append(s)
    return rails


def turned_warning(c, plan):
    """What turning the housing round does, in a sentence; it names a supply rail only if a wire lands on one."""
    rails = turned_rails(c, plan)
    if rails:
        hits = " and ".join(
            f"{rail} on the {' and '.join(label_of(s) for s in sigs)} wire{'s' if len(sigs) > 1 else ''}"
            for rail, sigs in rails.items()
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
    h = (2 + rows) * BOX_LINE + 2 * pad - 2
    box = (x, y, x + w, y + h)
    sh.rect(x, y, w, h, fill="#fff8e1", stroke=INK, sw=1.5, rx=8)
    top = y + pad + T * 0.8
    sh.text(x + pad, top, ASSUMED[0], T, "bold", INK, box=box)
    for i, col in enumerate(columns):
        cx, ty = x + pad + i * (col_w + gap), top + BOX_LINE
        for item in col:
            sh.add(f'<circle cx="{cx + 4}" cy="{ty - T * 0.3:.1f}" r="3" fill="{INK}"/>')
            for line in item:
                sh.text(cx + 14, ty, line, T, "regular", INK, box=box)
                ty += BOX_LINE
    sh.text(x + pad, top + (1 + rows) * BOX_LINE, ASSUMED[1], T, "bold", INK, box=box)
    return y + h


def plug(sh, x1, y, pins, numbers=True, flip=False):
    """The Pico-EZmate plug seen from above as it sits in the card's socket, its wires leaving downwards.

    Sketched from the plug seated in P1 in the card photo (the block, the row of contacts showing through
    its top, the wires out of one long side): no latch or key is drawn, because none is established.
    x1: the x of wire 1. numbers: number the contacts. flip: the wires leave upwards.
    Returns ({signal: where its wire leaves}, the body's rect).
    """
    body = (x1 - 34, y, x1 + 5 * PITCH + 34, y + 58)
    sh.rect(body[0], body[1], body[2] - body[0], 58, fill=BODY, rx=7)
    sh.rect(body[0] + 8, y + (0 if flip else 46), body[2] - body[0] - 16, 12, fill="#3a3d42")  # where the wires leave
    out = {}
    for i, sig in enumerate(pins):
        if numbers:
            token(sh, x1 + i * PITCH, y + 24, i + 1)
        out[sig] = (x1 + i * PITCH, y + (0 if flip else 58))
    return out, body


def cut_ends(sh, c, pins, out, cut, y, right, notes_y=0, length=0, mark=True):
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
    if length and mark:  # a dimension mark beside the last stub: this much of the wire is left at the plug
        top = out[cut[-1]][1]
        sh.add(
            f'<path d="M{x - 6},{top} h8 M{x - 6},{y + 28} h8 M{x - 2},{top} V{y + 28}" stroke="{INK}" '
            'stroke-width="1.5"/>'
        )
        x += 12
    for sigs, why in groups:
        colour = RED if "VCC" in sigs else GREY
        for sig in sigs:
            wx, y0 = out[sig]
            sh.add(f'<line x1="{wx}" y1="{y0}" x2="{wx}" y2="{y + 6}" stroke="{colour}" stroke-width="{WIRE}"/>')
            sh.rect(wx - 8, y, 16, 28, fill=colour, stroke=INK, sw=1.5, rx=5)
        numbers = sorted(pins.index(s) + 1 for s in sigs)
        who = f"wire {numbers[0]}" if len(numbers) == 1 else "wires " + " and ".join(str(n) for n in numbers)
        fill = RED if "VCC" in sigs else INK
        how = f"cut off about {length} mm from the plug" if length else "cut back"
        ty = para(sh, x, ty, f"{who}: {how}, heat shrink over the end", right - x, "bold", fill)
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
    sockets, (px, py, pw, ph) = acorn_photo_down(sh, 30, 132, 360, T, crop=(0, 60, 134, 590))
    host_bottom = HOSTS[c.key](sh, c, plan, px + pw + 20, 84, W - 10 - (px + pw + 20))
    x1 = 164
    out, body = plug(sh, x1, max(py + ph + 30, host_bottom - 30), pins)
    # the cone is as wide on the plug as the socket it leaves, so it never spreads into the words beside it
    half = (sockets[connector][2] - sockets[connector][0]) / 2
    middle = (body[0] + body[2]) / 2
    wedge(sh, sockets[connector], (middle - half, body[1], middle + half, body[3]), down=True)
    tag_y, stubs_bottom, cut_bottom, cut_x = plug_notes(
        sh, c, pins, plan, out, body, max(body[1] + 20, host_bottom + 24), wiring.LENGTHS["cut_back"], mark=False
    )

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
    for w, path in zip(wires, paths, strict=True):  # where each wire ends, as drawn: test_steps.py reads it back
        number = pins.index(w["sig"]) + 1
        sh.add(f'<circle id="wire-{number}-end" cx="{path[-1][0]}" cy="{path[-1][1]}" r="0"/>')
    wire_tags(sh, out, wired, tag_y)

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
        resistor(sh, c, cx, cy, w["colour"])
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
        tx, ty, tw = 30, max(y, side_y) + LINE - 2, W - 40
    for text in view:
        ty = para(sh, tx, ty, text, tw, "bold")
    # the next line: a full line below words that span the picture, a little less below words at the side
    y = max(y + 12, side_y + 12, ty - LINE + 21 if tx == side_x else ty + 2)

    # What the marks mean, the warnings, what is not yet checked, and whose photos these are.
    y = para(sh, 30, y, COLOURS, W - 40) + 2
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
    ty = assumptions(sh, 30, ty - LINE + 5, W - 40) + LINE
    sh.h = math.ceil(ty - LINE + 4)
    sh.check(file_name(c, connector))
    return sh.svg(), score


# ----------------------------------------------------------------------------------------------
# Pieces the cavity picture and the step pictures share
# ----------------------------------------------------------------------------------------------
def plug_notes(sh, c, pins, plan, out, body, y, length=0, mark=True):
    """Beside the plug: how it is seen and how the card lies; under it, the cut-back wires with why.

    Returns (the y of the wires' signal tags, the bottom of the cut stubs, of their notes, the notes' x).
    """
    note_x = body[2] + 14
    ty = para(sh, note_x, y, "The plug, seen from above", W - 10 - note_x, "bold")
    ty = para(sh, note_x, ty, "as it sits in the socket.", W - 10 - note_x, "bold")
    ty = para(sh, note_x, ty, CARD_WAY_UP, W - 10 - note_x)
    tag_y = body[3] + 24
    return (tag_y, *cut_ends(sh, c, pins, out, plan.cut, tag_y + 18, W - 10, ty - LINE + 8, length, mark))


def wire_tags(sh, out, wired, tag_y):
    """The signal's tag on every wire as it leaves the plug: over the wires, so drawn after them."""
    for sig, (x, _y) in out.items():
        colour = RED if sig == "VCC" else SIGNALS[sig][0] if sig in wired else GREY
        sh.tag(x, tag_y, label_of(sig), colour, size=T, h=24, anchor="middle", pad=5, on_wire=True)


def resistor(sh, c, cx, cy, colour, label=None):
    """The series resistor in a wire, under its heat shrink, centred on (cx, cy). label: (x, y, anchor) of its words."""
    r_w = sh.width(c.resistor_value, T, "bold") + 16
    sh.rect(cx - r_w / 2 - 12, cy - 19, r_w + 24, 38, fill="#fff", stroke=INK, sw=1.5, rx=12, extra='opacity="0.9"')
    sh.rect(cx - r_w / 2, cy - 12, r_w, 24, fill="#fff", stroke=colour, sw=3, rx=3)
    sh.text(cx, cy + 6, c.resistor_value, T, "bold", colour, "middle", on_wire=True)
    if label is False:
        return
    lx, ly, anchor = label or (cx, cy - 26, "middle")
    sh.text(lx, ly, "in heat shrink", T, "regular", INK, anchor)


TERMINAL = "#c9a227"  # a crimp terminal's brass


def terminal_down(sh, x, y, colour):
    """A wire end at (x, y) pointing down: the bare tip, and a crimped terminal on it, its latch tab to the right.

    Returns the bottom."""
    sh.add(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + 8}" stroke="#b87333" stroke-width="3"/>')
    sh.rect(x - 5, y + 2, 10, 12, fill=TERMINAL, stroke=INK, sw=1.2, rx=2)  # the crimp
    sh.rect(x - 7, y + 14, 14, 30, fill=TERMINAL, stroke=INK, sw=1.2, rx=2)  # the box that takes the pin
    sh.add(f'<path d="M{x + 7},{y + 22} l5,3 v9 l-5,0 z" fill="{TERMINAL}" stroke="{INK}" stroke-width="1.2"/>')
    sh.add(f'<line x1="{x}" y1="{y - 3}" x2="{x}" y2="{y}" stroke="{colour}" stroke-width="{WIRE}"/>')
    return y + 44


def title(sh, first, second):
    sh.text(30, 34, first, 26, "bold")
    sh.text(30, 58, second, 19, "bold", MUTED)
    sh.add(f'<line x1="30" y1="70" x2="{W - 10}" y2="70" stroke="{INK}" stroke-width="1.5"/>')


SKETCHED = "Sketched, not from a photograph."


# ----------------------------------------------------------------------------------------------
# Step pictures
# ----------------------------------------------------------------------------------------------
FLAGS = (
    f"Put a numbered tape flag on each wire, 1 to 6, about {wiring.LENGTHS['flag_back']} mm back from the tip, "
    "clear of the end that will be cut and stripped later."
)


def number_list(numbers):
    """ "wire 6", "wires 4 and 5", "wires 1, 2 and 3"; a run of four or more as "wires 1 to 5"."""
    numbers = [int(n) for n in numbers]
    if len(numbers) == 1:
        return f"wire {numbers[0]}"
    if len(numbers) > 3 and numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"wires {numbers[0]} to {numbers[-1]}"
    return "wires " + ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"


def prepare(c, connector):
    """One cable's wires made ready: where wire 1 is, which wires are cut back and sleeved, which get a terminal."""
    conn = wiring.CONNECTORS[connector]
    pins = conn["pins"]
    plan = housing(c, connector)
    wired = [s for s in pins if s not in plan.cut]
    lengths = wiring.LENGTHS
    sh = Sheet(W, 100)
    title(sh, f"{connector} cable ({conn['what']}) for a {c.name}:", "find wire 1, then prepare the wires")
    # The card and its socket, as at the top of the cavity picture: this is how wire 1 is found.
    sockets, (px, py, pw, ph) = acorn_photo_down(sh, 30, 132, 360, T, crop=(0, 60, 160, 590))
    tx = px + pw + 20
    ty = para(sh, tx, 98, f"Press the plug into socket {connector}.", W - 10 - tx, "bold")
    ty = para(sh, tx, ty + 2, "Card underside up, M.2 edge to your left: wire 1 is the leftmost.", W - 10 - tx, "bold")
    ty = para(sh, tx, ty + 2, FLAGS, W - 10 - tx)
    x1 = 164
    out, body = plug(sh, x1, max(py + ph + 30, ty - LINE + 14), pins)
    half = (sockets[connector][2] - sockets[connector][0]) / 2
    middle = (body[0] + body[2]) / 2
    wedge(sh, sockets[connector], (middle - half, body[1], middle + half, body[3]), down=True)
    tag_y, stubs_bottom, cut_bottom, _cut_x = plug_notes(
        sh, c, pins, plan, out, body, body[1] + 20, lengths["cut_back"]
    )
    resistors = [s for s in wired if s in c.resistors]
    end = max(stubs_bottom + (130 if resistors else 70), cut_bottom - 40)
    for sig in wired:
        x, y = out[sig]
        colour = SIGNALS[sig][0]
        sh.add(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{end}" stroke="{colour}" stroke-width="{WIRE}"/>')
        sh.wire_segments.append((x, y, x, end))
        sh.add(f'<g id="terminal-wire-{pins.index(sig) + 1}">')
        bottom = terminal_down(sh, x, end, colour)
        sh.add("</g>")
        token(sh, x, bottom + 22, pins.index(sig) + 1)
    for sig in resistors:
        sh.add(f'<g id="resistor-wire-{pins.index(sig) + 1}">')  # test_steps.py reads this back
        resistor(sh, c, out[sig][0], end - 44, SIGNALS[sig][0], label=False)
        sh.add("</g>")
    wire_tags(sh, out, wired, tag_y)
    numbers = [pins.index(s) + 1 for s in wired]
    who = number_list(numbers)
    y = bottom + 62
    y = para(
        sh,
        30,
        y,
        f"{who[0].upper()}{who[1:]}: leave at full length, strip about {lengths['strip']} mm, crimp a terminal on "
        "each.",
        W - 40,
        "bold",
    )
    for sig in resistors:
        y = para(
            sh,
            30,
            y + 4,
            f"Wire {pins.index(sig) + 1} ({label_of(sig)}): the {c.resistor_value} resistor, in heat shrink, is "
            "soldered in before its terminal is crimped.",
            W - 40,
            "bold",
        )
    y = para(sh, 30, y + 4, COLOURS, W - 40)
    y = para(sh, 30, y + 4, "The plug and the terminals are sketched, not from a photograph.", W - 40, fill=MUTED)
    sh.h = math.ceil(y - LINE + 14)
    sh.check(f"prepare {c.key} {connector}")
    return sh.svg()


def resistor_picture(c, connector):
    """Fitting the series resistor into its wire, in the order the hands do it."""
    pins = wiring.CONNECTORS[connector]["pins"]
    sig = next(s for s in pins if s in c.resistors)
    n, colour, mm = pins.index(sig) + 1, SIGNALS[sig][0], wiring.LENGTHS["resistor"]
    sh = Sheet(W, 100)
    title(sh, f"The {c.resistor_value} resistor in wire {n} ({label_of(sig)}) of the {connector} cable", SKETCHED)
    x0, x1, cut_x = 150, 640, 500  # the wire from the plug's side to its free end, and where it is cut
    rows = (
        f"1. Cut wire {n} about {mm} mm from its free end.",
        f"2. Slide a piece of the {wiring.LENGTHS['resistor_tube']} mm tube onto the wire, clear of the cut.",
        f"3. Strip {wiring.LENGTHS['strip']} mm from each cut end. Trim the resistor's leads to "
        f"{wiring.LENGTHS['resistor_lead']} mm each. Solder it in.",
        "4. Slide the tube over the resistor and both joints and shrink it.",
    )
    y = 100
    for i, text in enumerate(rows):
        sh.text(30, y, text, T, "bold")
        wy = y + 44
        gap = 0 if i == 3 else 44
        sh.add(f'<line x1="{x0}" y1="{wy}" x2="{cut_x - gap}" y2="{wy}" stroke="{colour}" stroke-width="{WIRE}"/>')
        sh.add(f'<line x1="{cut_x + gap}" y1="{wy}" x2="{x1}" y2="{wy}" stroke="{colour}" stroke-width="{WIRE}"/>')
        sh.wire_segments += [(x0, wy, cut_x - gap, wy), (cut_x + gap, wy, x1, wy)]
        token(sh, x0 - 24, wy, n)
        if i == 0:
            sh.text(x0 - 46, wy + 6, "plug", T, "regular", MUTED, "end")
            sh.text(x1 + 12, wy + 6, "free end", T, "regular", MUTED)
            sh.add(
                f'<path d="M{cut_x + gap},{wy + 14} v12 M{x1},{wy + 14} v12 M{cut_x + gap},{wy + 20} H{x1}" '
                f'stroke="{INK}" stroke-width="1.5" fill="none"/>'
            )
            sh.text((cut_x + gap + x1) / 2, wy + 44, f"{mm} mm", T, "regular", INK, "middle")
            y += 30
        if i in (1, 2):  # the tube waiting on the wire
            sh.rect(x0 + 80, wy - 14, 110, 28, fill="#fff", stroke=INK, sw=1.5, rx=10, extra='opacity="0.9"')
            sh.text(x0 + 135, wy - 22, "tube", T, "regular", MUTED, "middle")
        if i == 2:
            r_w = sh.width(c.resistor_value, T, "bold") + 16
            sh.rect(cut_x - r_w / 2, wy - 12, r_w, 24, fill="#fff", stroke=colour, sw=3, rx=3)
            sh.text(cut_x, wy + 6, c.resistor_value, T, "bold", colour, "middle", on_wire=True)
        if i == 3:
            sh.add(f'<g id="resistor-wire-{n}">')
            resistor(sh, c, cut_x, wy, colour, label=False)
            sh.add("</g>")
        y += 88
    y = para(sh, 30, y, "Crimp the terminal on this wire only after this.", W - 40, "bold")
    sh.h = math.ceil(y - LINE + 14)
    sh.check(f"resistor {c.key} {connector}")
    return sh.svg()


def cut():
    """The bought cable, a plug at each end, and where to cut it."""
    pins = wiring.CONNECTORS["P1"]["pins"]
    sh = Sheet(W, 100)
    title(sh, "Cut the Pico-EZmate cable in half:", "each half becomes one of the two cables")
    x1, top, bottom = 120, 96, 330
    out, _ = plug(sh, x1, top, pins, numbers=False)
    plug(sh, x1, bottom, pins, numbers=False, flip=True)
    middle = (top + 58 + bottom) / 2
    for x, y in out.values():
        sh.add(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{middle - 9}" stroke="{BODY}" stroke-width="{WIRE}"/>')
        sh.add(f'<line x1="{x}" y1="{middle + 9}" x2="{x}" y2="{bottom}" stroke="{BODY}" stroke-width="{WIRE}"/>')
    sh.add(
        f'<line x1="{x1 - 60}" y1="{middle}" x2="{x1 + 5 * PITCH + 60}" y2="{middle}" stroke="{RED}" '
        f'stroke-width="3" stroke-dasharray="10 7"/>'
    )
    tx = x1 + 5 * PITCH + 76
    sh.text(tx, middle + 6, "cut here, in the middle", T, "bold", RED)
    sh.text(tx, top + 24, "a plug", T, "bold")
    sh.text(tx, top + 24 + LINE, "this half: one cable", T)
    sh.text(tx, bottom + 24, "a plug", T, "bold")
    sh.text(tx, bottom + 24 + LINE, "this half: the other cable", T)
    y = bottom + 58 + 36
    y = para(sh, 30, y, "The two halves are alike. Either one can be the P1 cable or the P2 cable.", W - 40, "bold")
    y = para(sh, 30, y + 4, "All six wires are black. " + SKETCHED, W - 40, fill=MUTED)
    sh.h = math.ceil(y - LINE + 14)
    sh.check("cut")
    return sh.svg()


def terminal_side(sh, x, y):
    """A crimped terminal seen from the side, the wire coming from the left at (x, y), the latch tab on top."""
    sh.add(f'<line x1="{x - 70}" y1="{y}" x2="{x}" y2="{y}" stroke="{BODY}" stroke-width="9"/>')
    sh.add(f'<line x1="{x}" y1="{y}" x2="{x + 16}" y2="{y}" stroke="#b87333" stroke-width="5"/>')
    sh.rect(x - 8, y - 9, 14, 18, fill=TERMINAL, stroke=INK, sw=1.5, rx=2)  # the crimp on the insulation
    sh.rect(x + 8, y - 7, 14, 14, fill=TERMINAL, stroke=INK, sw=1.5, rx=2)  # the crimp on the bare wire
    sh.rect(x + 22, y - 10, 64, 20, fill=TERMINAL, stroke=INK, sw=1.5, rx=2)  # the box
    sh.add(f'<path d="M{x + 40},{y - 10} l16,-8 l0,8 z" fill="{TERMINAL}" stroke="{INK}" stroke-width="1.5"/>')
    return x + 86


def crimp():
    """Strip and crimp."""
    sh = Sheet(W, 100)
    title(sh, "Crimp a terminal on each wire", SKETCHED)
    # 1: strip
    sh.text(30, 100, f"1. Strip about {wiring.LENGTHS['strip']} mm.", T, "bold")
    sh.add(f'<line x1="40" y1="150" x2="150" y2="150" stroke="{BODY}" stroke-width="9"/>')
    sh.add('<line x1="150" y1="150" x2="172" y2="150" stroke="#b87333" stroke-width="5"/>')
    sh.add(f'<path d="M150,166 v12 M172,166 v12 M150,172 h22" stroke="{INK}" stroke-width="1.5" fill="none"/>')
    sh.text(161, 198, f"{wiring.LENGTHS['strip']} mm", T, "regular", INK, "middle")
    # 2: crimp
    sh.text(270, 100, "2. Crimp the terminal on.", T, "bold")
    end = terminal_side(sh, 350, 162)
    sh.add(f'<path d="M{end - 38},{134} v10" stroke="{MUTED}" stroke-width="1.2"/>')
    sh.text(end - 38, 130, "latch tab", T, "regular", MUTED, "middle")
    sh.text(270, 210, "One crimp grips the bare wire,", T)
    sh.text(270, 210 + LINE, "the other the insulation.", T)
    sh.h = 262
    sh.check("crimp")
    return sh.svg()


def ground_check():
    """Before anything is cut: wire 1 is ground, so a meter from its end to the card's ground tells which end is 1."""
    pins = wiring.CONNECTORS["P1"]["pins"]
    sh = Sheet(W, 100)
    title(
        sh, "Check which wire is wire 1, before cutting anything", "the plug in its socket, the Acorn out of any slot"
    )
    crop = (0, 0, 330, 590)
    sockets, (px, py, pw, ph) = acorn_photo_down(sh, 30, 132, 470, T, crop=crop)
    k = pw / (crop[3] - crop[1])
    x0, y0, x1, y1 = ACORN_PAD  # in acorn-cw.jpg; a quarter turn clockwise takes (x, y) to (crop height - y, x)
    pad = (px + (crop[3] - y1) * k, py + (x0 - crop[0]) * k, px + (crop[3] - y0) * k, py + (x1 - crop[0]) * k)
    highlight(sh, pad)
    tx = px + pw + 16
    sh.text(tx, (pad[1] + pad[3]) / 2 - 16, "the plated half-round", T, "bold")
    sh.text(tx, (pad[1] + pad[3]) / 2 + 6, "mounting pad at the", T, "bold")
    sh.text(tx, (pad[1] + pad[3]) / 2 + 28, "end of the card", T, "bold")
    x1p = px + 56
    out, body = plug(sh, x1p, py + ph + 34, pins)
    half = (sockets["P1"][2] - sockets["P1"][0]) / 2
    middle = (body[0] + body[2]) / 2
    wedge(sh, sockets["P1"], (middle - half, body[1], middle + half, body[3]), down=True)
    end = body[3] + 70
    for sig, (x, y) in out.items():
        sh.add(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{end}" stroke="{BODY}" stroke-width="{WIRE}"/>')
        token(sh, x, end + 20, pins.index(sig) + 1)
    mx, my = 600, body[1] + 10  # the meter
    sh.rect(mx, my, 130, 150, fill="#f3c623", stroke=INK, sw=3, rx=12)
    sh.rect(mx + 14, my + 14, 102, 44, fill="#dfe8d8", stroke=INK, sw=1.5, rx=4)
    sh.text(mx + 65, my + 43, "beep", T, "bold", INK, "middle")
    sh.add(f'<circle cx="{mx + 65}" cy="{my + 102}" r="26" fill="{BODY}"/>')
    sh.add(f'<path d="M{mx + 65},{my + 102} l0,-22" stroke="#fff" stroke-width="4"/>')
    w1 = (out[pins[0]][0], end + 44)
    sh.add(
        f'<path d="M{mx},{my + 120} C{mx - 120},{my + 250} {w1[0] + 180},{w1[1] + 50} {w1[0]},{w1[1]}" fill="none" '
        f'stroke="{RED}" stroke-width="4"/>'
    )
    pc = ((pad[0] + pad[2]) / 2, (pad[1] + pad[3]) / 2)
    sh.add(
        f'<path d="M{mx + 100},{my} C{mx + 100},{my - 60} {pc[0] + 40},{pc[1] + 70} {pc[0]},{pc[1]}" fill="none" '
        f'stroke="{BODY}" stroke-width="4"/>'
    )
    sh.add(
        f'<circle cx="{w1[0]}" cy="{w1[1]}" r="5" fill="{RED}"/><circle cx="{pc[0]}" cy="{pc[1]}" r="5" fill="{BODY}"/>'
    )
    y = end + 122
    y = para(
        sh,
        30,
        y,
        "Press the probe tip, or a pin held to it, against the cut face of the wire flagged 1; the other probe "
        "on the mounting pad: the meter must beep. Wire flagged 6: it must stay silent.",
        W - 40,
        "bold",
    )
    y = para(
        sh,
        30,
        y + 4,
        "If wire 6 beeps instead, the numbering is reversed: take the flags off and number from the other end.",
        W - 40,
        "bold",
        RED,
    )
    y = para(
        sh,
        30,
        y + 4,
        "Shown in socket P1; the same in P2. The pad is taken to be ground from the M.2 standard: not measured "
        "on this card. The plug and the meter are sketched.",
        W - 40,
        fill=MUTED,
    )
    sh.h = math.ceil(y - LINE + 14)
    sh.check("ground check")
    return sh.svg()


def push():
    """Which way round a terminal goes into its cavity, and the pull that tests it."""
    sh = Sheet(W, 100)
    title(sh, "Push each terminal into its cavity", SKETCHED)
    sh.text(30, 100, "1. Push it in, latch tab towards the window, until it clicks.", T, "bold")
    hx, hy = 250, 150
    sh.rect(hx, hy, 150, 60, fill="#f1f3f5", stroke=INK, sw=3, rx=6)  # the housing, cut through one cavity
    sh.rect(hx + 46, hy - 4, 18, 8, fill=INK, rx=2)  # its window: the mark the cavity pictures use
    end = terminal_side(sh, hx - 30, hy + 30)
    sh.add(f'<path d="M{hx - 150},{hy + 62} h60" stroke="{INK}" stroke-width="2.5"/>')
    sh.add(f'<path d="M{hx - 94},{hy + 56} l10,6 l-10,6 z" fill="{INK}"/>')
    sh.text(hx + 55, hy - 14, "window", T, "regular", MUTED, "middle")
    sh.text(end - 80, hy + 84, "latch tab, under the window", T, "regular", MUTED)
    sh.text(hx + 170, hy + 22, "housing, cut through", T, "regular", MUTED)
    sh.text(hx + 170, hy + 22 + LINE, "one cavity", T, "regular", MUTED)
    y = para(sh, 30, hy + 128, "2. Pull the wire gently. The terminal must stay in.", W - 40, "bold")
    sh.rect(34, y - 11, 18, 8, fill=INK, rx=2)
    y = para(sh, 64, y, "the window, as marked on the housing in the cavity picture", W - 74)
    sh.h = math.ceil(y - LINE + 14)
    sh.check("push")
    return sh.svg()


def check_picture():
    """Buzzing a wire through: one probe on a plug contact, the other on the terminal in its cavity."""
    pins = wiring.CONNECTORS["P1"]["pins"]
    sh = Sheet(W, 100)
    title(sh, "Check every wire with a meter", SKETCHED)
    mx, my = 40, 96
    sh.rect(mx, my, 130, 170, fill="#f3c623", stroke=INK, sw=3, rx=12)  # the meter
    sh.rect(mx + 14, my + 14, 102, 44, fill="#dfe8d8", stroke=INK, sw=1.5, rx=4)
    sh.text(mx + 65, my + 43, "beep", T, "bold", INK, "middle")
    sh.add(f'<circle cx="{mx + 65}" cy="{my + 110}" r="30" fill="{BODY}"/>')
    sh.add(f'<path d="M{mx + 65},{my + 110} l0,-26" stroke="#fff" stroke-width="4"/>')
    out, body = plug(sh, 330, 96, pins)
    cx, cy = 400, 250  # a cavity
    sh.rect(cx - 59, cy - 22, 118, 44, fill="#fff", stroke=INK, sw=3, rx=6)
    token(sh, cx + 35, cy, 1)
    px = out[pins[0]][0] - 12  # contact 1, reached from the meter's side
    sh.add(
        f'<path d="M{mx + 130},{my + 50} C{mx + 180},{my + 50} {px - 60},{my + 24} {px},{my + 24}" fill="none" '
        f'stroke="{RED}" stroke-width="4"/>'
    )
    sh.add(
        f'<path d="M{mx + 130},{my + 130} C{mx + 210},{my + 130} {cx - 140},{cy} {cx - 20},{cy}" fill="none" '
        f'stroke="{BODY}" stroke-width="4"/>'
    )
    sh.add(
        f'<circle cx="{px}" cy="{my + 24}" r="5" fill="{RED}"/><circle cx="{cx - 20}" cy="{cy}" r="5" fill="{BODY}"/>'
    )
    sh.text(body[0], body[3] + 26, "one probe on the metal contact of the plug", T)
    sh.text(cx - 59, cy + 46, "the other probe on the metal terminal,", T)
    sh.text(cx - 59, cy + 46 + LINE, "through the opening on the pin side of the housing", T)
    y = cy + 108
    y = para(sh, 30, y, "Set the meter to continuity. For each wire, touch its contact on the plug and "
             "its terminal in the housing: the meter must beep.", W - 40, "bold")  # fmt: skip
    y = para(sh, 30, y + 4, "Then try every other cavity: silent.", W - 40, "bold")
    sh.h = math.ceil(y - LINE + 14)
    sh.check("check")
    return sh.svg()


SHARED = {
    "acorn-cable-cut.svg": cut,
    "acorn-cable-ground-check.svg": ground_check,
    "acorn-cable-crimp.svg": crimp,
    "acorn-cable-push.svg": push,
    "acorn-cable-check.svg": check_picture,
}


def prepare_name(c, connector):
    return f"acorn-cable-{c.key}-{connector.lower()}-prepare.svg"


def resistor_name(c, connector):
    return f"acorn-cable-{c.key}-{connector.lower()}-resistor.svg"


def has_resistor(c, connector):
    return any(s in c.resistors for s in wiring.CONNECTORS[connector]["pins"])


# ----------------------------------------------------------------------------------------------
# The procedure, as Markdown
# ----------------------------------------------------------------------------------------------
SHEETS = {"pi5": "acorn-wiring-pi5", "blade": "acorn-wiring-computeblade"}


def procedure(c):
    """Building both cables for one carrier, complete in itself: every step has its picture under it."""
    lengths = wiring.LENGTHS
    sheet = (f"The finished wiring: Acorn to {c.name}", f"{SHEETS[c.key]}.png")
    used = [s for conn in wiring.CONNECTORS.values() for s in conn["pins"] if s in c.wires]
    labels = list(dict.fromkeys(label_of(s) for s in used))
    balls = [label_of(s) for s in used if "ball" in wiring.SIGNALS[s]]

    spares = sum(
        1 for s in wiring.CONNECTORS["P2"]["pins"] if s in c.wires and wiring.SIGNALS[s]["what"] == "spare GPIO"
    )
    count = {1: "one", 2: "two", 3: "three"}.get(spares, str(spares))
    spare = f" and {count} spare GPIO{'s' if spares > 1 else ''}" if spares else ""

    def listed(words):
        return ", ".join(words[:-1]) + f" and {words[-1]}" if len(words) > 1 else words[0]

    out = [
        tables.BANNER.strip(),
        "",
        "Not yet run by us on this hardware: written from the design.",
        "",
        "### What you will have",
        "",
        f"Two short cables from the Acorn's two connectors to the {c.name}: the P1 cable carries JTAG, the P2 "
        f"cable carries the serial port{spare}.",
        "",
        f"{listed(labels)} are the names on the pictures for each wire; {listed(balls)} are the FPGA's pin names.",
        "",
        f"![{sheet[0]}]({sheet[1]})",
        "",
        "### Parts and tools",
        "",
        tables.bom(c).strip(),
        "",
        "### Steps",
        "",
    ]
    n = 0

    def step(text, *images):
        nonlocal n
        n += 1
        out.extend([f"**{n}.** {text}", ""])
        for alt, name in images:
            out.extend([f"![{alt}]({name})", ""])

    step(
        "Cut the Molex cable in half with side cutters. Each half is one cable.",
        ("The cable, cut in the middle", "acorn-cable-cut.png"),
    )
    cavity = {}
    for connector, conn in wiring.CONNECTORS.items():
        plan = housing(c, connector)
        data = c.headers[plan.header]
        pins = conn["pins"]
        shape = f"{data.columns}×{(plan.last - plan.first + 1) // data.columns}"
        cavity[connector] = (f"Which wire goes in which cavity, {connector} cable", png(file_name(c, connector)))
        prep = (f"The {connector} cable: finding wire 1, and its wires prepared", png(prepare_name(c, connector)))
        kept = [pins.index(s) + 1 for s in pins if s not in plan.cut]
        cut_n = [pins.index(s) + 1 for s in plan.cut]
        cut_who = number_list(cut_n)
        out.extend([f"#### The {connector} cable ({conn['what']})", ""])
        half = "one" if connector == next(iter(wiring.CONNECTORS)) else "the other"
        step(
            f"Press the plug of {half} half into socket {connector} on the underside of the Acorn. Hold the card "
            "underside up with the M.2 edge to your left: wire 1 is the leftmost. Put a numbered tape flag on each "
            f"of the {len(pins)} wires, 1 to {len(pins)}, about {lengths['flag_back']} mm back from the tip, clear "
            "of the end that will be cut and stripped later. "
            "While the plug sits in the socket (the Acorn out of any slot, unpowered), set the meter to continuity. "
            "Press the probe tip, or a pin held to it, against the cut face of the wire flagged 1 (it is not "
            "stripped yet), and put the other probe on the plated half-round mounting pad "
            f"at the end of the card: it must beep. Then the wire flagged {len(pins)}: it must stay silent. "
            f"If wire {len(pins)} beeps instead, stop: the numbering is reversed; take the flags off and number from "
            "the other end. Then take the plug out again.",
            prep,
            ("Checking which wire is wire 1, with a meter", "acorn-cable-ground-check.png"),
        )
        one = len(cut_n) == 1
        step(
            f"Cut {cut_who} off about {lengths['cut_back']} mm from the plug and shrink a piece of the "
            f"{lengths['tube']} mm tube over "
            f"{'the cut end' if one else 'each cut end'}. {'It goes' if one else 'They go'} in no cavity. "
            f"Wire {len(pins)} is VCC, 3.3 V from the Acorn: it must never reach the host. "
            f"Leave {number_list(kept)} at full length.",
            prep,
        )
        for sig in (s for s in pins if s in c.resistors and s not in plan.cut):
            step(
                f"Cut wire {pins.index(sig) + 1} ({label_of(sig)}) about {lengths['resistor']} mm from its free end. "
                f"Slide a piece of the {lengths['resistor_tube']} mm tube onto the wire, clear of the cut. "
                f"Strip about {lengths['strip']} mm from each cut end. "
                f"Trim the resistor's leads to about {lengths['resistor_lead']} mm each. "
                f"Solder the {c.resistor_value} resistor between the two cut ends. "
                "Slide the tube over the resistor and both joints and shrink it. Crimp the terminal only after this.",
                (f"The resistor fitted into wire {pins.index(sig) + 1}", png(resistor_name(c, connector))),
            )
        step(
            f"Strip about {lengths['strip']} mm from {number_list(kept)}. Crimp a Dupont terminal on each.",
            ("Stripping and crimping", "acorn-cable-crimp.png"),
        )
        warning = turned_warning(c, plan)
        if any(label_of(s) != "GND" for sigs in turned_rails(c, plan).values() for s in sigs):
            warning = warning[:-1] + ", which can destroy the host."
        step(
            f"Hold the empty {shape} housing with the wire openings facing you and its long side upright, as in "
            "the picture. Until it is marked, either way up is the same. "
            f"Mark {'the top left corner' if data.columns > 1 else 'the top end'} with a paint pen or a dot of tape: "
            f"that is the pin {plan.first} corner. "
            "For each wire, read the number on its flag, find the same number in the picture, and push its terminal "
            f"into that cavity, latch tab towards the window, until it clicks. {warning} "
            f"{cut_who[0].upper()}{cut_who[1:]} {'goes' if one else 'go'} in no cavity. "
            "Pull each wire gently: the terminal must stay in.",
            cavity[connector],
            ("Which way round a terminal goes in, and the pull test", "acorn-cable-push.png"),
        )
        step(
            "Check each wire with a meter on continuity. For each wire: one probe on its contact on the plug, the "
            "other on the terminal in the cavity the picture gives for that wire number, through the opening on the "
            "pin side of the housing: it must beep. Every other cavity must stay silent for that contact. "
            "The plug's contacts are 1.2 mm apart: use a fine probe or a sewing pin held to the probe.",
            ("A meter between the plug and the housing", "acorn-cable-check.png"),
            cavity[connector],
        )
    out.extend(["#### Fit the cables", ""])
    fits, last = [], []
    for connector in wiring.CONNECTORS:
        plan = housing(c, connector)
        data = c.headers[plan.header]
        whole = (plan.first, plan.last) == (1, data.count)
        on = data.name if whole else f"{data.name} pins {plan.first} to {plan.last}"
        pin = (
            f"the pin printed {plan.first} beside the header"
            if data.printed
            else f"pin {plan.first}, counted as in the picture"
        )
        fits.append(f"the {connector} housing on the {on} with its marked corner on {pin}")
        last.append(f"the {connector} housing on the {on}, marked corner on pin {plan.first}")
    first = next(iter(wiring.CONNECTORS.values()))["pins"][0]
    step(
        "This is a bench check; the housings come off again in the next step. "
        f"Fit {fits[0]}, and {fits[1]}. The Acorn is not in its slot and the plugs are free. With the host unplugged "
        "from power, "
        "put one meter probe "
        f"on contact 1 ({label_of(first)}) of a plug and the other on {c.shell}: it must "
        f"beep. Do the same for the other plug. Then contact {len(pins)} of each plug ({label_of(pins[-1])}, the wire "
        "you cut back): against the shell and against every other contact it must be silent.",
        *cavity.values(),
    )
    actions = [
        "Take both housings off again.",
        c.power_off,
        "Press the P1 plug into socket P1 and the P2 plug into socket P2 on the underside of the Acorn, each the way "
        "round it was when you put the flags on, until fully seated.",
        "Put the Acorn in the M.2 slot and fit its screw.",
        f"Fit {last[0]}, and {last[1]}.",
    ]
    step(
        "Fit the cables, in this order. The sockets are on the underside of the card and may not be reachable once "
        "it is in the slot.\n\n" + "\n".join(f"{i}. {action}" for i, action in enumerate(actions, 1)),
        ("Where sockets P1 and P2 are, and which end is wire 1", "acorn-cable-ground-check.png"),
        sheet,
    )
    out.extend([CREDITS[c.key] + ".", ""])
    return "\n".join(out)


def png(name):
    return name.replace(".svg", ".png")


def build_names():
    """The file names of every picture build() draws."""
    names = []
    for key, connector in CABLES:
        c = wiring.CARRIERS[key]
        names += [file_name(c, connector), prepare_name(c, connector)]
        if has_resistor(c, connector):
            names.append(resistor_name(c, connector))
    return [*names, *SHARED]


def build():
    """{file name: contents} for every step picture and procedure."""
    out = {}
    for key, connector in CABLES:
        c = wiring.CARRIERS[key]
        svg, (cross, _shared, tight) = cable(c, connector)
        out[file_name(c, connector)] = svg
        print(f"{file_name(c, connector)}: {len(svg) // 1024} KiB, {cross} crossings, {tight} tight spots")
        out[prepare_name(c, connector)] = prepare(c, connector)
        if has_resistor(c, connector):
            out[resistor_name(c, connector)] = resistor_picture(c, connector)
    for name, draw in SHARED.items():
        out[name] = draw()
    for key, c in wiring.CARRIERS.items():
        out[f"acorn-cables-{key}.md"] = procedure(c)
    return out
