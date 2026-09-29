"""Sqrl Acorn CLE-215+ / CLE-101 (and NiteFury/LiteFury): found on PCI, checked over BAR0 (check.py).

Every Xilinx or SQRL PCIe endpoint is claimed. The Acorn-family images are recognised: the fpgas.online SoC
(10ee:7021 with our subsystem IDs), SQRL's factory image and the vendor XDMA sample. Anything else (an older
build of ours without the subsystem IDs, 10ee:7021 subsystem 10ee:0007, or another design) fails as "not a
design we built": an FPGA is plainly there, so reporting no board at all would hide it (pi-sw2-p37, 2026-09-27).

A board whose variant is known also has its links to the Pi checked (links.py): P1 JTAG, and, when our SoC
runs, the P2 UART. A failure there fails the board: its PCIe side may be fine, but it cannot be loaded or
talked to the way users are told it can.

spi_flash.py (fpgas-acorn-flash) is the operator's tool for the same flash, and shares the lock.
"""

from ...board import Board
from ...core import Problem, run
from . import check, links


class Acorn(Board):
    name = slug = "acorn"
    title = "Sqrl Acorn"
    doc = "acorn.md"
    lock = str(check.LOCK)  # shared with fpgas-acorn-flash (spi_flash.py)

    def spot(self, host, usb, pci):
        return [d for d in map(check.describe, pci) if d]

    def weak(self, found):
        return found.get("kind") not in ("fpgas-online", "sqrl-factory")  # the Xilinx sample runs on a NeTV2 too

    def check(self, host, found, options):
        images = options.get("images") or check.IMAGES
        try:
            release = check.load_release(images) if found["kind"] == "fpgas-online" else None
        except Problem as p:
            return {"board": self.name, "found": found, "variant": found["variant"], "result": p.result,
                    "reason": p.reason}  # fmt: skip
        board = check.check_board(found, images, release, options.get("open_bar", check.open_bar0))
        report = {"board": self.name, "found": found, "variant": found["variant"], **board}
        if found["variant"]:  # a board we can name: its P1 JTAG and, running our SoC, its P2 UART (links.py)
            tests = [links.jtag(found["variant"], options.get("run", run))]
            identifier = board.get("running", {}).get("identifier")
            if identifier and board["result"] in ("pass", "degraded"):
                tests.append(links.p2_uart(identifier, options.get("uart_opener")))
            report["tests"] = tests
            failed = [t for t in tests if t["result"] != "pass"]
            if failed and check.SEVERITY.index("fail") > check.SEVERITY.index(report["result"]):
                report["result"], report["reason"] = "fail", failed[0].get("reason", f"{failed[0]['test']} failed")
        if release:
            report["bitstreams"] = release[0].get("tag")
        state = {"bdf": found["bdf"], "ids": found["ids"], "subsystem": found["subsystem"]}
        if found["variant"]:
            state["variant"] = found["variant"]
        if "flash" in board:
            flash = board["flash"]
            state["flash"] = {k: flash[k] for k in ("part", "jedec", "unique_id") if k in flash}
            state["flash"]["slots"] = {s["slot"]: s["sha256"] for s in flash.get("slots", []) if "sha256" in s}
        report["state"] = state
        return report


BOARD = Acorn()
