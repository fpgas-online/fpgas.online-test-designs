#!/usr/bin/env python3
"""Give a PCIe endpoint found by a sysfs rescan the Max_Payload_Size its root port runs.

The Pi 5 firmware boots Linux with `pci=pcie_bus_safe`. In that mode the kernel sets MPS once, at boot
(pcie_bus_configure_settings), and `echo 1 > /sys/bus/pci/rescan` does not repeat it: an FPGA reloaded over
JTAG comes back with DevCtl's reset MPS of 128 bytes while the root port stays at 512. The root port then
sends completions (and writes) of up to 512 bytes, which the endpoint must treat as malformed TLPs. A
7-series PCIe core drops them and sets FatalErr, so a LitePCIe DMA reader waits forever for its read data
(pi-sw2-p48, 2026-09-26: no descriptor ever completed, no MSI, endpoint DevSta FatalErr+).

This does what pcie_bus_safe would have done at boot, for one link: both ends get
min(root port's current MPS, endpoint's MPS Supported). Nothing is ever raised above what the root port
already runs; the root port is only lowered when the endpoint cannot reach its MPS. Only the MPS field of
Device Control is written. Run it as root after every rescan, and before a driver starts DMA.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.

    sudo python3 pcie_match_mps.py                 # the Acorn slot, 0001:01:00.0
    sudo python3 pcie_match_mps.py 0001:01:00.0
"""

import argparse
import os
import pathlib
import struct
import sys

PCI_STATUS, PCI_STATUS_CAP_LIST, PCI_CAPABILITY_LIST = 0x06, 0x10, 0x34
PCI_CAP_ID_EXP = 0x10
PCI_EXP_DEVCAP, PCI_EXP_DEVCTL = 0x04, 0x08
MPS_SHIFT, MPS_MASK = 5, 0x7 << 5  # DevCtl bits 7:5
MPSS_MASK = 0x7  # DevCap bits 2:0

DEFAULT_BDF = "0001:01:00.0"  # the M.2 slot the Acorn sits in on a Pi 5 (pcie1)


class NotPCIe(Exception):
    pass


def size(code):
    return 128 << code


class Function:
    """One PCI function's config space, through sysfs."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.bdf = self.path.name
        self.config = self.path / "config"
        self.cap = self._find_exp_cap()

    def _read(self, offset, fmt):
        with open(self.config, "rb") as f:
            f.seek(offset)
            return struct.unpack("<" + fmt, f.read(struct.calcsize(fmt)))[0]

    def _find_exp_cap(self):
        if not self._read(PCI_STATUS, "H") & PCI_STATUS_CAP_LIST:
            raise NotPCIe(f"{self.bdf}: no PCI Express capability (no capability list)")
        ptr, seen = self._read(PCI_CAPABILITY_LIST, "B") & ~3, set()
        while ptr and ptr not in seen:
            seen.add(ptr)
            if self._read(ptr, "B") == PCI_CAP_ID_EXP:
                return ptr
            ptr = self._read(ptr + 1, "B") & ~3
        raise NotPCIe(f"{self.bdf}: no PCI Express capability")

    @property
    def devctl(self):
        return self._read(self.cap + PCI_EXP_DEVCTL, "H")

    @property
    def mps(self):
        return (self.devctl & MPS_MASK) >> MPS_SHIFT

    @property
    def mpss(self):
        return self._read(self.cap + PCI_EXP_DEVCAP, "I") & MPSS_MASK

    def set_mps(self, code):
        value = (self.devctl & ~MPS_MASK) | (code << MPS_SHIFT)
        with open(self.config, "r+b") as f:
            f.seek(self.cap + PCI_EXP_DEVCTL)
            f.write(struct.pack("<H", value))


def match_mps(bdf=DEFAULT_BDF, sysfs_root="/sys"):
    """Match `bdf`'s MPS with its upstream port. Returns a one-line report; raises NotPCIe."""
    link = pathlib.Path(sysfs_root) / "bus" / "pci" / "devices" / bdf
    if not link.exists():
        return f"{bdf}: not present, nothing to match"
    ep = Function(os.path.realpath(link))
    port = Function(ep.path.parent)
    target = min(port.mps, ep.mpss)
    if ep.mps == target == port.mps:
        return f"{bdf}: MPS {size(target)} matches root port {port.bdf}"
    port_note = f"{size(port.mps)}"
    if port.mps != target:
        # Lower the port first, so the link never has a port that sends more than the endpoint accepts.
        port_note = f"{size(port.mps)} -> {size(target)}"
        port.set_mps(target)
    before = ep.mps
    ep.set_mps(target)
    return f"{bdf}: MPS {size(before)} -> {size(target)} (root port {port.bdf}: {port_note})"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bdf", nargs="*", default=[DEFAULT_BDF], help=f"PCI functions to match (default {DEFAULT_BDF})")
    ap.add_argument("--sysfs-root", default="/sys", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    status = 0
    for bdf in args.bdf:
        try:
            print(match_mps(bdf, args.sysfs_root))
        except (NotPCIe, OSError) as e:
            print(f"{bdf}: cannot match MPS: {e}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
