#!/usr/bin/env python3
"""
Host-side DDR memory test script.

Captures UART output from the LiteX BIOS boot sequence and parses for:
  1. DRAM calibration results (read/write leveling)
  2. Memtest verdict ("Memtest OK" or "Memtest KO")

Usage:
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyUSB1
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import re
import sys
import time

import serial


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
BOOT_TIMEOUT_S = 60  # DDR calibration can take a while

# Expected DRAM sizes per board (bytes).
EXPECTED_DRAM_SIZE = {
    "arty":  256 * 1024 * 1024,  # 256 MB
    "netv2": 512 * 1024 * 1024,  # 512 MB
}


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #

def run_ddr_test(ser, board, timeout=BOOT_TIMEOUT_S):
    """Capture boot output and parse DDR test results.

    Returns (overall_pass, captured_lines).
    """
    lines = []
    deadline = time.monotonic() + timeout

    calibration_ok = False
    memtest_ok = None  # None = not seen, True = OK, False = KO
    memtest_line = ""

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        # Track calibration progress.
        if "Switching SDRAM to software control" in line:
            calibration_ok = True

        # Detect memtest result.
        if "Memtest OK" in line:
            memtest_ok = True
            memtest_line = line
            break
        elif "Memtest KO" in line:
            memtest_ok = False
            memtest_line = line
            break

        # Detect calibration failure.
        if re.search(r"(calibration|leveling).*(fail|error)", line, re.IGNORECASE):
            print("FAIL: DRAM calibration failed: {}".format(line))
            return False, lines

        # If we see the BIOS prompt without a memtest result, boot
        # completed but memtest was skipped or not run.
        if "litex>" in line:
            break

    # Report results.
    results = []

    if calibration_ok:
        print("PASS: DRAM calibration completed (SDRAM under software control)")
    else:
        print("FAIL: DRAM calibration not detected")
    results.append(calibration_ok)

    if memtest_ok is True:
        print("PASS: {}".format(memtest_line))
    elif memtest_ok is False:
        print("FAIL: {}".format(memtest_line))
    else:
        print("FAIL: Memtest result not detected within timeout")
    results.append(memtest_ok is True)

    return all(results), lines


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="DDR memory test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(EXPECTED_DRAM_SIZE.keys()),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help="Baud rate (default: {})".format(BAUD_RATE),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=BOOT_TIMEOUT_S,
        help="Boot timeout in seconds (default: {})".format(BOOT_TIMEOUT_S),
    )
    args = parser.parse_args()

    boot_timeout = args.timeout

    print("Opening {} at {} baud...".format(args.port, args.baud))
    print("Board: {}, expected DRAM: {} MB".format(
          args.board, EXPECTED_DRAM_SIZE[args.board] // (1024*1024)))
    print("Waiting up to {}s for boot + memtest...".format(boot_timeout))
    print()

    with serial.Serial(args.port, args.baud, timeout=2) as ser:
        passed, boot_lines = run_ddr_test(ser, args.board, timeout=boot_timeout)

    if not passed:
        print("\nFull boot output:")
        for line in boot_lines:
            print("  {}".format(line))

    print()
    if passed:
        print("RESULT: PASS — DDR memory test completed successfully")
        return 0
    else:
        print("RESULT: FAIL — DDR memory test had failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
