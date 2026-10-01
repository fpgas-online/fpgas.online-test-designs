"""Sqrl Acorn CLE-215+ / CLE-101 (and NiteFury/LiteFury): found on PCI, checked by suite.py.

Every Xilinx or SQRL PCIe endpoint is claimed. The Acorn-family images are recognised: the fpgas.online SoC
(10ee:7021 with our subsystem IDs), SQRL's factory image and the vendor XDMA sample. Two Xilinx PCIe boards
that are not Acorns are named (a PCIe Screamer running PCILeech, a stock XDMA design that is most likely a
PicoEVB). Anything else (an older build of ours without the subsystem IDs, 10ee:7021 subsystem 10ee:0007, or
another design) fails as "not a design we built": an FPGA is plainly there, so reporting no board at all
would hide it.

An Acorn has its links to the Pi checked as well as PCIe (links.py): P1 JTAG, the P2 UART and, on the Pi 5
setup, the P2 spare balls. Which setup the host is, and how it is wired, comes from wiring.toml (setup.py).

spi_flash.py (fpgas-acorn-flash) is the operator's tool for the same flash, and shares the lock.
"""

from ...board import Board
from . import check, suite


class Acorn(Board):
    name = slug = "acorn"
    title = "Sqrl Acorn"
    doc = "acorn.md"
    lock = str(check.LOCK)  # shared with fpgas-acorn-flash (spi_flash.py)
    tests = suite.TESTS  # each can be run on its own with --test

    def spot(self, host, usb, pci):
        return [d for d in map(check.describe, pci) if d]

    def weak(self, found):
        return found.get("kind") not in ("fpgas-online", "sqrl-factory")  # the Xilinx sample runs on a NeTV2 too

    def check(self, host, found, options):
        return suite.check_board(found, options)


BOARD = Acorn()
