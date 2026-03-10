#!/usr/bin/env python3
"""
Host-side SPI Flash ID test script.

Captures UART output from the FPGA and looks for the JEDEC ID
printed by the custom firmware or by the LiteX BIOS.

Two modes of operation:
  1. Custom firmware mode (default): Looks for "JEDEC_ID:" and
     "SPI_FLASH_TEST: PASS/FAIL" lines.
  2. BIOS mode (--bios): Parses the BIOS boot output for SPI flash
     identification messages.

Usage:
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyUSB1
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyAMA0 --board netv2
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
BOOT_TIMEOUT_S = 30

# Known-good JEDEC IDs per board (to be filled in after initial runs).
# Format: (manufacturer, device_type, capacity)
# Set to None to skip validation — only check for non-zero/non-FF.
EXPECTED_JEDEC_IDS: dict[str, tuple[int, int, int] | None] = {
    "arty":  None,  # TBD — varies by board revision
    "netv2": None,  # TBD — to be determined
    "fomu":  (0x1F, 0x86, 0x01),  # AT25SF161: Adesto/Renesas, 16 Mbit
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


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #

def run_firmware_mode(ser: serial.Serial, board: str,
                      expected_ids: dict[str, tuple[int, int, int] | None] | None = None) -> tuple[bool, list[str]]:
    """Parse output from custom JEDEC ID firmware.

    Looks for lines:
        JEDEC_ID: 0xMM 0xTT 0xCC
        SPI_FLASH_TEST: PASS
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S

    jedec_id = None
    test_result = None

    jedec_re = re.compile(r"JEDEC_ID:\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})")
    result_re = re.compile(r"SPI_FLASH_TEST:\s+(PASS|FAIL)")

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        m = jedec_re.search(line)
        if m:
            jedec_id = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))

        m = result_re.search(line)
        if m:
            test_result = m.group(1)

        if "Test Complete" in line:
            break

    # Report.
    if jedec_id is None:
        print("FAIL: JEDEC ID not found in firmware output")
        return False, lines

    mfr, dtype, cap = jedec_id
    mfr_name = MANUFACTURER_NAMES.get(mfr, "Unknown")
    cap_bytes = 2 ** cap if cap else 0
    if cap_bytes >= 1024 * 1024:
        cap_str = f"{cap_bytes // (1024 * 1024)} MB"
    elif cap_bytes >= 1024:
        cap_str = f"{cap_bytes // 1024} KB"
    else:
        cap_str = f"{cap_bytes} B"
    print(f"JEDEC ID: 0x{mfr:02X} 0x{dtype:02X} 0x{cap:02X}")
    print(f"  Manufacturer: {mfr_name} (0x{mfr:02X})")
    print(f"  Device type:  0x{dtype:02X}")
    print(f"  Capacity:     0x{cap:02X} ({cap_str})")

    results: list[bool] = []

    # Check firmware's own verdict.
    if test_result == "PASS":
        print("PASS: Firmware reported SPI flash test passed")
        results.append(True)
    elif test_result == "FAIL":
        print("FAIL: Firmware reported SPI flash test failed")
        results.append(False)
    else:
        print("FAIL: Firmware test result not found in output")
        results.append(False)

    # Optionally compare against expected JEDEC ID.
    ids = expected_ids if expected_ids is not None else EXPECTED_JEDEC_IDS
    expected = ids.get(board)
    if expected is not None:
        if jedec_id == expected:
            print(f"PASS: JEDEC ID matches expected value for {board}")
            results.append(True)
        else:
            exp_str = " ".join(f"0x{b:02X}" for b in expected)
            got_str = " ".join(f"0x{b:02X}" for b in jedec_id)
            print(f"FAIL: JEDEC ID mismatch — expected {exp_str}, got {got_str}")
            results.append(False)

    return all(results), lines


def run_bios_mode(ser: serial.Serial, board: str) -> tuple[bool, list[str]]:
    """Parse SPI flash info from standard LiteX BIOS boot output.

    The BIOS prints flash identification during boot, e.g.:
        Initializing SPI Flash @0x...
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S

    spi_detected = False

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        if "SPI" in line.upper() and "flash" in line.lower():
            spi_detected = True
            print(f"  SPI Flash detected: {line}")

        if "litex>" in line:
            break

    if spi_detected:
        print("PASS: SPI flash detected during BIOS boot")
        return True, lines
    else:
        print("FAIL: No SPI flash detection in BIOS output")
        return False, lines


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="SPI Flash ID test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(EXPECTED_JEDEC_IDS.keys()),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--bios",
        action="store_true",
        help="Use BIOS mode (parse standard BIOS output instead of custom firmware)",
    )
    parser.add_argument(
        "--expected-jedec",
        help="Expected JEDEC ID as hex string, e.g. '20BA18' for Micron 128Mbit",
    )
    args = parser.parse_args()

    # Build a local copy of expected IDs so we don't mutate the module constant.
    expected_ids = dict(EXPECTED_JEDEC_IDS)

    if args.expected_jedec:
        hex_str = args.expected_jedec.replace("0x", "").replace(" ", "")
        if len(hex_str) != 6:
            print(f"ERROR: --expected-jedec must be 6 hex digits, got '{args.expected_jedec}'")
            return 2
        expected_ids[args.board] = (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
        )

    print(f"Opening {args.port} at {args.baud} baud...")
    print(f"Board: {args.board}")
    print(f"Mode: {'BIOS' if args.bios else 'Custom firmware'}")
    print()

    with serial.Serial(args.port, args.baud, timeout=2) as ser:
        if args.bios:
            passed, boot_lines = run_bios_mode(ser, args.board)
        else:
            passed, boot_lines = run_firmware_mode(ser, args.board, expected_ids)

    if not passed:
        print("\nFull output:")
        for line in boot_lines:
            print(f"  {line}")

    print()
    if passed:
        print("RESULT: PASS — SPI Flash ID test completed successfully")
        return 0
    else:
        print("RESULT: FAIL — SPI Flash ID test had failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
