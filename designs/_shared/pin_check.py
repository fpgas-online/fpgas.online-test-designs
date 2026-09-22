"""Did every port end up on the package pin its constraint asked for?

Vivado lets a cell LOC win over a port LOC without failing the build. The
Xilinx 7-series PCIe IP ships an XDC that pins its lane-0 transceiver to one
GTP channel, so a x1 design constrained to the M.2 slot's lane-0 pins was
silently moved to another lane's pins and never linked (pi20, 2026-09-20).
Comparing the XDC with the placed design's I/O report catches that class of
mistake at build time, on any design.
"""

import pathlib
import re

# The port is either {braced}, which is how LiteX writes it and the only form that can hold a bus index, or bare.
_XDC_LOC = re.compile(r"^set_property\s+LOC\s+(\S+)\s+\[get_ports\s+(?:\{([^}]+)\}|([^\]\s{]+))\s*\]", re.M)


def requested_pins(xdc_text):
    """{port: package pin} from `set_property LOC <pin> [get_ports {<port>}]` lines."""
    return {(braced or bare).strip(): pin for pin, braced, bare in _XDC_LOC.findall(xdc_text)}


def placed_pins(io_report_text):
    """{port: package pin} from a Vivado `report_io` table (columns: Pin Number | Signal Name | ...)."""
    placed = {}
    for line in io_report_text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and cells[1] and cells[2] and cells[1] != "Pin Number":
            placed[cells[2]] = cells[1]
    return placed


def misplaced(xdc_text, io_report_text):
    """[(port, asked, got)] for every constrained port that is somewhere else, or nowhere."""
    placed = placed_pins(io_report_text)
    asked = requested_pins(xdc_text)
    return sorted((port, pin, placed.get(port)) for port, pin in asked.items() if placed.get(port) != pin)


def check_build(gateware_dir, build_name):
    gateware_dir = pathlib.Path(gateware_dir)
    xdc = (gateware_dir / f"{build_name}.xdc").read_text()
    wrong = misplaced(xdc, (gateware_dir / f"{build_name}_io.rpt").read_text())
    if wrong:
        lines = "\n".join(f"  {port}: constrained to {asked}, placed on {got}" for port, asked, got in wrong)
        raise SystemExit(f"{build_name}: ports not on the pins the XDC asked for:\n{lines}")
