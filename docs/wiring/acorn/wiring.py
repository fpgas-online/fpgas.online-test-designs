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
DIRECTION = {"pi": "Pi → FPGA", "fpga": "FPGA → Pi", "both": "either"}


@dataclass
class Header:
    key: str
    name: str
    short: str  # its name inside a sentence: "a housing on header pins 5 to 10"
    columns: int
    pins: dict  # pin number -> {name, gpio, func, tag, rpi}
    housings: list  # [(first pin, last pin)]


@dataclass
class Carrier:
    key: str
    name: str
    jtag_pins: str
    resistors: set
    resistor_value: str
    headers: dict  # key -> Header
    wires: dict  # signal -> (header key, pin)

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


def _carrier(key, raw):
    headers = {}
    for hk, h in raw["headers"].items():
        pins = {int(n): p for n, p in h["pins"].items()}
        headers[hk] = Header(
            hk, h["name"], h.get("short", h["name"]), h["columns"], pins, [tuple(r) for r in h.get("housings", [])]
        )
    wires = {s: (w[0], int(w[1])) for s, w in raw["wires"].items()}
    c = Carrier(
        key, raw["name"], raw["jtag_pins"], set(raw.get("resistors", [])), raw.get("resistor_value", ""), headers, wires
    )
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
    if c.resistors and not c.resistor_value:
        errors.append(f"{c.key}: resistors listed but no resistor_value")
    for r in c.resistors:
        if r not in c.wires:
            errors.append(f"{c.key}: resistor listed for {r}, which is not wired")
    if errors:
        raise WiringError("wiring.toml:\n  " + "\n  ".join(errors))


CARRIERS = {k: _carrier(k, v) for k, v in DATA["carriers"].items()}
