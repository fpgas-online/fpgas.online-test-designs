# SPDX-License-Identifier: Apache-2.0
"""The cable picture: which Pmod header of the demo board goes to which port of the Pmod HAT.

One drawing, from wiring.toml, written several times: whole (`tt-fpga-pmod-cables.svg`), and with only the
headers a table is about picked out, the rest drawn faint, so that a table can show the reader where its
header is without sending them to another page. PICTURES lists them.

It is a diagram, not a drawing of the boards: the headers are in the order Tiny Tapeout's documents give,
the ports in the order of their names, and every connector is drawn the way the Pmod standard numbers its
pins (1 to 6 in one row, 7 to 12 in the other). Where pin 1 is on a real board is not recorded in this
repository. The gold square is therefore pin NUMBER 1, drawn where the numbering puts it and not where a
board has it, and the picture says so in words (PIN_1), as does every page under the picture: a reader
must not take the square's corner for a place on the board. When a board has been looked at, record where
pin 1 is in wiring.toml, draw it, and take the warning off.

Drawn on the canvas the Acorn sheets use (docs/wiring/wiringlib/canvas.py): text as glyph outlines, its own
paper background, and a build that fails if any text leaves the canvas, overlaps other text or sits on a
cable. The smallest text is SMALLEST px on a canvas W px wide: 2.6 mm high when the picture is printed
180 mm wide, the text width of an A4 page.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # docs/wiring, for wiringlib

import wiring
from wiringlib.canvas import FAINT, GOLD, INK, MUTED, RED, Sheet

W, H = 1040, 830
# Said on the picture and, by tables.py, under it on every page, until where pin 1 is has been read off a
# board. That a cable turned round puts the power pins on signal pins follows from the numbering:
# turned_round() works it out from wiring.toml and draw() refuses to say it if it is not so.
PIN_1 = (
    "The gold square is pin NUMBER 1 of the Pmod numbering. It is not a place on the board.",
    "Find pin 1 on each connector by its marking before plugging a cable in.",
    "A 2x6 cable turned round puts {power} on signal pins.",
)
SMALLEST = 15  # px: no text on the picture is smaller
CELL = 34  # a pin of a connector
BOARD_FILL = "#eef0f3"
GROUND_FILL, POWER_FILL, SHARED_RING = "#aab1ba", "#f6c9c9", "#1d6fb8"
OFF = "#8a929c"  # a cable that this picture is not about

# {file name without its suffix: (the header keys it picks out, or None for all; the end of its title)}
PICTURES = {
    "tt-fpga-pmod-cables": (None, "which header goes to which port"),
    "tt-fpga-pmod-cables-ui-uo": (("input", "output"), "the Input and Output headers"),
    "tt-fpga-pmod-cables-uo": (("output",), "the Output header"),
}
DRIVES = {"pi": "the Pi drives", "fpga": "the FPGA drives", "both": "either end drives"}


def listed(items):
    """['a', 'b', 'c'] -> 'a, b, c'."""
    return ", ".join(str(i) for i in items)


def shared_note(w):
    """One line for each pair of ports with pins on the same GPIOs: 'JA pins 2, 3, 4 and JB pins 2, 3, 4 are ...'."""
    notes = []
    ports = list(w.hat)
    for i, a in enumerate(ports):
        for b in ports[i + 1 :]:
            both = [g for g in w.hat[a]["gpios"] if g in w.hat[b]["gpios"]]
            if not both:
                continue
            pins_a = [w.pmod["signal_pins"][w.hat[a]["gpios"].index(g)] for g in both]
            pins_b = [w.pmod["signal_pins"][w.hat[b]["gpios"].index(g)] for g in both]
            notes.append(
                f"{a} pins {listed(pins_a)} and {b} pins {listed(pins_b)} are the same "
                f"Raspberry Pi GPIOs: {listed(both)}."
            )
    return notes


def turned_round(w):
    """The pins the power pins land on when a 2x6 plug is turned half a turn: pin n goes to pin 13 - n."""
    return sorted(13 - pin for pin in w.pmod["power_pins"])


def pin_1_warning(w):
    """PIN_1 as the three sentences to print, or SystemExit if the wiring no longer makes the last one true."""
    if not set(turned_round(w)) <= set(w.pmod["signal_pins"]):
        raise SystemExit("picture.py: PIN_1 says a cable turned round puts power on signal pins; it no longer does")
    return [line.format(power=w.pmod["power"]) for line in PIN_1]


def connector(sh, w, cx, top, lit, ringed=()):
    """A 12-pin Pmod connector, pins 1 to 6 over pins 7 to 12, centred on cx. `ringed`: pins to ring."""
    x0 = cx - 3 * CELL
    for pin in range(1, 13):
        col, row = (pin - 1) % 6, (pin - 1) // 6
        x, y = x0 + col * CELL, top + row * CELL
        fill, stroke, sw = "#ffffff", INK if lit else FAINT, 1.5
        if pin == 1:
            fill, sw = GOLD, 2.5
        elif pin in w.pmod["ground_pins"]:
            fill = GROUND_FILL
        elif pin in w.pmod["power_pins"]:
            fill, stroke = POWER_FILL, RED
        sh.rect(x + 2, y + 2, CELL - 4, CELL - 4, fill=fill, stroke=stroke, sw=sw)
        if pin in ringed:
            sh.rect(x + 5, y + 5, CELL - 10, CELL - 10, stroke=SHARED_RING, sw=3)
        sh.text(x + CELL / 2, y + CELL / 2 + 5, str(pin), SMALLEST, "bold", INK if lit else MUTED, "middle",
                box=(x, y, x + CELL, y + CELL))  # fmt: skip
    return x0, top, x0 + 6 * CELL, top + 2 * CELL


def swatch(sh, x, y, text, fill="#ffffff", stroke=INK, sw=1.5, ring=False):
    """A pad of the key with what it means; returns where the next one starts."""
    sh.rect(x, y - 16, 22, 22, fill=fill, stroke=stroke, sw=sw)
    if ring:
        sh.rect(x + 3, y - 13, 16, 16, stroke=SHARED_RING, sw=3)
    return x + 30 + sh.text(x + 30, y, text, SMALLEST) + 26


def draw(w, name):
    """The picture `name` of PICTURES, as SVG text."""
    show, title_end = PICTURES[name]
    sh = Sheet(W, H)
    left, right, lane = 30, 900, 965  # the boards' edges, and where the USB-C cable runs
    board_top, board_bottom, hat_top, hat_bottom = 86, 300, 470, 690
    centres = [170, 465, 760]
    if len(w.headers) != len(centres) or len(w.hat) != len(centres):
        raise SystemExit("picture.py is laid out for three headers and three ports")

    sh.text(left, 40, f"Tiny Tapeout FPGA demo board to Pmod HAT: {title_end}", 22, "bold")
    sh.text(left, 66, "Three 12-pin Pmod cables, each pin 1 to pin 1, and one USB-C cable. A diagram, not to scale.",
            SMALLEST, fill=MUTED)  # fmt: skip

    sh.rect(left, board_top, right - left, board_bottom - board_top, fill=BOARD_FILL, stroke=INK, sw=2, rx=10)
    sh.text(left + 16, board_top + 28, "Tiny Tapeout demo board", 17, "bold")
    sh.text(left + 16, board_top + 50, "with the FPGA breakout in its chip socket", SMALLEST)
    sh.rect(left, hat_top, right - left, hat_bottom - hat_top, fill=BOARD_FILL, stroke=INK, sw=2, rx=10)
    sh.text(left + 16, hat_bottom - 16, f"{w.board['hat']}, on the Raspberry Pi's 40-pin header", 17, "bold")

    # the USB-C cable, from the demo board to the Pi
    usb_y, pi_y = board_top + 26, hat_bottom - 22
    sh.tag(right - 14, usb_y, "USB-C", INK, SMALLEST, 26, "end")
    sh.tag(right - 14, pi_y, "a USB port of the Pi", INK, SMALLEST, 26, "end")
    for x0, y0, x1, y1 in ((right, usb_y, lane, usb_y), (lane, usb_y, lane, pi_y), (lane, pi_y, right, pi_y)):
        sh.add(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{INK}" stroke-width="5" '
               'stroke-linecap="round"/>')  # fmt: skip
        sh.wire_segments.append((x0, y0, x1, y1))
    sh.tag(lane, (board_bottom + hat_top) / 2, "USB-C cable", INK, SMALLEST, 26, "middle", on_wire=True)

    shared_gpios = {x.gpio for x in w.shared()}
    for cx, (key, header) in zip(centres, w.headers.items(), strict=True):
        group = next(g for g, v in w.groups.items() if v["header"] == key)
        port = w.cables[key]
        lit = show is None or key in show
        colour = w.groups[group]["colour"] if lit else OFF
        ink = INK if lit else MUTED

        sh.text(cx, board_top + 100, header["name"], 17, "bold", ink, "middle")
        sh.text(cx, board_top + 121, f"{group}[0] to {group}[7]", SMALLEST, "mono", ink, "middle")
        _, _, _, top_end = connector(sh, w, cx, board_top + 132, lit)
        ringed = [p for p, g in zip(w.pmod["signal_pins"], w.hat[port]["gpios"], strict=True) if g in shared_gpios]
        x0, port_top, x1, port_end = connector(sh, w, cx, hat_top + 16, lit, ringed)
        sh.text(cx, port_end + 30, port, 22, "bold", ink, "middle")

        # the cable: a band from the header to the port, and a gold line from pin 1 to pin 1
        sh.rect(x0, top_end, x1 - x0, port_top - top_end, fill=colour, stroke=colour, sw=2, extra='fill-opacity="0.16"')
        pin1 = x0 + CELL / 2
        sh.add(f'<line x1="{pin1}" y1="{top_end}" x2="{pin1}" y2="{port_top}" stroke="{GOLD if lit else FAINT}" '
               'stroke-width="6"/>')  # fmt: skip
        sh.wire_segments.append((pin1, top_end, pin1, port_top))
        middle = (top_end + port_top) / 2
        if lit:
            sh.tag(pin1, middle - 52, "pin 1 to pin 1", GOLD, SMALLEST, 26, "middle", on_wire=True, fg=INK)
        sh.tag(cx + 12, middle, f"{header['name']} to {port}", colour, 16, 28, "middle")
        sh.text(cx + 12, middle + 40, DRIVES[w.groups[group]["drive"]], SMALLEST, fill=ink, anchor="middle")

    for i, note in enumerate(shared_note(w)):
        sh.text(left + 16, hat_top + 148 + 20 * i, note, SMALLEST)

    # the warning about pin 1, in words on the picture itself
    first, *rest = pin_1_warning(w)
    box = (left, H - 122, W - left, H - 60)
    sh.rect(box[0], box[1], box[2] - box[0], box[3] - box[1], fill="#fff4d6", stroke=GOLD, sw=2, rx=8)
    sh.text(left + 16, H - 96, first, 16, "bold", box=box)
    sh.text(left + 16, H - 73, " ".join(rest), 16, box=box)

    # the key
    x, y = left, H - 22
    x = swatch(sh, x, y, "pin 1", GOLD, INK, 2.5)
    x = swatch(sh, x, y, f"signal: pins {listed(w.pmod['signal_pins'])}")
    x = swatch(sh, x, y, f"ground: pins {listed(w.pmod['ground_pins'])}", GROUND_FILL)
    x = swatch(sh, x, y, f"{w.pmod['power']}: pins {listed(w.pmod['power_pins'])}", POWER_FILL, RED)
    if shared_gpios:
        swatch(sh, x, y, "one GPIO, two ports", ring=True)

    sh.check(name)
    small = [s for bbox, s, _ in sh.texts if bbox[3] - bbox[1] < SMALLEST - 0.01]
    if small:
        raise SystemExit(f"{name}: text smaller than {SMALLEST} px: {small}")
    return sh.svg()


def build(w=wiring.WIRING):
    return {f"{name}.svg": draw(w, name) for name in PICTURES}
