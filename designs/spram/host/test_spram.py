#!/usr/bin/env python3
"""
Host-side SPRAM test for the TT FPGA Demo Board (#343).

The SPRAM test design (designs/spram/gateware/spram_soc_tt.py) tests its iCE40UP5K's 128 KB of SPRAM each time it
receives a byte, and answers with one line: "SPRAM_TEST: PASS", or
"SPRAM_TEST: FAIL at 0x<address> read 0x<word> expected 0x<word>". This script asks it and judges the answer.
On the boot check it runs through tt_test_wrapper.py, which loads the design and bridges the FPGA's UART to a
PTY given here as --port.

Its last line starts "SPRAM:" and says the result. Exit 0: pass; 1: the SPRAM failed; 2: nothing was tested (the
port could not be opened, or the design did not answer).

Usage:
    python3 designs/spram/host/test_spram.py --port /dev/pts/3
"""

import argparse
import sys
import time

import serial

BAUD_RATE = 115200
# The design answers in about a second (its two passes over 32768 words at 12 MHz). It may still be starting
# when the first byte is sent, so the byte is sent again, at most ASKS times.
ASK_EVERY_S = 5
ASKS = 3
VERDICT = "SPRAM_TEST:"
SIZE_KB = 128


def ask(ser):
    """Send one byte and read lines until the design's verdict; returns (verdict or None, lines read, seconds from
    the last byte sent to the verdict or None)."""
    lines = []
    for _ in range(ASKS):
        ser.write(b"T")
        sent = time.monotonic()
        deadline = sent + ASK_EVERY_S
        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            lines.append(line)
            if line.startswith(VERDICT):
                return line[len(VERDICT) :].strip(), lines, time.monotonic() - sent
    return None, lines, None


def main() -> int:
    parser = argparse.ArgumentParser(description="SPRAM test for the TT FPGA Demo Board")
    parser.add_argument("--port", required=True, help="the FPGA's UART (on the boot check, the bridge's PTY)")
    parser.add_argument("--baud", type=int, default=BAUD_RATE, help=f"baud rate (default: {BAUD_RATE})")
    args = parser.parse_args()

    print(f"Opening {args.port} at {args.baud} baud...")
    try:
        with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
            ser.reset_input_buffer()
            verdict, lines, seconds = ask(ser)
    except serial.SerialException as e:
        print(f"SPRAM: could not open {args.port}: {e}: nothing was tested")
        return 2
    for line in lines:
        print(f"  {line}")
    if seconds is not None:  # what the test takes on the board, as the bridge delivers it
        print(f"answered {seconds:.1f} s after the byte that asked")
    if verdict is None:
        print(f"SPRAM: no answer from the SPRAM test design in {ASKS * ASK_EVERY_S} s: nothing was tested")
        return 2
    if verdict == "PASS":
        print(f"SPRAM: all {SIZE_KB} KB written and read back twice, each byte lane's write mask checked")
        return 0
    print(f"SPRAM: {verdict}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
