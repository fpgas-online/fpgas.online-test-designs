#!/usr/bin/env python3
"""
Host-side UART test script.

Connects to the FPGA's serial port, waits for the LiteX BIOS banner,
then performs an echo test with printable ASCII bytes.

Usage:
    uv run python designs/uart/host/test_uart.py --port /dev/ttyUSB1
    uv run python designs/uart/host/test_uart.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import sys
import time

import serial


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
BOOT_TIMEOUT_S = 30
ECHO_TIMEOUT_S = 5

# The LiteX BIOS prints this string early in boot.
BIOS_BANNER_MARKER = "LiteX"

# Board-specific identification strings set via SoCCore(ident=...).
BOARD_IDENT = {
    "arty":  "Arty A7",
    "netv2": "NeTV2",
}

# Printable ASCII range for the echo test.  Control characters (0x00-0x1F,
# 0x7F) are excluded because the LiteX BIOS interprets many of them (e.g.
# backspace, Ctrl-C, newline) rather than echoing them verbatim.
ECHO_TEST_BYTES = bytes(range(0x20, 0x7F))


# --------------------------------------------------------------------------- #
# Test steps
# --------------------------------------------------------------------------- #

def wait_for_banner(ser: serial.Serial, board: str) -> tuple[bool, list[str]]:
    """Read lines until we see the BIOS ``litex>`` prompt or timeout.

    Returns (success, captured_lines).
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    found_bios = False
    found_ident = False
    expected_ident = BOARD_IDENT.get(board, "")

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        if BIOS_BANNER_MARKER in line:
            found_bios = True
        if expected_ident and expected_ident in line:
            found_ident = True

        # Once we see the BIOS prompt, boot is complete.
        if "litex>" in line:
            break

    if not found_bios:
        print("FAIL: BIOS banner not detected within timeout")
        return False, lines

    if expected_ident and not found_ident:
        print(f"FAIL: Board identification string '{expected_ident}' not found")
        return False, lines

    print("PASS: BIOS banner and board identification received")
    return True, lines


def echo_test(ser: serial.Serial) -> bool:
    """Send printable ASCII bytes one at a time and verify echo.

    The LiteX BIOS console echoes every printable character it receives.
    Control characters (0x00-0x1F, 0x7F) are excluded because the BIOS
    interprets them as commands rather than echoing them verbatim.
    """
    # Flush any pending input.
    ser.reset_input_buffer()
    time.sleep(0.1)

    errors = 0

    for byte_val in ECHO_TEST_BYTES:
        ser.write(bytes([byte_val]))
        response = ser.read(1)
        if len(response) == 0:
            print(f"  FAIL: Timeout waiting for echo of 0x{byte_val:02X}")
            errors += 1
        elif response[0] != byte_val:
            print(
                f"  FAIL: Echo mismatch for 0x{byte_val:02X}: "
                f"got 0x{response[0]:02X}"
            )
            errors += 1

    total = len(ECHO_TEST_BYTES)
    if errors == 0:
        print(f"PASS: Echo test — all {total} printable bytes echoed correctly")
        return True
    else:
        print(f"FAIL: Echo test — {errors}/{total} bytes failed")
        return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="UART echo test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(BOARD_IDENT.keys()),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--skip-banner",
        action="store_true",
        help="Skip waiting for BIOS banner (assume FPGA is already booted)",
    )
    args = parser.parse_args()

    print(f"Opening {args.port} at {args.baud} baud...")

    results: list[bool] = []

    with serial.Serial(args.port, args.baud, timeout=ECHO_TIMEOUT_S) as ser:
        # Step 1: Wait for BIOS banner
        if not args.skip_banner:
            passed, boot_lines = wait_for_banner(ser, args.board)
            results.append(passed)
            if not passed:
                print("\nBoot output captured:")
                for line in boot_lines:
                    print(f"  {line}")
        else:
            print("Skipping banner check (--skip-banner)")

        # Step 2: Printable-byte echo test
        passed = echo_test(ser)
        results.append(passed)

    # Summary
    print()
    if all(results):
        print("RESULT: PASS — UART test completed successfully")
        return 0
    else:
        print("RESULT: FAIL — UART test had failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
