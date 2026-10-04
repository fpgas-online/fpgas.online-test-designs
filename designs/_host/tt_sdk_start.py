#!/usr/bin/env python3
"""Start the Tiny Tapeout SDK on a demo board and say whether it came up.

The SDK's own main.py builds the `tt` object when the board starts and ends by
printing `tt.sdk_version=<release>`. That start-up state is what `rpi-hwid
tinytapeout` reads to say what the board is. It is lost whenever something has
soft-reset the board from the raw REPL (mpremote does: a raw-REPL soft reset
does not run main.py), so before asking the board who it is, this script
soft-resets it from the friendly REPL, which runs boot.py and main.py again,
and waits for the SDK's last boot line.

Exit 0: the SDK started. Exit 1: main.py ran to the prompt without starting
the SDK (it is not the SDK's main.py: see tt_restore_sdk_main.py), or nothing
conclusive was seen in time. What the board printed is shown either way.

Usage (on the Pi, with fpgas-tt.service stopped):
    python3 tt_sdk_start.py /dev/ttyACM0 [--timeout 45]
"""

import argparse
import os
import select
import sys
import time
import tty

STARTED = "tt.sdk_version="  # the SDK main.py's last boot line (tt-micropython-firmware src/main.py)
REBOOTED = "soft reboot"  # MicroPython's own line on a friendly-REPL Ctrl-D
PROMPT = ">>> "


def verdict(text):
    """(started, reason) from what the board printed after the soft reset; (None, reason) while undecided."""
    after = text.rpartition(REBOOTED)[2] if REBOOTED in text else None
    if after is None:
        return None, "the board has not soft-reset yet"
    for line in after.splitlines():
        if line.startswith(STARTED):
            return True, "the SDK started: " + line.strip()
    if after.rstrip(" ").endswith(PROMPT.rstrip(" ")) or PROMPT in after:
        return False, ("main.py ran to the prompt without starting the Tiny Tapeout SDK: "
                       "it is not the SDK's main.py (restore it with tt_restore_sdk_main.py)")  # fmt: skip
    return None, "the SDK is still starting"


def read_some(fd, seconds):
    out = b""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            out += chunk
    return out


def start(port, timeout):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        tty.setraw(fd)
        os.write(fd, b"\r\x03\x03")  # stop whatever is running
        read_some(fd, 0.5)
        os.write(fd, b"\x02")  # leave the raw REPL, if it was in it
        read_some(fd, 0.5)
        os.write(fd, b"\x04")  # friendly REPL, empty line: soft reset, which runs main.py
        text = ""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            text += read_some(fd, 0.5).decode("utf-8", "replace")
            started, reason = verdict(text)
            if started is not None:
                return started, reason, text
        return False, f"{verdict(text)[1]} after {timeout} s", text
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args(argv)
    try:
        started, reason, text = start(args.port, args.timeout)
    except OSError as e:
        print(f"SDK_START: FAIL: cannot open {args.port}: {e}")
        return 1
    for line in text.splitlines()[-12:]:
        print("  board: " + line.rstrip())
    print(f"SDK_START: {'OK' if started else 'FAIL'}: {reason}")
    return 0 if started else 1


if __name__ == "__main__":
    sys.exit(main())
