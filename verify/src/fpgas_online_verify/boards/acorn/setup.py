"""Which Acorn setup this host is, and how that setup is wired: read from docs/wiring/acorn/.

There are two setups (docs/verify-goals.md): an Acorn on a Pi 5 through a Waveshare HAT, and an Acorn on a
Compute Blade with a CM4 or CM5. Each is a carrier in wiring.toml, the one copy of the wiring; the figures
the check expects of each (PCIe link speed and width, XADC ranges) are in expected.toml beside it. Both
files ship with the Acorn's module (fpgas-online-acorn-tools puts them in data/ here); run from a checkout,
they are read from the repository.

The host is matched to a carrier by its device-tree model. From the carrier come the JTAG pins and cable,
the device-tree compatible of the GPIO chip those pins are on, the serial port on K2/J2, and the Pi GPIOs
the spare P2 balls (J5, H5) land on: none on a carrier whose cable leaves them cut.
"""

import pathlib
from dataclasses import dataclass, field

from ...core import Problem

HERE = pathlib.Path(__file__).resolve().parent
# Installed: data/ beside this file. From a checkout: verify/src/fpgas_online_verify/boards/acorn -> the repo.
DATA_DIRS = (HERE / "data", HERE.parents[4] / "docs" / "wiring" / "acorn")
WIRING, EXPECTED = "wiring.toml", "expected.toml"
JTAG_ORDER = ("TDI", "TDO", "TCK", "TMS")  # openFPGALoader --pins


def load(name, dirs=DATA_DIRS):
    try:
        import tomllib
    except ImportError:  # Python 3.10 or older
        raise Problem("error", f"reading {name} needs Python 3.11 or newer") from None
    for d in dirs:
        path = pathlib.Path(d) / name
        if path.is_file():
            try:
                return tomllib.loads(path.read_text())
            except (OSError, ValueError) as e:
                raise Problem("error", f"cannot read {path}: {e}") from None
    raise Problem("error", f"{name} is not installed (looked in {', '.join(str(d) for d in dirs)})")


@dataclass
class Setup:
    key: str  # the carrier's key in wiring.toml: pi5, blade
    name: str
    model: str  # the device-tree model prefix that matched
    gpiochip: str  # device-tree compatible of the header's GPIO chip
    jtag_cable: str
    jtag_pins: str  # TDI:TDO:TCK:TMS, as openFPGALoader --pins takes them
    uart: str
    p2_gpio: dict = field(default_factory=dict)  # P2 ball -> Pi GPIO number, for the wired spare balls
    p2_serial: dict = field(default_factory=dict)  # J2/K2 -> Pi GPIO number
    expected: dict = field(default_factory=dict)  # this setup's figures from expected.toml, and "xadc"

    @property
    def jtag_gpios(self):
        return [int(n) for n in self.jtag_pins.split(":")]


def _gpio_of(carrier, signal):
    """The Pi GPIO number a P1/P2 signal lands on in this carrier, or None if it is not wired."""
    wire = carrier.get("wires", {}).get(signal)
    if not wire:
        return None
    pin = carrier["headers"][wire[0]]["pins"][str(wire[1])]
    gpio = pin.get("gpio", "")
    return int(gpio.removeprefix("GPIO")) if gpio.startswith("GPIO") else None


def setups(wiring=None):
    """{carrier key: [(model prefix, gpiochip compatible)]} for every carrier the wiring lists hosts for."""
    wiring = wiring or load(WIRING)
    return {k: [(m, h["gpiochip"]) for m, h in c.get("hosts", {}).items()] for k, c in wiring["carriers"].items()}


def detect(model, wiring=None, expected=None):
    """The Setup of a host with this device-tree model. A host that is none of them is the check's error: the
    wiring it should have is unknown."""
    wiring = wiring or load(WIRING)
    for key, carrier in wiring["carriers"].items():
        for prefix, host in carrier.get("hosts", {}).items():
            if model.startswith(prefix):
                return _setup(key, carrier, prefix, host, load(EXPECTED) if expected is None else expected)
    known = ", ".join(f"{m} ({c['name']})" for c in wiring["carriers"].values() for m in c.get("hosts", {}))
    raise Problem("error", f"this host ({model or 'no device-tree model'}) is not an Acorn setup in {WIRING}: "
                           f"{known}")  # fmt: skip


def _setup(key, carrier, prefix, host, expected):
    pins = ":".join(str(_gpio_of(carrier, s)) for s in JTAG_ORDER)
    if pins != carrier["jtag_pins"]:  # wiring.py checks the same when the sheets are built
        raise Problem("error", f"{WIRING}: {key} jtag_pins is {carrier['jtag_pins']}, but TDI:TDO:TCK:TMS land on "
                               f"{pins}")  # fmt: skip
    spare = {s: _gpio_of(carrier, s) for s in ("J5", "H5")}
    return Setup(
        key=key,
        name=carrier["name"],
        model=prefix,
        gpiochip=host["gpiochip"],
        jtag_cable=carrier["jtag_cable"],
        jtag_pins=carrier["jtag_pins"],
        uart=carrier["uart"],
        p2_gpio={s: g for s, g in spare.items() if g is not None},
        p2_serial={s: g for s in ("J2", "K2") if (g := _gpio_of(carrier, s)) is not None},
        expected={**expected.get("setups", {}).get(key, {}), "xadc": expected.get("xadc", {})},
    )
