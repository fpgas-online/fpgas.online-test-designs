# SPDX-License-Identifier: Apache-2.0
"""A picture for each step of building the two cables, from wiring.toml, drawn with the sheets' own pieces.

cable(): "which wire goes in which cavity" for one cable of one carrier. The half cable as an object: its
Pico-EZmate plug (and where pin 1 is, on the card), its six wires, and its Dupont housing, large, seen as
the reader holds it while pushing the terminals in.

gen.py's build() calls build() here, so these pictures are part of generated/ and of `gen.py --check`.
"""

from dataclasses import dataclass

import wiring
from gen import (
    CREDITS,
    HOST_PHOTOS,
    Header,
    acorn_photo,
    draw_header,
    draw_inside,
    draw_wires,
    housing_note,
    is_5v,
    legend,
    make_wires,
    pin_label,
    plug_box,
    route,
    terminate,
    wedge,
    wire_ends,
)
from sheetlib import INK, MUTED, PAPER, RED, Sheet

# Narrower than a sheet (1600 x 900), so the same text is larger where a page shows the picture at its text width.
SIZE = (950, 900)

# (carrier, connector) of every cable picture drawn, and how far its housing is nudged down so that no plug
# row and housing row share a track (as NUDGE in gen.py).
CABLES = {("blade", "P1"): 8}


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


def file_name(c, connector):
    return f"acorn-cable-{c.key}-{connector.lower()}.svg"


def cable(c, connector, nudge=0):
    """The picture for one cable. Returns (svg, routing score)."""
    conn = wiring.CONNECTORS[connector]
    pins = conn["pins"]
    plan = housing(c, connector)
    data = c.headers[plan.header]
    numbers = data.grid(plan.first, plan.last)
    w, h = SIZE
    sh = Sheet(w, h)

    sh.text(30, 44, f"{connector} cable ({conn['what']}) for a {c.name}: which wire in which cavity", 22, "bold")
    sh.text(
        30,
        65,
        f"All {len(pins)} wires of the cable are black: a wire's number is its position in the plug, counted from "
        "pin 1.",
        12.5,
        "regular",
        MUTED,
    )
    sh.add(f'<line x1="30" y1="78" x2="{w - 26}" y2="78" stroke="{INK}" stroke-width="1.5"/>')

    # Left, top: the host, and a close-up of the header the housing goes on, in the housing's orientation.
    hl, (_ix, iy, _iw, ih) = HOST_PHOTOS[c.key](sh, 30, 114, 400, (120, 198, 220), only={plan.header})
    port_hl = hl[plan.header]
    sh.tag(
        (port_hl[0] + port_hl[2]) / 2,
        iy + ih + 14,
        data.name,
        "#fff",
        size=10.5,
        h=17,
        anchor="middle",
        fg=INK,
        stroke=INK,
        pad=6,
    )

    # Left, below it: the housing, straight under the header in the close-up.
    pitch, pad = 64, 32
    centre = (port_hl[0] + port_hl[2]) / 2
    hdr = Header(sh, round(centre - data.columns * pitch / 2), iy + ih + 46 + nudge, numbers, pitch, pad, "right")
    wedge(sh, port_hl, hdr.body, down=True)
    draw_header(hdr, c, plan.header, set(plan.cavities), empty="empty: ")
    shape = f"{data.columns}×{len(numbers)}"
    y = hdr.body[3] + 26
    sh.text(30, y, f"{shape} Dupont housing, seen from the wire side,", 12.5, "bold")
    sh.text(30, y + 17, f"as it will sit on the {data.name} with the {c.name} seen from above.", 12.5, "bold")
    sh.text(30, y + 36, f"Numbers in the cavities: as printed beside the {data.name}.", 12, "regular", MUTED)
    if hdr.where[plan.first] != (0, 0):
        raise wiring.WiringError(f"{c.key}: pin {plan.first} is not the top left cavity of its housing")
    kx, ky = hdr.body[0] - 7, hdr.y + 7  # the corner of the housing outline (Header.draw_body)
    sh.add(
        f'<polygon points="{kx},{ky} {kx + 22},{ky} {kx},{ky + 22}" fill="{RED}" stroke="{PAPER}" stroke-width="1.5"/>'
    )
    sh.text(kx - 8, ky + 8, "mark this corner", 11.5, "bold", RED, "end")

    # Right: the card with the socket and its pin 1, and under it the plug in the same orientation.
    lanes = [hdr.body[2] + 210 + 18 * i for i in range(6)]
    plug_x = lanes[-1] + 72
    rows = (60, 590)  # of acorn-cw.jpg: the two sockets and a little of the card each side
    sockets = dict(zip(("P1", "P2"), acorn_photo(sh, plug_x, 114, 240, "cw", rows=rows), strict=True))
    attach, box, cut = plug_box(
        sh,
        plug_x,
        max(r[3] for r in sockets.values()) + 72,  # clear of the words under the photo
        300,
        connector,
        conn["what"],
        pins,
        "left",
        False,
        housing_note(c, connector),
        unused=c.unused(connector),
        sleeve=True,
    )
    wedge(sh, sockets[connector], box, down=True)
    for sig, (x, y) in cut.items():
        vcc = sig == "VCC"
        sh.text(
            x - 9,
            y - 2,
            f"wire {pins.index(sig) + 1}: cut back, heat shrink over the end",
            11.5,
            "bold",
            RED if vcc else MUTED,
            "end",
        )
        what = wiring.SIGNALS[sig]["what"]
        why = f"{what}: it must never reach the host" if vcc else f"{what}: not used on this host"
        sh.text(x - 9, y + 12, why, 11.5, "regular", RED if vcc else MUTED, "end")

    mapping = {s: pin for pin, s in plan.cavities.items() if s}
    wires = make_wires(attach, mapping, c)
    inside = terminate(sh, hdr, wires)
    paths, (cross, shared, tight) = route(wires, lanes)
    assert shared == 0, f"{c.key} {connector}: {shared} shared tracks"
    draw_wires(sh, wires, paths)
    draw_inside(sh, inside)
    wire_ends(
        sh,
        hdr,
        wires,
        {s: f"pin {pin} {pin_label(data.pins[pin]['name'])}" for s, pin in mapping.items()},
        "right",
        lead={s: f"wire {pins.index(s) + 1}" for s in mapping},
    )

    resistor = c.resistor_value if c.resistors & set(mapping) else ""
    legend(sh, plug_x, box[3] + 34, resistor)
    y = box[3] + 34 + (190 if resistor else 150)
    sh.text(plug_x, y, f"Mark the pin {plan.first} corner of the housing before filling it.", 12.5, "bold", RED)
    # turned end for end, the wire of pin n sits on pin first + last - n
    turned = {plan.first + plan.last - pin: s for s, pin in mapping.items()}
    if any(is_5v(data.pins[pin]["name"]) and wiring.SIGNALS[s]["label"] != "GND" for pin, s in turned.items()):
        sh.text(plug_x, y + 17, "Turned round, it puts 5 V on a signal wire.", 12, "regular", RED)
    sh.text(w - 26, h - 14, CREDITS[c.key], 10, "regular", MUTED, "end")
    sh.check(file_name(c, connector))
    return sh.svg(), cross + 3 * tight


def build():
    """{file name: svg} for every cable picture."""
    out = {}
    for (key, connector), nudge in CABLES.items():
        c = wiring.CARRIERS[key]
        svg, score = cable(c, connector, nudge)
        out[file_name(c, connector)] = svg
        print(f"{file_name(c, connector)}: {len(svg) // 1024} KiB, routing score {score}, housing nudged {nudge} px")
    return out
