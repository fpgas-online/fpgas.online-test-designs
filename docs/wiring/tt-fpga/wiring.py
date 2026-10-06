# SPDX-License-Identifier: Apache-2.0
"""Load wiring.toml, the one copy of how a Tiny Tapeout FPGA demo board is wired to its Raspberry Pi, and
check it hangs together.

Everything that needs the wiring (the picture, the Markdown tables, the test that the code agrees) reads
it through here, so a mistake in the table stops the build instead of reaching a page.

A wire is one signal's whole way: iCE40 pin, Tiny Tapeout signal, demo board header and pin, Pmod HAT port
and pin, Raspberry Pi GPIO. WIRES has every one of them, in the order of the HAT's ports.
"""

import pathlib
from dataclasses import dataclass

import tomllib

HERE = pathlib.Path(__file__).parent
DRIVES = {"pi": "the Raspberry Pi", "fpga": "the FPGA", "both": "either end"}


class WiringError(Exception):
    pass


@dataclass(frozen=True)
class Wire:
    group: str  # ui_in, uio or uo_out
    bit: int
    fpga_pin: int  # the iCE40's package pin
    header: str  # key of the demo board header
    pin: int  # the pin of that header, and of the HAT port: every cable is straight through
    port: str  # the Pmod HAT port
    gpio: int  # the Raspberry Pi GPIO (BCM number)
    mcu_gpio: int  # the demo board microcontroller's GPIO on the same signal

    @property
    def signal(self):
        return f"{self.group}[{self.bit}]"


@dataclass(frozen=True)
class Measurement:
    wires: frozenset  # the signals it covers
    dates: tuple  # the days it was made, as printed
    how: str
    when: str  # who or what measured on each of those days, with the days in it
    where: str
    also: str
    record: str


@dataclass(frozen=True)
class Wiring:
    board: dict
    pmod: dict
    groups: dict  # name -> {what, drive, fpga_pins, connector, header, mcu_first_gpio, colour}
    headers: dict  # key -> {name}: the name printed on the board
    hat: dict  # port -> {gpios}
    cables: dict  # header key -> port
    uart: dict
    display: dict
    config: dict  # {fpga: [{name, pin}], mcu: [{name, gpio, what}]}
    other: list  # [{signal, pin, what, mcu_gpio?, mcu_source?}]
    wires: tuple  # every Wire, in the order of the HAT's ports, then by bit
    measurements: tuple
    unmeasured: dict
    sources: dict
    facts: dict  # key -> {says, source}: what the makers' documents say

    def wire(self, group, bit):
        return next(w for w in self.wires if w.group == group and w.bit == bit)

    def of_group(self, group):
        return [w for w in self.wires if w.group == group]

    def shares(self, wire):
        """The other wires that end on the same Raspberry Pi GPIO."""
        return [w for w in self.wires if w.gpio == wire.gpio and w != wire]

    def shared(self):
        """Every wire that shares its GPIO with another, in WIRES' order."""
        return [w for w in self.wires if self.shares(w)]

    def measured(self, wire):
        """The measurement that covers this wire, or None: then it is from the design."""
        return next((m for m in self.measurements if wire.signal in m.wires), None)

    def header_of(self, group):
        return self.headers[self.groups[group]["header"]]


def _need(table, keys, what, errors):
    missing = [k for k in keys if k not in table or table[k] in ("", [], None)]
    if missing:
        errors.append(f"{what} has no {', '.join(missing)}")
    return not missing


def build(data):
    """A Wiring from wiring.toml's contents; WiringError, with every problem found, if it does not check."""
    errors = []
    pmod, groups, headers, hat, cables = (data[k] for k in ("pmod", "groups", "headers", "hat", "cables"))

    signal_pins = pmod["signal_pins"]
    if len(signal_pins) != 8 or sorted([*signal_pins, *pmod["ground_pins"], *pmod["power_pins"]]) != list(range(1, 13)):
        errors.append("[pmod] must give each of pins 1 to 12 once: eight signal pins, the ground pins, the power pins")

    carried = {}
    for name, g in groups.items():
        if not _need(
            g, ("what", "drive", "fpga_pins", "connector", "header", "mcu_first_gpio", "colour"), name, errors
        ):
            continue
        if g["drive"] not in DRIVES:
            errors.append(f"{name}: drive is {g['drive']!r}; it must be one of {', '.join(DRIVES)}")
        if len(g["fpga_pins"]) != 8:
            errors.append(f"{name}: {len(g['fpga_pins'])} iCE40 pins; a group has eight")
        if g["header"] not in headers:
            errors.append(f"{name}: is on header {g['header']!r}, which [headers] does not list")
        elif g["header"] in carried:
            errors.append(f"{name} and {carried[g['header']]} are both on header {g['header']!r}")
        carried[g["header"]] = name
    for key, h in headers.items():
        _need(h, ("name",), f"header {key}", errors)
        if key not in carried:
            errors.append(f"header {key!r} carries no group")
        if key not in cables:
            errors.append(f"header {key!r} has no cable in [cables]")
    for port, p in hat.items():
        if len(p.get("gpios", [])) != 8 or len(set(p["gpios"])) != 8:
            errors.append(f"Pmod HAT port {port}: needs eight different GPIOs, one for each signal pin")
    for key, port in cables.items():
        if key not in headers:
            errors.append(f"[cables]: {key!r} is not a header")
        if port not in hat:
            errors.append(f"[cables]: header {key!r} goes to port {port!r}, which [hat] does not list")
        if list(cables.values()).count(port) > 1:
            errors.append(f"[cables]: two headers go to port {port}")
    if errors:  # the wires cannot be made from this
        raise WiringError("wiring.toml:\n  " + "\n  ".join(dict.fromkeys(errors)))

    wires = []
    for port in hat:
        for name, g in groups.items():
            if cables[g["header"]] != port:
                continue
            for bit, fpga_pin in enumerate(g["fpga_pins"]):
                wires.append(
                    Wire(name, bit, fpga_pin, g["header"], signal_pins[bit], port, hat[port]["gpios"][bit],
                         g["mcu_first_gpio"] + bit)
                )  # fmt: skip

    # every iCE40 pin has one use
    uses = [(w.fpga_pin, w.signal) for w in wires]
    uses += [(o["pin"], o["signal"]) for o in data.get("other", [])]
    uses += [(c["pin"], c["name"]) for c in data["config"]["fpga"]]
    for pin in sorted({p for p, _ in uses}):
        names = [n for p, n in uses if p == pin]
        if len(names) > 1:
            errors.append(f"iCE40 pin {pin} is given to {' and '.join(names)}")
    # every microcontroller GPIO has one use
    mcu = [(w.mcu_gpio, w.signal) for w in wires]
    mcu += [(o["mcu_gpio"], o["signal"]) for o in data.get("other", []) if "mcu_gpio" in o]
    mcu += [(c["gpio"], f"the loader's {c['name']}") for c in data["config"]["mcu"]]
    for gpio in sorted({g for g, _ in mcu}):
        names = [n for g, n in mcu if g == gpio]
        if len(names) > 1:
            errors.append(f"{data['board']['mcu']} GPIO{gpio} is given to {' and '.join(names)}")
    for o in data.get("other", []):
        if ("mcu_gpio" in o) != ("mcu_source" in o) or o.get("mcu_source", "code") not in ("code", "tt"):
            errors.append(f'{o["signal"]}: mcu_gpio needs mcu_source = "code" or "tt", and the other way round')

    # a Raspberry Pi GPIO that two wires end on: never more than two, and never one the FPGA always drives
    for gpio in sorted({w.gpio for w in wires}):
        on = [w for w in wires if w.gpio == gpio]
        if len(on) > 2:
            errors.append(f"GPIO{gpio} has {len(on)} wires: {', '.join(w.signal for w in on)}")
        if len(on) > 1:
            for w in on:
                if groups[w.group]["drive"] == "fpga":
                    others = ", ".join(o.signal for o in on if o != w)
                    errors.append(f"{w.signal}, which the FPGA drives, shares GPIO{gpio} with {others}")

    clocks = [o for o in data.get("other", []) if "hz" in o]
    if len(clocks) != 1 or not isinstance(clocks[0]["hz"], int) or clocks[0].get("mcu_source") != "code":
        errors.append("[[other]] needs one clock: an entry with a whole `hz`, made by a GPIO our code drives")

    uart = data["uart"]
    for end, drive in (("rx", "pi"), ("tx", "fpga")):
        u = uart[end]
        if u["group"] not in groups or not 0 <= u["bit"] <= 7:
            errors.append(f"[uart] {end}: {u['group']}[{u['bit']}] is not a signal")
        elif groups[u["group"]]["drive"] != drive:
            errors.append(f"[uart] {end} is on {u['group']}, which {DRIVES[groups[u['group']]['drive']]} drives")
    display = data["display"]
    if display["group"] not in groups or len(display["segments"]) != 8:
        errors.append("[display] needs a group and the eight segments its bits light")

    signals = {w.signal for w in wires}
    own = frozenset(w.signal for w in wires if [x.gpio for x in wires].count(w.gpio) == 1)
    measurements = []
    for m in data.get("measurements", []):
        if not _need(m, ("wires", "dates", "how", "when", "where", "record"), "a measurement", errors):
            continue
        when = m["when"].format(*m["dates"])
        if not all(date in when for date in m["dates"]):
            errors.append("a measurement's `when` must name each of its `dates`, as {0}, {1}, ...")
        covered = own if m["wires"] == "own" else frozenset(m["wires"])
        if not covered <= signals:
            errors.append(f"a measurement names wires that do not exist: {', '.join(sorted(covered - signals))}")
        measurements.append(
            Measurement(covered, tuple(m["dates"]), m["how"], when, m["where"], m.get("also", ""), m["record"])
        )
    _need(data.get("unmeasured", {}), ("why",), "[unmeasured]", errors)
    facts = {}
    for fact in data.get("facts", []):
        if _need(fact, ("key", "says", "source"), "a fact", errors):
            if fact["key"] in facts:
                errors.append(f"two facts have the key {fact['key']!r}")
            facts[fact["key"]] = fact
    if not data.get("sources"):
        errors.append("[sources] is empty: every statement of fact on the pages needs where it comes from")
    if errors:
        raise WiringError("wiring.toml:\n  " + "\n  ".join(errors))
    return Wiring(
        data["board"], pmod, groups, headers, hat, cables, uart, display, data["config"], data.get("other", []),
        tuple(wires), tuple(measurements), data["unmeasured"], data["sources"], facts,
    )  # fmt: skip


DATA = tomllib.loads((HERE / "wiring.toml").read_text())
WIRING = build(DATA)
