#!/usr/bin/env python3
"""Summarise an openXC7 build from what nextpnr-xilinx left behind: timing, utilisation, where things went.

Reads <build name>_nextpnr.log and <build name>.fasm in a LiteX gateware directory and prints markdown:

- timing: each clock's maximum frequency after routing against what it was asked to make, with the slack;
- utilisation: every site type the design uses;
- placement: the transceiver cells and the ports nextpnr tied to a site;
- pull-ups: the pads with a pull-up in the bitstream.

    uv run --no-project python scripts/openxc7_build_report.py designs/acorn-pcie/build/acorn-cle-215+/gateware \\
        sqrl_acorn

It reports; it does not judge. A build that misses timing has already failed in nextpnr-xilinx (the
designs run it in strict mode), so a log that gets here is of a build that met every constraint it was given.
"""

import argparse
import pathlib
import re
import sys

_FMAX = re.compile(
    r"^(?:Info|Warning|ERROR): Max frequency for clock\s+'([^']+)': ([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)"
)
_UTILISATION = re.compile(r"^Info:\s+(\S+):\s*(\d+)/\s*(\d+)\s+(\d+)%")
_SITE = re.compile(r"^Info:\s+Constraining '([^']+)' to site '([^']+)'")
_PULLUP = re.compile(r"^(\S+)\.PULLTYPE\.PULLUP$")
_TRANSCEIVER_SITE = re.compile(r"^(GTPE2|GTXE2|IBUFDS_GTE2)")


def clocks(log_text):
    """[(clock, fmax MHz, target MHz, passed)] from the last timing report in the log: the routed design's."""
    blocks, block = [], []
    for line in log_text.splitlines():
        m = _FMAX.match(line)
        if m:
            block.append((m.group(1), float(m.group(2)), float(m.group(4)), m.group(3) == "PASS"))
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    return blocks[-1] if blocks else []


def slack_ns(fmax_mhz, target_mhz):
    """Setup slack: the period asked for less the period achieved."""
    return 1e3 / target_mhz - 1e3 / fmax_mhz


def utilisation(log_text):
    """[(site type, used, available, percent)] for every type in use, from the first utilisation table."""
    rows, started = [], False
    for line in log_text.splitlines():
        if line.startswith("Info: Device utilisation:"):
            if started:
                break
            started = True
            continue
        if started:
            m = _UTILISATION.match(line)
            if m and int(m.group(2)):
                rows.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
            elif rows and not line.startswith("Info:"):
                break
    return rows


def sites(log_text):
    """{cell or port: site} for everything nextpnr tied to a site by a constraint."""
    return {m.group(1): m.group(2) for m in map(_SITE.match, log_text.splitlines()) if m}


def pullups(fasm_text):
    """The pads (tile.IOB_Yn) that have a pull-up in the FASM."""
    return sorted(m.group(1) for m in map(_PULLUP.match, fasm_text.splitlines()) if m)


def report(log_text, fasm_text):
    out = ["### Timing (routed)", "", "| clock | max MHz | asked MHz | slack ns | |", "|---|---:|---:|---:|---|"]
    for name, fmax, target, passed in clocks(log_text):
        verdict = "met" if passed else "MISSED"
        out.append(f"| `{name}` | {fmax:.2f} | {target:.2f} | {slack_ns(fmax, target):+.3f} | {verdict} |")
    out += ["", "### Utilisation", "", "| site type | used | available | % |", "|---|---:|---:|---:|"]
    used_sites = utilisation(log_text)
    out += [f"| {kind} | {used} | {available} | {percent} |" for kind, used, available, percent in used_sites]
    placed = sites(log_text)
    out += ["", "### Transceiver placement", ""]
    out += [f"- `{cell}` on `{site}`" for cell, site in placed.items() if _TRANSCEIVER_SITE.match(site)]
    out += ["", "### Ports", ""]
    out += [f"- `{port}` on `{site}`" for port, site in placed.items() if not _TRANSCEIVER_SITE.match(site)]
    out += ["", "### Pads with a pull-up", ""]
    out += [f"- `{pad}`" for pad in pullups(fasm_text)] or ["- none"]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gateware_dir", type=pathlib.Path)
    parser.add_argument("build_name")
    args = parser.parse_args(argv)
    log = args.gateware_dir / f"{args.build_name}_nextpnr.log"
    fasm = args.gateware_dir / f"{args.build_name}.fasm"
    sys.stdout.write(report(log.read_text(errors="replace"), fasm.read_text()))


if __name__ == "__main__":
    main()
