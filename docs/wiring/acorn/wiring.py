# SPDX-License-Identifier: Apache-2.0
"""Load wiring.toml, the one copy of how an Acorn is wired to each host, and check it hangs together.

Everything that needs the wiring (the sheets, the Markdown tables) reads it through here, so a
mistake in the table stops the build instead of reaching a drawing.
"""

import pathlib
from dataclasses import dataclass

import tomllib

HERE = pathlib.Path(__file__).parent
DATA = tomllib.loads((HERE / "wiring.toml").read_text())

CONNECTORS = DATA["connectors"]
SIGNALS = DATA["signals"]
# [{tool, note?, when?, carrier?}]: what building and fitting the cables takes. `when = "resistor"`: only where a
# wire has one. `carrier`: on that carrier's list only.
TOOLS = DATA.get("tools", [])
for _tool in TOOLS:
    if (
        not _tool.get("tool")
        or set(_tool) - {"tool", "note", "note_resistor", "when", "carrier"}
        or _tool.get("when", "resistor") != "resistor"
    ):
        raise ValueError(
            f'wiring.toml: a tool needs a `tool`, and may have `note`, `when = "resistor"` and `carrier`: {_tool}'
        )
SOURCES = DATA["sources"]  # [{claim, source, carrier (optional)}]: where a fact on the pages comes from
LENGTHS = DATA["lengths"]  # {cut_back, resistor, strip, tube, resistor_tube, flag_back, resistor_lead} in mm
if LENGTHS["flag_back"] <= LENGTHS["resistor"]:
    raise ValueError("wiring.toml: [lengths] flag_back must be greater than resistor, or the flag is cut off")
if not any(f"heat-shrink tube, about {LENGTHS['tube']} mm" in p["part"] for p in DATA.get("parts", [])):
    raise ValueError("wiring.toml: [lengths] tube is not the size of the heat-shrink tube in [[parts]]")
DIRECTION = {"pi": "Pi → FPGA", "fpga": "FPGA → Pi", "both": "either"}


@dataclass
class Header:
    key: str
    name: str
    short: str  # its name inside a sentence: "a housing on header pins 5 to 10"
    columns: int
    pins: dict  # pin number -> {name, gpio, func, tag, rpi}
    housings: list  # [(first pin, last pin)]
    numbering: str = "across"  # how the printed numbers run, seen from above: "across" rows or "down" columns
    count: int = 0  # how many pins the whole header has
    printed: bool = False  # the pin numbers are printed on the board beside the header

    def grid(self, first, last):
        """Pins `first` to `last` as they sit on the board seen from above: one tuple per row, left to right."""
        rows, rest = divmod(last - first + 1, self.columns)
        if rest:
            raise WiringError(f"{self.key}: pins {first} to {last} do not fill {self.columns} columns")
        if self.numbering == "down":
            return [tuple(first + c * rows + r for c in range(self.columns)) for r in range(rows)]
        return [tuple(first + r * self.columns + c for c in range(self.columns)) for r in range(rows)]


@dataclass
class Carrier:
    key: str
    name: str
    jtag_pins: str
    resistors: set
    resistor_value: str
    headers: dict  # key -> Header
    wires: dict  # signal -> (header key, pin)
    parts: list  # [{qty, part, number?, note?}] besides what the wiring itself counts
    host: str = ""  # the host in a word, for a pin name that needs its owner: "blade TX"
    shell: str = ""  # bare metal of the host that is its ground, for a meter probe
    power_off: str = ""  # how the host is made dead before the cables are fitted, as a sentence
    contact: str = ""  # whom the reader tells what the guide cannot settle: "Tell {contact}."

    def tag(self, sig):
        """The host's name for the pin a signal lands on, as the sheet prints it; None for none."""
        hdr, pin = self.wires[sig]
        return self.headers[hdr].pins[pin].get("tag")

    def unused(self, connector):
        """Signals of a connector that this carrier leaves cut back, VCC apart."""
        return [s for s in CONNECTORS[connector]["pins"] if s != "VCC" and s not in self.wires]

    def mapping(self, header):
        return {s: pin for s, (h, pin) in self.wires.items() if h == header}

    def same_gpio(self, header, pin):
        """Other header pins on the same SoC line: [(header, pin)]."""
        gpio = self.headers[header].pins[pin].get("gpio")
        if not gpio:
            return []
        return [
            (h.key, n)
            for h in self.headers.values()
            for n, p in h.pins.items()
            if p.get("gpio") == gpio and (h.key, n) != (header, pin)
        ]


class WiringError(Exception):
    pass


# Whom a reader tells what the guide cannot settle, unless a carrier names someone (the public guide's wording).
CONTACT = "whoever gave you this guide"


def _carrier(key, raw):
    headers = {}
    for hk, h in raw["headers"].items():
        pins = {int(n): p for n, p in h["pins"].items()}
        if h["columns"] > 1 and h.get("numbering") not in ("across", "down"):
            raise WiringError(f'wiring.toml: {key}: header {hk} needs numbering = "across" or "down"')
        headers[hk] = Header(
            hk,
            h["name"],
            h.get("short", h["name"]),
            h["columns"],
            pins,
            [tuple(r) for r in h.get("housings", [])],
            h.get("numbering", "across"),
            h.get("count", max(pins)),
            h.get("printed", False),
        )
    wires = {s: (w[0], int(w[1])) for s, w in raw["wires"].items()}
    parts = [*raw.get("parts", []), *DATA.get("parts", [])]  # this carrier's own, then what every carrier needs
    c = Carrier(
        key, raw["name"], raw["jtag_pins"], set(raw.get("resistors", [])), raw.get("resistor_value", ""), headers,
        wires, parts, raw.get("host", raw["name"]), raw["shell"], raw.get("power_off", "Power off the host."),
        raw.get("contact", CONTACT),
    )  # fmt: skip
    _check(c)
    return c


def _check(c):
    errors = []
    connector_signals = {s for conn in CONNECTORS.values() for s in conn["pins"]}
    for s in connector_signals:
        if s not in SIGNALS:
            errors.append(f"connector signal {s} has no [signals] entry")
    taken = {}
    for s, (hk, pin) in c.wires.items():
        if s not in connector_signals:
            errors.append(f"{c.key}: wire for {s}, which is on neither connector")
        if s == "VCC":
            errors.append(f"{c.key}: VCC is wired; it must be cut")
        if hk not in c.headers or pin not in c.headers[hk].pins:
            errors.append(f"{c.key}: {s} goes to {hk} pin {pin}, which the header does not list")
            continue
        name = c.headers[hk].pins[pin]["name"].replace(" ", "")
        if name in ("5V", "3.3V"):
            errors.append(f"{c.key}: {s} goes to {hk} pin {pin}, a {name} pin")
        if (hk, pin) in taken:
            errors.append(f"{c.key}: {taken[(hk, pin)]} and {s} both go to {hk} pin {pin}")
        taken[(hk, pin)] = s
        if not any(a <= pin <= b for a, b in c.headers[hk].housings):
            errors.append(f"{c.key}: {s} goes to {hk} pin {pin}, outside every housing")
        is_ground = SIGNALS[s]["label"] == "GND"
        if is_ground != (c.headers[hk].pins[pin]["name"] == "GND"):
            errors.append(f"{c.key}: {s} goes to {hk} pin {pin} ({c.headers[hk].pins[pin]['name']})")
    # openFPGALoader's --pins is TDI:TDO:TCK:TMS as GPIO numbers; it must be what the JTAG wires land on
    try:
        gpios = [c.headers[c.wires[s][0]].pins[c.wires[s][1]]["gpio"] for s in ("TDI", "TDO", "TCK", "TMS")]
        derived = ":".join(g.removeprefix("GPIO") for g in gpios)
        if derived != c.jtag_pins:
            errors.append(f"{c.key}: jtag_pins is {c.jtag_pins}, but TDI:TDO:TCK:TMS land on {derived}")
    except KeyError as e:
        errors.append(f"{c.key}: a JTAG wire is missing, or lands on a pin with no gpio ({e})")
    for part in c.parts:
        if not isinstance(part.get("qty"), int) or part["qty"] < 1 or not part.get("part"):
            errors.append(f"{c.key}: a part needs a whole `qty` of 1 or more and a `part`: {part}")
        if set(part) - {"qty", "part", "number", "note"}:
            errors.append(f"{c.key}: part {part.get('part')!r} has keys other than qty, part, number, note")
    if c.resistors and not c.resistor_value:
        errors.append(f"{c.key}: resistors listed but no resistor_value")
    for r in c.resistors:
        if r not in c.wires:
            errors.append(f"{c.key}: resistor listed for {r}, which is not wired")
    if errors:
        raise WiringError("wiring.toml:\n  " + "\n  ".join(errors))


CARRIERS = {k: _carrier(k, v) for k, v in DATA["carriers"].items()}
for _tool in TOOLS:
    if _tool.get("carrier", next(iter(CARRIERS))) not in CARRIERS:
        raise WiringError(f"wiring.toml: a tool names a carrier there is none of: {_tool}")
