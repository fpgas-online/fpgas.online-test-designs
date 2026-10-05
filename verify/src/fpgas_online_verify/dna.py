"""The Xilinx 7-series device DNA: a 57-bit number fused into each FPGA, different on every chip.

`openFPGALoader --read-dna` reads it over JTAG with the FUSE_DNA instruction and prints
`{"dna": "0x<16 hex digits>"}`. It loads nothing and does not reconfigure the FPGA, so it is safe on a board
that is running a design. The instruction goes in through TDI, so a good DNA also shows that TDI works, which
an IDCODE read does not. openFPGALoader has --read-dna from 0.13.0; Debian bookworm's 0.10.0 does not.

A DNA of all zeros or all ones is a DNA port that is not being read, so it is no DNA (faults()).

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import re

BITS = 57
# openFPGALoader --read-dna's line: {"dna": "0x0054b48664b04854"}.
OPENFPGALOADER = re.compile(r"\bdna\"?\s*[:=]\s*\"?(0x[0-9a-fA-F]+)", re.IGNORECASE)


def parse(text):
    """The DNA in openFPGALoader --read-dna's output, as an int; None when it printed none."""
    m = OPENFPGALOADER.search(text or "")
    return int(m.group(1), 16) if m else None


def faults(dna, where):
    """What is wrong with a DNA read over `where`, as sentences: all zeros or all ones is no DNA."""
    if dna == 0 or dna == (1 << BITS) - 1:
        return [f"device DNA over {where} reads {dna:#x}: the DNA port is not being read"]
    return []
