"""JTAG IDCODEs: reading the whole 32-bit value, and what its fields say.

An IDCODE (IEEE 1149.1) is 32 bits, reported as these fields:

  bits 31:28  idcode_version          the silicon revision; differs between chips of the same part
  bits 27:12  idcode_part_number      the part, as its manufacturer numbers it
  bits 11:1   idcode_manufacturer_id  the JEP106 code: continuation-code count (bank) in 11:8, ID in 7:1
  bit  0      always 1                a device with no IDCODE answers BYPASS, a single 0

openFPGALoader's `--detect` prints the IDCODE it found in its own part table, and most of that table is keyed
by the IDCODE with the version masked off: an XC7A200T that answers 0x13636093 is printed as
`idcode 0x3636093`. Its raw scan, printed with `--verbose-level 2` as `- 0 -> 0x13636093`, is the whole value,
so that is what is read here. OpenOCD's `tap/device found: 0x13636093` is the whole value too.

The part is compared without the version, so a board with another silicon revision of the right part passes;
the version is reported.
"""

import re

VERSION_MASK = 0x0FFFFFFF  # everything but the version
# openFPGALoader --detect --verbose-level 2: "- 0 -> 0x13636093" per device, then 0xffffffff past the end.
OPENFPGALOADER_RAW = re.compile(r"^- \d+ -> (0x[0-9a-fA-F]{8})\s*$", re.MULTILINE)
# OpenOCD: "Info : JTAG tap: xc7.tap tap/device found: 0x13631093 (mfg: 0x049 (Xilinx), ...)".
OPENOCD = re.compile(r"tap/device found:\s*(0x[0-9a-fA-F]{1,8})")
# Asks openFPGALoader to print its raw scan (Jtag::detectChain prints it when the level is above 1).
OPENFPGALOADER_RAW_ARGS = ("--verbose-level", "2")

# JEP106 codes, as bits 11:1 of an IDCODE (bank in the top four bits), as openFPGALoader's src/part.hpp has them.
MANUFACTURERS = {0x021: "Lattice", 0x049: "Xilinx", 0x06E: "Altera"}
# Devices by IDCODE with the version masked off.
DEVICES = {
    0x0362E093: "XC7A15T",
    0x0362D093: "XC7A35T",
    0x0362C093: "XC7A50T",
    0x03632093: "XC7A75T",
    0x03631093: "XC7A100T",
    0x03636093: "XC7A200T",
}


def parse(text):
    """The whole IDCODEs in openFPGALoader's raw scan or OpenOCD's output, in chain order. The all-ones word
    past the end of the chain, and the all-zeros of a stuck TDO, are not devices."""
    codes = [int(x, 16) for x in OPENFPGALOADER_RAW.findall(text) + OPENOCD.findall(text)]
    return [c for c in codes if c not in (0, 0xFFFFFFFF)]


def scan_lines(text):
    """The lines of the output that hold whole IDCODEs, for a report's output: openFPGALoader's part table,
    which follows its raw scan, prints them masked."""
    return [line.strip() for line in text.splitlines() if OPENFPGALOADER_RAW.match(line) or OPENOCD.search(line)]


def masked(code):
    """The IDCODE without its version: the part, whatever its silicon revision."""
    return code & VERSION_MASK


def same_part(code, expected):
    return masked(code) == masked(expected)


def device(code):
    """The device's name, or None for a part not in DEVICES."""
    return DEVICES.get(masked(code))


def decode(code):
    """The report's fields for one IDCODE."""
    mfg = code >> 1 & 0x7FF
    return {
        "idcode": f"{code:#010x}",
        "idcode_version": code >> 28,
        "idcode_part_number": f"{code >> 12 & 0xFFFF:#06x}",
        "idcode_manufacturer_id": f"{mfg:#05x}",
        "idcode_manufacturer": MANUFACTURERS.get(mfg, "unknown"),
        "idcode_device": device(code) or "unknown",
    }


def faults(code):
    """What is wrong with the IDCODE as an IDCODE, as sentences."""
    if code & 1:
        return []
    return [f"IDCODE {code:#010x} has bit 0 clear, which no IDCODE has"]
