"""Sqrl Acorn CLE-215+ / CLE-101 (and NiteFury/LiteFury): found on PCI, checked over BAR0 (check.py).

Every Xilinx or SQRL PCIe endpoint is claimed. The Acorn-family images are recognised: the fpgas.online SoC
(10ee:7021 with our subsystem IDs), SQRL's factory image and the vendor XDMA sample. Anything else (an older
build of ours without the subsystem IDs, 10ee:7021 subsystem 10ee:0007, or another design) fails as "not a
design we built": an FPGA is plainly there, so reporting no board at all would hide it (pi-sw2-p37, 2026-09-27).

spi_flash.py (fpgas-acorn-flash) is the operator's tool for the same flash, and shares the lock.
"""

from ...board import Board
from ...core import Problem
from . import check


class Acorn(Board):
    name = slug = "acorn"
    title = "Sqrl Acorn"
    doc = "acorn.md"
    lock = str(check.LOCK)  # shared with fpgas-acorn-flash (spi_flash.py)

    def spot(self, host, usb, pci):
        return [d for d in map(check.describe, pci) if d]

    def check(self, host, found, options):
        images = options.get("images") or check.IMAGES
        try:
            release = check.load_release(images) if found["kind"] == "fpgas-online" else None
        except Problem as p:
            return {"board": self.name, "found": found, "variant": found["variant"], "result": p.result,
                    "reason": p.reason}  # fmt: skip
        board = check.check_board(found, images, release, options.get("open_bar", check.open_bar0))
        report = {"board": self.name, "found": found, "variant": found["variant"], **board}
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
