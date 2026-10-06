# SPDX-License-Identifier: Apache-2.0
"""The Tiny Tapeout FPGA pin tables, as Markdown, from wiring.toml. gen.py writes them into generated/.

tt-fpga-cables.md         which demo board header goes to which Pmod HAT port, with the picture
tt-fpga-pins-ui-uo.md     ui_in and uo_out, wire by wire
tt-fpga-pins-uio-uart.md  uio, wire by wire, and the serial port
tt-fpga-pins-other.md     the pins that load the FPGA, the seven-segment display, the clock, the reset, the LED
tt-fpga-sources.md        where each statement of fact comes from, or that nobody has checked it

Each file is complete in itself, for a reader at a bench with paper only: it starts with the generator's
banner, says who it is for, and repeats the picture and the sentences needed to find the header it is
about, rather than pointing at another page. Its headings start at level 3, so a page includes it under
one of its own sections. No table is wider than six columns of short values. A page built from one file
stays well inside five printed A4 sheets (test_tables.py holds each to a size).

Every wire's row comes from wiring.WIRING, so no number is written twice.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # docs/wiring, for wiringlib

import picture
import wiring
from wiringlib.fragments import banner, table

BANNER = banner("tt-fpga")
W = wiring.WIRING

LEAD = (
    "For the person at the bench with a Tiny Tapeout demo board that has the FPGA breakout in its chip "
    f"socket, joined to a {W.board['host']}."
)
# The standing rule, printed wherever a page mentions loading the FPGA: first the rule, as a rule, then
# the fact this repository can stand behind (tests/test_tt_host_scripts.py holds what its scripts send).
STREAMING = (
    "**The rule here: an FPGA on a demo board is loaded by streaming only**, and no code of ours may write, "
    "replace or delete a file on a demo board. The loader and the tests in this repository do not: the demo "
    "board's microcontroller reads the bitstream from the Raspberry Pi over the USB-C cable and passes it "
    "straight to the FPGA."
)


NUMBER = {1: "one", 2: "two", 3: "three", 4: "four"}
SOURCES_PAGE = "tt-fpga-sources.md"


def code(s):
    return f"`{s}`"


def spoken(items):
    """['a', 'b', 'c'] -> 'a, b and c'."""
    items = [str(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def header_name(key):
    return W.headers[key]["name"]


def group_on(key):
    return next(g for g, v in W.groups.items() if v["header"] == key)


def image(name, alt):
    """A picture of picture.PICTURES, as the PNG with a link to the SVG; both are beside this file."""
    if name not in picture.PICTURES:
        raise KeyError(f"{name} is not a picture that picture.py draws")
    warning = " ".join(picture.pin_1_warning(W))
    return f"[![{alt}]({name}.png)]({name}.svg)\n\n**Pin 1 on the picture.** {warning}\n"


def finding(keys=None):
    """The sentences a reader needs to find the headers `keys` (all of them by default) and their ports."""
    keys = list(W.headers) if keys is None else keys
    row = ", ".join(f"{h['name']} ({code(group_on(k))}) {h['place']}" for k, h in W.headers.items())
    joins = spoken(f"{header_name(k)} to {W.cables[k]}" for k in keys)
    which = "each header to its port" if len(keys) > 1 else "the header to its port"
    return (
        f"**Finding the headers.** The demo board has {NUMBER[len(W.headers)]} 12-pin Pmod headers side by side along "
        f"its bottom edge. Seen from above, they are: {row}. The {W.board['hat']} has {NUMBER[len(W.hat)]} ports: "
        f"{spoken(W.hat)}. A 12-pin Pmod cable joins {which}, pin 1 to pin 1: {joins}. A USB-C cable joins the "
        "demo board to a USB port of the Raspberry Pi.\n\n"
        "**Not checked by us against a board:** the order of the headers (it is from Tiny Tapeout's "
        "documents), what is printed beside each header and each port, and where pin 1 is on each connector. "
        f"{spoken(h['name'] for h in W.headers.values())} are this page's names for the headers; "
        f"{spoken(W.hat)} are Digilent's names for the ports. On a Pmod connector pins 1 to 6 are one row and "
        f"pins 7 to 12 the other; pins {spoken(W.pmod['ground_pins'])} are ground and pins "
        f"{spoken(W.pmod['power_pins'])} are {W.pmod['power']}. Each board puts its own {W.pmod['power']} "
        f"supply on those pins (the {W.board['hat']} from the Raspberry Pi's). Whether the cables in use join "
        f"the {W.pmod['power']} pins of the two boards is not recorded, and nor is the kind of cable (what is "
        "on each of its ends).\n"
    )


READING = (
    f"**Reading the table.** *iCE40 pin* is the pin number of the FPGA itself (a {W.board['fpga']}). *Signal* "
    "is the Tiny Tapeout name a design uses. *Demo board* and *Pmod HAT* give the connector and its pin; a "
    "cable joins pins of the same number. *Pi GPIO* is the Raspberry Pi's GPIO number (the BCM number), not a "
    "position on its 40-pin header.\n"
)


def gpio_cell(wire):
    return f"GPIO{wire.gpio}" + (" (shared)" if W.shares(wire) else "")


def checked_cell(wire):
    return "measured" if W.measured(wire) else "from the design"


def chain(wire):
    """A wire's way from the FPGA to the Raspberry Pi, as the cells every wire table has."""
    return [
        wire.fpga_pin,
        code(wire.signal),
        f"{header_name(wire.header)} pin {wire.pin}",
        f"{wire.port} pin {wire.pin}",
        gpio_cell(wire),
    ]


CHAIN = ["iCE40 pin", "Signal", "Demo board", "Pmod HAT", "Pi GPIO"]


def checked(wires):
    """What 'measured' and 'from the design' mean for these wires, in one short line: the days of the
    measurement here, and where and how once, on the sources page."""
    out = []
    for m in dict.fromkeys(W.measured(w) for w in wires):
        if m is not None:
            out.append(
                f"*measured*: read on boards on {spoken(m.dates)}; for where and how, see Sources "
                f"({code(SOURCES_PAGE)})."
            )
    if any(W.measured(w) is None for w in wires):
        out.append(f"*from the design*: not read on a board; {W.unmeasured['why']}.")
    return "**Checked.** " + " ".join(out) + "\n"


def shared(wires):
    """The paragraph on the GPIOs that two wires end on, if any of `wires` is such a wire; else ''."""
    pairs = {}
    for wire in wires:
        for other in W.shares(wire):
            pairs.setdefault(wire.gpio, sorted([wire, other], key=W.wires.index))
    if not pairs:
        return ""
    joined = "; ".join(
        f"GPIO{gpio} is {a.port} pin {a.pin} and {b.port} pin {b.pin} ({code(a.signal)} and {code(b.signal)})"
        for gpio, (a, b) in pairs.items()
    )
    both = sorted({w.group for pair in pairs.values() for w in pair if W.groups[w.group]["drive"] == "both"})
    fight = ""
    if both:
        fight = (
            f" A design that drives one of these {spoken(code(g) for g in both)} signals drives the signal it "
            "shares with too, and the Raspberry Pi must then leave that GPIO as an input."
        )
    return (
        f"**Shared GPIOs.** The {W.board['hat']} joins some pins of two ports to one Raspberry Pi GPIO, so the "
        f"two signals on them are one wire at the Raspberry Pi: {joined}. Whatever the Raspberry Pi puts on such "
        "a GPIO reaches both signals."
        f"{fight}\n"
    )


def group_section(group):
    g = W.groups[group]
    wires = W.of_group(group)
    drive = {
        "pi": "The Raspberry Pi drives these; the FPGA reads them.",
        "fpga": "The FPGA drives these; the Raspberry Pi reads them.",
        "both": "Either end may drive each of these: the design decides, signal by signal.",
    }[g["drive"]]
    extra = ""
    if W.display["group"] == group:
        extra = " The same eight signals light the demo board's seven-segment display."
    head = [*CHAIN, "Checked"]
    parts = [
        f"### {code(group)}: {g['what']}",
        f"{drive}{extra} They are on the demo board's {W.header_of(group)['name']} header, cabled to Pmod HAT "
        f"port {wires[0].port}.{' ' + g['note'] if g.get('note') else ''}",
        table(head, [[*chain(w), checked_cell(w)] for w in wires]),
        checked(wires),
    ]
    if shared(wires):
        parts.append(shared(wires))
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def cables():
    rows = []
    for key, h in W.headers.items():
        group = group_on(key)
        wires = W.of_group(group)
        states = sorted({checked_cell(w) for w in wires}, reverse=True)
        how = states[0] if len(states) == 1 else "measured, except the wires on shared GPIOs"
        rows.append([h["name"], f"{code(group + '[0]')} to {code(group + '[7]')}", W.cables[key],
                     wiring.DRIVES[W.groups[group]["drive"]], how])  # fmt: skip
    parts = [
        f"{LEAD} This part shows which cable goes where.",
        image("tt-fpga-pmod-cables", "Which Pmod header of the demo board goes to which port of the Pmod HAT"),
        finding(),
        table(["Demo board header", "Signals", "Pmod HAT port", "Driven by", "Checked"], rows),
        checked(W.wires),
        shared(W.wires),
        "The USB-C cable carries the demo board's serial link to the Raspberry Pi: it is how the FPGA is loaded "
        f"and how a design's serial port is reached. {STREAMING}",
    ]
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def ui_uo():
    keys = [W.groups[g]["header"] for g in ("ui_in", "uo_out")]
    parts = [
        f"{LEAD} This part covers {W.groups['ui_in']['what']} ({code('ui_in')}) and "
        f"{W.groups['uo_out']['what']} ({code('uo_out')}), wire by wire.",
        image("tt-fpga-pmod-cables-ui-uo", "The Input header goes to port JA and the Output header to port JC"),
        finding(keys),
        READING,
        group_section("ui_in"),
        group_section("uo_out"),
    ]
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def uart_section():
    u = W.uart
    rx, tx = (W.wire(u[end]["group"], u[end]["bit"]) for end in ("rx", "tx"))
    rows = [[*chain(rx)[:2], u["rx"]["what"], *chain(rx)[2:]], [*chain(tx)[:2], u["tx"]["what"], *chain(tx)[2:]]]
    mcu = W.board["mcu"]
    parts = [
        "### The serial port (UART)",
        f"A design's serial port uses two of the signals of the other two headers, by Tiny Tapeout's "
        f"convention: {code(rx.signal)} carries data into the design and {code(tx.signal)} carries data out of "
        f"it. Our test design runs it at {u['baud']} baud.",
        table([*CHAIN[:2], "Use", *CHAIN[2:]], rows),
        f"On its way to the Raspberry Pi's GPIO, {code(rx.signal)} is {checked_cell(rx)} and {code(tx.signal)} is "
        f"{checked_cell(tx)}.",
        checked([rx, tx]),
        f"The demo board's microcontroller (an {mcu} on a version 3 demo board) is on the same two signals: its "
        f"GPIO{rx.mcu_gpio} sends to {code(rx.signal)} and its GPIO{tx.mcu_gpio} receives from "
        f"{code(tx.signal)}. Our {code('uart')} test talks to the design through the microcontroller and the "
        f"USB-C cable, not through the Pmod HAT. {u['checked']}. Nobody has used these two signals as a serial "
        f"port from the Raspberry Pi's own GPIOs, which would mean sending on GPIO{rx.gpio} and receiving on "
        f"GPIO{tx.gpio}.",
    ]
    if shared([rx, tx]):
        parts.append(shared([rx, tx]))
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def uio_uart():
    parts = [
        f"{LEAD} This part covers the {code('uio')} signals, wire by wire, and the serial port.",
        image("tt-fpga-pmod-cables", "Which Pmod header of the demo board goes to which port of the Pmod HAT"),
        finding(),
        READING,
        group_section("uio"),
        uart_section(),
    ]
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def loading_section():
    mcu = W.board["mcu"]
    fpga_pins = [[c["pin"], code(c["name"])] for c in W.config["fpga"]]
    return "\n\n".join(
        [
            "### Loading the FPGA: its configuration pins",
            STREAMING,
            "The FPGA breakout has no SPI flash (no memory chip that keeps a design), so the FPGA is loaded "
            "again after every power-up. Its four configuration pins go only to the demo board's "
            "microcontroller. None is on a Pmod header: no cable carries them, and the Raspberry Pi cannot "
            "reach them.",
            table(["iCE40 pin", "The iCE40's name for it"], fpga_pins).strip(),
            f"The pins of the microcontroller (an {mcu} on a version 3 demo board) that our loader drives:",
            table([f"{mcu} pin", "What our loader uses it for"],
                  [[f"GPIO{c['gpio']}", c["what"]] for c in W.config["mcu"]]).strip(),
            "Which microcontroller pin is wired to which of the four iCE40 pins is not recorded in this "
            "repository and has not been measured by us.",
        ]
    ) + "\n"  # fmt: skip


def display_section():
    group = W.display["group"]
    wires = W.of_group(group)
    key = W.groups[group]["header"]
    rows = [
        [seg, *chain(w)[1:2], w.fpga_pin, *chain(w)[2:]] for seg, w in zip(W.display["segments"], wires, strict=True)
    ]
    return "\n\n".join(
        [
            "### The seven-segment display",
            f"The display is on the eight {code(group)} signals, the same ones that go to the "
            f"{header_name(key)} header: whatever a design puts on {code(group)} shows on the display and "
            "reaches the Raspberry Pi too. Segments a to f are the six bars of the outer ring, in the order "
            "`designs/tt-display` runs round it; where a is, and which way round the ring that order goes, is "
            "not recorded and not verified by us. g is the middle bar and the dot is the decimal point.",
            image("tt-fpga-pmod-cables-uo", f"The {header_name(key)} header goes to port {W.cables[key]}").strip(),
            finding([key]).strip(),
            table(["Segment", "Signal", "iCE40 pin", *CHAIN[2:]], rows).strip(),
            checked(wires).strip()
            + " Which segment each signal lights is from Tiny Tapeout's board specification; not verified by "
            "us segment by segment.",
        ]
    ) + "\n"  # fmt: skip


def other_section():
    mcu = W.board["mcu"]
    rows = []
    for o in W.other:
        gpio = "not recorded"
        if "mcu_gpio" in o:
            gpio = f"GPIO{o['mcu_gpio']}" + ("" if o["mcu_source"] == "code" else " (not verified by us)")
        what = o["what"] + (f": {o['hz'] / 1e6:g} MHz" if "hz" in o else "")
        rows.append([o["pin"], code(o["signal"]), what, gpio])
    groups = [
        [f"{code(g + '[0]')} to {code(g + '[7]')}", f"GPIO{v['mcu_first_gpio']} to GPIO{v['mcu_first_gpio'] + 7}"]
        for g, v in W.groups.items()
    ]
    return "\n\n".join(
        [
            "### The clock, the reset and the LED",
            "None of these is on a Pmod header: no cable carries them, and the Raspberry Pi cannot reach them. "
            "*Name in our designs* is the name in `designs/_shared/tt_fpga_platform.py`.",
            table(["iCE40 pin", "Name in our designs", "What it is", f"{mcu} pin"], rows).strip(),
            "### The same 24 signals at the microcontroller",
            f"For a version 3 demo board, whose microcontroller is an {mcu}; a version 2 demo board has an "
            "RP2040 with other pin numbers, and our loader is written for version 3. Bit 0 is on the first "
            "GPIO of each range and bit 7 on the last.",
            table(["Signals", f"{mcu} pins"], groups).strip(),
            "After a load made with `--gpio-release`, our loader sets these 24 pins "
            "to inputs, so that only the FPGA and the Raspberry Pi drive the signals.",
        ]
    ) + "\n"  # fmt: skip


def other():
    parts = [
        f"{LEAD} This part covers the pins that load the FPGA, the seven-segment display, the clock, the reset "
        "and the LED.",
        loading_section(),
        display_section(),
        other_section(),
    ]
    return "\n\n".join(p.strip("\n") for p in parts) + "\n"


def sources():
    """{statement: where it comes from}: the entries the measurements give, then wiring.toml's [sources]."""
    out = {}
    cabling = spoken(f"{h['name']} to {W.cables[k]}" for k, h in W.headers.items())
    for m in W.measurements:
        covered = [w for w in W.wires if w.signal in m.wires]
        rest = [w for w in W.wires if w.signal not in m.wires]
        which = f"every wire except {spoken(code(w.signal) for w in rest)}" if rest else "every wire"
        also = f" {m.also}." if m.also else ""
        out[
            f"Which demo board header is cabled to which Pmod HAT port ({cabling}), and the {len(covered)} wires "
            f"that have a Raspberry Pi GPIO to themselves ({which})"
        ] = (
            f"measured: {m.how} {m.when}, {m.where}.{also} The record is {m.record}. The measurement joins an "
            "iCE40 pin to a Raspberry Pi GPIO; the header pin and the port pin in between are from the entries "
            "below"
        )
    unmeasured = [w for w in W.wires if W.measured(w) is None]
    if unmeasured:
        also = f". {W.unmeasured['also']}" if W.unmeasured.get("also") else ""
        out[f"The wires no measurement covers ({spoken(code(w.signal) for w in unmeasured)})"] = (
            f"from the design: {W.unmeasured['why']}{also}"
        )
    for claim, source in W.sources.items():
        out[claim] = source.replace("{uart.checked}", W.uart["checked"])
    return out


def sources_page():
    lines = [
        "Where each statement of fact on the Tiny Tapeout FPGA wiring pages comes from. A statement nobody has "
        "checked says so. A board is named by where it was seen on the day of the measurement, because that is "
        "all the record gives.",
        "",
        *(f"- {claim}: {source}." for claim, source in sources().items()),
    ]
    return "\n".join(lines) + "\n"


def build():
    return {
        "tt-fpga-cables.md": BANNER + cables(),
        "tt-fpga-pins-ui-uo.md": BANNER + ui_uo(),
        "tt-fpga-pins-uio-uart.md": BANNER + uio_uart(),
        "tt-fpga-pins-other.md": BANNER + other(),
        SOURCES_PAGE: BANNER + sources_page(),
    }
