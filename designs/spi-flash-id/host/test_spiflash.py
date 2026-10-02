#!/usr/bin/env python3
"""
Host-side SPI Flash ID test script.

Attaches to the SPI flash test design's firmware (designs/_shared/ice40_firmware.py) over the UART and asks
it to read the flash's JEDEC ID now:

  1. the prompt   a newline is answered with the `litex>` prompt
  2. a newline    the firmware sends 0x9F to the flash again and prints its ident, the three ID bytes and
                  its own verdict; asked twice, and both readings have to agree

The verdict is on these readings, not on the one the firmware printed when the design started: that output
is gone before the Pi's own UART is opened (the NeTV2, the Fomu), and is an old log on a USB UART (the
Arty). See designs/_host/bios_console.py.

The last line of output is the result for fpgas-verify: RESULT_JSON {"test": "spiflash", "result": ...}.

Usage:
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyUSB1
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import os
import re
import sys

# In the repository the helper is in designs/_host; installed, it is beside this script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_host"))

import bios_console

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
ATTACH_TIMEOUT_S = 30
READ_TIMEOUT_S = 10  # one reading: about 100 characters and 40 bit-banged SPI clocks

# What the ident must contain: the design, and the board it was built for. `jedec` is the ID of the flash
# the board is known to carry (manufacturer, device type, capacity), None where boards differ.
DESIGN_IDENT = "SPI Flash Test SoC"
BOARDS = {
    "arty": {"ident": "Arty A7", "jedec": None},  # varies by board revision
    "netv2": {"ident": "NeTV2", "jedec": None},
    "fomu": {"ident": "Fomu EVT", "jedec": (0x1F, 0x86, 0x01)},  # AT25SF161: Adesto/Renesas, 16 Mbit
    "tt": {"ident": "TT FPGA", "jedec": None},
    "acorn": {"ident": "Acorn", "jedec": None},
}

# Common manufacturer names for reporting.
MANUFACTURER_NAMES = {
    0x01: "Spansion/Cypress/Infineon",
    0x20: "Micron/Numonyx/ST",
    0xC2: "Macronix (MXIC)",
    0xEF: "Winbond",
    0x1F: "Adesto/Atmel",
    0xBF: "SST/Microchip",
}

JEDEC_RE = re.compile(r"JEDEC_ID:\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})")
VERDICT_RE = re.compile(r"SPI_FLASH_TEST:\s+(PASS|FAIL)")
IDENT_RE = re.compile(r"Ident:\s*(.+)")
READINGS = 2


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def parse_reading(reply):
    """{"ident", "jedec", "verdict"} of one reading's lines; None for what the firmware did not print."""
    text = "\n".join(reply)
    ident, jedec, verdict = IDENT_RE.search(text), JEDEC_RE.search(text), VERDICT_RE.search(text)
    return {
        "ident": ident.group(1).strip() if ident else None,
        "jedec": tuple(int(b, 16) for b in jedec.groups()) if jedec else None,
        "verdict": verdict.group(1) if verdict else None,
    }


def rdid(jedec):
    return "".join(f"{b:02x}" for b in jedec)


def capacity_bytes(jedec):
    """The flash's size, where the third ID byte is its log2 (most manufacturers; not Adesto's 0x1F parts)."""
    return 2 ** jedec[2] if jedec[0] != 0x1F and 0x10 <= jedec[2] <= 0x20 else None


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #


def run_spiflash_test(bios, board, expected=None, attach_timeout=ATTACH_TIMEOUT_S):
    """Run the test on an open console. Returns the result's fields ("result", "reason", ...)."""
    found = {"test": "spiflash", "board": board, "commands": []}

    def failed(reason):
        print(f"FAIL: {reason}")
        return {**found, "result": "fail", "reason": reason}

    try:
        bios.attach(attach_timeout)
    except bios_console.NoPrompt as e:
        return failed(f"{e}: nothing on the UART answers a newline with the litex> prompt")
    print("PASS: the design answers at its prompt")

    readings = []
    try:
        for _ in range(READINGS):
            found["commands"].append("read")
            readings.append(parse_reading(bios.command("", READ_TIMEOUT_S)))
    except bios_console.NoPrompt as e:
        return failed(str(e))
    except OSError as e:  # the port went away (pyserial's SerialException is one)
        return failed(f"the UART failed during a reading: {e}")

    first = readings[0]
    found["ident"] = ident = first["ident"]
    name = BOARDS[board]["ident"]
    if not ident or DESIGN_IDENT not in ident or name not in ident:
        return failed(f"the design on the UART is {ident!r}, not the {DESIGN_IDENT} for the {name}")
    print(f"PASS: {ident}")

    jedec = first["jedec"]
    if jedec is None:
        return failed("the firmware printed no JEDEC_ID line")
    found["rdid"] = rdid(jedec)
    found["manufacturer"] = MANUFACTURER_NAMES.get(jedec[0], "unknown")
    size = capacity_bytes(jedec)
    if size:
        found["capacity_bytes"] = size
    print(f"JEDEC ID: 0x{jedec[0]:02X} 0x{jedec[1]:02X} 0x{jedec[2]:02X}")
    print(f"  Manufacturer: {found['manufacturer']} (0x{jedec[0]:02X})")
    print(f"  Device type:  0x{jedec[1]:02X}")
    print(f"  Capacity:     0x{jedec[2]:02X}" + (f" ({size // 1024} KiB)" if size else ""))

    faults = []
    if jedec in ((0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF)):
        faults.append(f"the ID is {found['rdid']}: no flash answered")
    if first["verdict"] != "PASS":
        faults.append(f"the firmware's verdict is {first['verdict'] or 'missing'}")
    others = sorted({rdid(r["jedec"]) if r["jedec"] else "nothing" for r in readings[1:]} - {found["rdid"]})
    if others:
        faults.append(f"the ID read again is {', '.join(others)}, not {found['rdid']}")
    if expected is None:
        expected = BOARDS[board]["jedec"]
    if expected is not None and jedec != tuple(expected):
        faults.append(f"the ID is {found['rdid']}, not the {rdid(expected)} expected for the {name}")

    if faults:
        for fault in faults:
            print(f"FAIL: {fault}")
        return {**found, "result": "fail", "reason": "; ".join(faults)}
    print(f"PASS: the flash answered {found['rdid']} on each of {READINGS} readings")
    if expected is not None:
        print(f"PASS: the ID is the one expected for the {name}")
    return {**found, "result": "pass"}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None):
    parser = argparse.ArgumentParser(description="SPI Flash ID test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(BOARDS),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=ATTACH_TIMEOUT_S,
        help=f"Seconds to wait for the prompt (default: {ATTACH_TIMEOUT_S}); longer when the port is opened "
        "before the design is loaded, as fpgas-verify's listen does",
    )
    parser.add_argument(
        "--expected-jedec",
        help="Expected JEDEC ID as hex string, e.g. '20BA18' for Micron 128Mbit",
    )
    args = parser.parse_args(argv)

    expected = None
    if args.expected_jedec:
        hex_str = args.expected_jedec.replace("0x", "").replace(" ", "")
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", hex_str):
            print(f"ERROR: --expected-jedec must be 6 hex digits, got '{args.expected_jedec}'")
            return 2
        expected = tuple(bytes.fromhex(hex_str))

    return bios_console.run_script(
        "spiflash",
        "SPI Flash ID test",
        args.board,
        args.port,
        args.baud,
        lambda bios: run_spiflash_test(bios, args.board, expected, args.timeout),
    )


if __name__ == "__main__":
    sys.exit(main())
