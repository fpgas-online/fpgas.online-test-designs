#!/usr/bin/env python3
"""
Host-side UART test script.

Attaches to the UART test design's console and checks both directions of the UART now:

  1. the prompt   a newline is answered with the `litex>` prompt: the design receives and sends
  2. `ident`      the design answering is the UART test design for this board
  3. echo         every printable ASCII byte typed at the prompt comes back as itself

Nothing is read from what the design printed when it started: that output is gone before the Pi's own
UART is opened (the NeTV2, the Fomu), and is an old log on a USB UART (the Arty). The Arty, NeTV2 and Acorn
designs run the LiteX BIOS; the Fomu and TT FPGA designs run designs/_shared/ice40_firmware.py, which
answers a newline with its ident and the prompt as the BIOS's `ident` does. See designs/_host/bios_console.py.

The last line of output is the result for fpgas-verify: RESULT_JSON {"test": "uart", "result": ...}.

Usage:
    uv run python designs/uart/host/test_uart.py --port /dev/ttyUSB1
    uv run python designs/uart/host/test_uart.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import os
import sys

# In the repository the helper is in designs/_host; installed, it is beside this script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_host"))

import bios_console

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
ATTACH_TIMEOUT_S = 30  # the BIOS waits a few seconds for a serial boot before its first prompt

# What `ident` must contain: the design, and the board it was built for (SoCCore(ident=...)).
DESIGN_IDENT = "UART Test SoC"
BOARD_IDENT = {
    "arty": "Arty A7",
    "netv2": "NeTV2",
    "fomu": "Fomu EVT",
    "tt": "TT FPGA",
    "acorn": "Acorn",
}

# Printable ASCII. Control characters (0x00-0x1F, 0x7F) are left out: the BIOS acts on many of them
# (backspace, Ctrl-C, newline) instead of echoing them.
ECHO_TEST_BYTES = bytes(range(0x20, 0x7F))

# The BIOS's line buffer holds 64 characters and it rings the bell instead of echoing once it is full, so
# the bytes are typed as lines shorter than that. Each line is ended with a newline, which has to bring the
# prompt back (the BIOS says the line is no command; the iCE40 firmware prints its ident).
LINE_BYTES = 48


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #


def describe(wrong):
    """The first few bytes that did not echo, for the reason."""
    shown = [f"0x{sent:02X} came back as " + ("nothing" if got is None else f"0x{got:02X}") for sent, got in wrong[:4]]
    return ", ".join(shown) + (f" and {len(wrong) - 4} more" if len(wrong) > 4 else "")


def run_uart_test(bios, board, attach_timeout=ATTACH_TIMEOUT_S):
    """Run the test on an open console. Returns the result's fields ("result", "reason", ...)."""
    found = {"test": "uart", "board": board, "commands": []}

    def failed(reason):
        print(f"FAIL: {reason}")
        return {**found, "result": "fail", "reason": reason}

    try:
        bios.attach(attach_timeout)
    except bios_console.NoPrompt as e:
        return failed(f"{e}: nothing on the UART answers a newline with the litex> prompt")
    print("PASS: the design answers at its prompt")

    try:
        found["commands"].append("ident")
        found["ident"] = ident = bios.ident()
        name = BOARD_IDENT[board]
        if not ident or DESIGN_IDENT not in ident or name not in ident:
            return failed(f"the design on the UART is {ident!r}, not the {DESIGN_IDENT} for the {name}")
        print(f"PASS: {ident}")

        found["commands"].append("echo")
        wrong = []
        for start in range(0, len(ECHO_TEST_BYTES), LINE_BYTES):
            wrong += bios.echo(ECHO_TEST_BYTES[start : start + LINE_BYTES])
            bios.command("")  # end the line: the prompt has to come back
    except bios_console.NoPrompt as e:
        return failed(str(e))
    except OSError as e:  # the port went away (pyserial's SerialException is one)
        return failed(f"the UART failed during {found['commands'][-1]}: {e}")

    found["echo_bytes"] = len(ECHO_TEST_BYTES)
    found["echo_errors"] = len(wrong)
    if wrong:
        return failed(f"echo: {len(wrong)} of {len(ECHO_TEST_BYTES)} bytes did not come back: {describe(wrong)}")
    print(f"PASS: echo: all {len(ECHO_TEST_BYTES)} printable bytes came back")
    return {**found, "result": "pass"}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None):
    parser = argparse.ArgumentParser(description="UART echo test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(BOARD_IDENT),
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
        type=int,
        default=ATTACH_TIMEOUT_S,
        help=f"Seconds to wait for the prompt (default: {ATTACH_TIMEOUT_S})",
    )
    parser.add_argument(
        "--skip-banner",
        action="store_true",
        help="Accepted and ignored: the test never reads the banner, it asks the design for its ident",
    )
    args = parser.parse_args(argv)

    return bios_console.run_script(
        "uart",
        "UART test",
        args.board,
        args.port,
        args.baud,
        lambda bios: run_uart_test(bios, args.board, args.timeout),
    )


if __name__ == "__main__":
    sys.exit(main())
