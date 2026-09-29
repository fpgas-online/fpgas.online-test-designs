"""The Acorn's links to its Pi besides PCIe, checked at boot: P1 (JTAG) and P2 (the UART).

check.py proves only what PCIe can see: which image runs and what the flash holds. A board passed that with
its JTAG cable off, or with nothing on its P2 UART (test-designs #55), and nothing noticed until someone
tried to load a design or talk to the SoC. So:

  jtag     `openFPGALoader --detect` over the P1 cable (GPIO bit-bang, docs/wiring/acorn/generated/
           acorn-pi5-p1.md: TDI 10, TDO 9, TCK 11, TMS 8) must find one device with the variant's IDCODE.
           --detect does not reconfigure the FPGA, so the enumerated PCIe endpoint is safe
           (docs/hardware/acorn-pcie-programming.md). openFPGALoader leaves TMS/TDI/TCK driven, so all four
           pins go back to inputs afterwards.
  p2-uart  Only when the fpgas.online SoC runs (it bridges UARTBone onto P2's K2/J2): the identifier read over
           /dev/ttyAMA0 must be the one tier 2 read over BAR0. That needs both directions of the link.

Each gives a test entry in the board's report, in the shape testbench.py uses ({test, result, output}).
"""

import os
import re

from ...core import Problem
from . import uartbone_link

JTAG_PINS = "10:9:11:8"  # openFPGALoader --pins: TDI:TDO:TCK:TMS
JTAG_GPIOS = "8,9,10,11"
JTAG_TIMEOUT = 60
# The IDCODE of each variant's FPGA, the revision nibble masked off (check.py's variants).
IDCODES = {"cle-215+": 0x3636093, "cle-215": 0x3636093, "cle-101": 0x3631093}
IDCODE_RE = re.compile(r"idcode\s+(0x[0-9a-fA-F]+)")
# openFPGALoader's libgpiod cable opens /dev/gpiochip0; on a Pi 5 the 40-pin header is gpiochip15.
GPIOCHIP, HEADER_GPIOCHIP = "/dev/gpiochip0", "/dev/gpiochip15"
UART = "/dev/ttyAMA0"


def _header_gpiochip():
    """Point /dev/gpiochip0 at the header chip (devtmpfs: gone at reboot). A freshly booted Pi 5 has no
    gpiochip0 (pi-sw2-p37, 2026-09-30: gpiochip11-15, 15 = pinctrl-rp1); if some other chip is gpiochip0,
    probing it would test the wrong pins, so that is refused."""
    if not os.path.lexists(GPIOCHIP):
        if os.path.exists(HEADER_GPIOCHIP):
            os.symlink(HEADER_GPIOCHIP, GPIOCHIP)
        return
    if os.path.realpath(GPIOCHIP) != os.path.realpath(HEADER_GPIOCHIP):
        raise Problem("error", f"{GPIOCHIP} is not the 40-pin header ({HEADER_GPIOCHIP}): P1 JTAG not probed")


def _release_pins(run):
    """Put the JTAG pins back to inputs; a note for the output if that did not work."""
    try:
        rc, out = run(["pinctrl", "set", JTAG_GPIOS, "ip", "pd"], 10)
    except Problem as e:
        return [f"could not release GPIO {JTAG_GPIOS}: {e}"]
    return [] if rc == 0 else [f"could not release GPIO {JTAG_GPIOS}: {out.strip()}"]


def jtag(variant, run, gpiochip=None):
    want = IDCODES[variant]
    try:
        (gpiochip or _header_gpiochip)()
        rc, out = run(["openFPGALoader", "--cable", "libgpiod", "--pins", JTAG_PINS, "--detect"], JTAG_TIMEOUT)
    except (Problem, OSError) as e:
        # A missing tool or a wrong gpiochip is the check not running ("error"); a hung probe is a fail.
        result = e.result if isinstance(e, Problem) else "error"
        return {"test": "jtag", "result": result, "output": [str(e), *_release_pins(run)],
                "reason": f"P1 JTAG could not be probed: {e}"}  # fmt: skip
    found = [int(x, 16) & 0x0FFFFFFF for x in IDCODE_RE.findall(out)]
    tail = out.strip().splitlines()[-8:] + _release_pins(run)
    if rc != 0 or not found:
        return {"test": "jtag", "result": "fail", "output": tail, "reason": "no device on the P1 JTAG chain"}
    if found != [want]:
        seen = ", ".join(f"{i:#09x}" for i in found)
        return {"test": "jtag", "result": "fail", "output": tail,
                "reason": f"P1 JTAG chain has {seen}, expected {want:#09x} for {variant}"}  # fmt: skip
    return {"test": "jtag", "result": "pass", "output": tail}


def p2_uart(identifier, open_port=None):
    """At the reset rate (1200 baud, after a break): the ident is short, and the link is left where the
    next user of /dev/ttyAMA0 expects it."""
    try:
        link = uartbone_link.UARTBoneLink(open_port or uartbone_link._serial_opener(UART))
    except ImportError as e:  # pyserial
        return {"test": "p2-uart", "result": "error", "output": [str(e)], "reason": f"P2 UART not checked: {e}"}
    try:
        baud = link.connect(fast=False)
        got = link.ident()
    except (uartbone_link.LinkError, OSError) as e:
        return {"test": "p2-uart", "result": "fail", "output": [str(e)],
                "reason": f"no UARTBone reply on {UART} (P2 K2/J2)"}  # fmt: skip
    finally:
        link.close()
    out = [f"baud {baud}", f"ident {got!r}"]
    if got != identifier:
        return {"test": "p2-uart", "result": "fail", "output": out,
                "reason": f"UARTBone ident {got!r} is not the BAR0 identifier {identifier!r}"}  # fmt: skip
    return {"test": "p2-uart", "result": "pass", "output": out}
