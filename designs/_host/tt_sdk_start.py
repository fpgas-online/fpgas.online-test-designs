#!/usr/bin/env python3
"""Start the Tiny Tapeout SDK on a demo board and say whether it came up.

The SDK's own main.py builds the `tt` object when the board starts and ends by
printing `tt.sdk_version=<release>`. That start-up state is what `rpi-hwid
tinytapeout` reads to say what the board is. It is lost whenever something has
soft-reset the board from the raw REPL (mpremote does: a raw-REPL soft reset
does not run main.py), so before asking the board who it is, this script
soft-resets it from the friendly REPL, which runs boot.py and main.py again,
and waits for the SDK's last boot line.

Exit 0: the SDK started. Exit 1, with the reason: main.py is not the SDK's
(see tt_restore_sdk_main.py), the SDK's main.py raised or did not finish, or
nothing conclusive was seen in time. What the board printed is shown either way.

Usage (on the Pi, with fpgas-tt.service stopped):
    python3 tt_sdk_start.py /dev/ttyACM0 [--timeout 45]
"""

import argparse
import os
import re
import select
import sys
import time
import tty

STARTED = re.compile(r"^tt\.sdk_version=\S+\r?$", re.M)  # the SDK main.py's last boot line, once complete
SDK_BOOT = "BOOT: Tiny Tapeout SDK"  # its first (tt-micropython-firmware src/main.py)
REBOOTED = "soft reboot"  # MicroPython's own line on a friendly-REPL Ctrl-D
RESTORE = "restore it with tt_restore_sdk_main.py"


def verdict(text):
    """(started, reason) from what the board printed after the soft reset; (None, reason) while undecided."""
    if REBOOTED not in text:
        return None, "the board has not soft-reset yet"
    after = text.rpartition(REBOOTED)[2]
    whole_lines = after[: after.rfind("\n") + 1]  # a line still arriving is not judged
    line = STARTED.search(whole_lines)
    if line:
        return True, "the SDK started: " + line.group().strip()
    if not after.rstrip().endswith(">>>"):  # main.py is still running
        return None, "the SDK is still starting"
    if "Traceback" in after:
        raised = [ln.strip() for ln in after.partition("Traceback")[2].splitlines()[1:] if ln[:1] not in (" ", "")]
        return False, f"the board's main.py raised: {raised[0] if raised else 'an exception'}"
    if SDK_BOOT in after:
        return False, "the SDK's main.py ran to the prompt without finishing its start-up"
    return False, f"main.py ran to the prompt without starting the Tiny Tapeout SDK: it is not the SDK's ({RESTORE})"


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
                text += read_some(fd, 1.0).decode("utf-8", "replace")  # let main.py reach the prompt
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
        print(f"SDK_START: FAIL: {args.port} could not be opened or stopped answering: {e}")
        return 1
    for line in text.splitlines()[-12:]:
        print("  board: " + line.rstrip())
    print(f"SDK_START: {'OK' if started else 'FAIL'}: {reason}")
    return 0 if started else 1


if __name__ == "__main__":
    sys.exit(main())
