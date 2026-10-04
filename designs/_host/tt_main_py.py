#!/usr/bin/env python3
"""Say whether a Tiny Tapeout demo board's main.py is still the SDK's own.

Visitors have the board's Python prompt (the Commander's REPL tab), so a visitor
can change the board's files; nothing of ours does. This reads, and only reads:
the SDK release the board runs (`ttboard.VERSION`) and the SHA-256 of the
main.py on it, and compares that with the SHA-256 recorded here for that
release's src/main.py. A board whose main.py was replaced or edited then fails
its boot check with that reason, instead of passing unnoticed.

Exit 0: main.py is the SDK's own. Exit 1, with the reason: it is not, the
release is one no main.py is recorded for, or the board could not be read.

Usage (on the Pi, with fpgas-tt.service stopped):
    python3 tt_main_py.py /dev/ttyACM0
"""

import argparse
import subprocess
import sys

# SDK release (ttboard.VERSION, without a leading "v") -> SHA-256 of that release's src/main.py.
# 3.1.0: https://github.com/TinyTapeout/tt-micropython-firmware/blob/v3.1.0/src/main.py
# (tag v3.1.0 = 9e15305dadaed39697970fe753dfccd5b5cbd926, 3999 bytes), read 2026-10-04.
# A board upgraded to a release that is not here fails the check until its main.py is recorded.
MAIN_PY_SHA256 = {
    "3.1.0": "9ebe551a54715dd730261201ff4f21ad8ecbcd518b4809aa81675cca161e0cb4",
}
RESTORE = 'see "The SDK\'s main.py" in docs/hardware/tt-fpga.md'
# Run on the board. It reads two files and writes none.
READ = (
    "import hashlib, binascii, ttboard\n"
    "print('SDK_RELEASE', ttboard.VERSION)\n"
    "print('MAIN_SHA256', binascii.hexlify(hashlib.sha256(open('main.py', 'rb').read()).digest()).decode())\n"
)
TIMEOUT = 60


def read_board(port, timeout=TIMEOUT):
    """(returncode, stdout, stderr) of the read; mpremote hanging is 124, mpremote not installed 127."""
    try:
        p = subprocess.run(["mpremote", "connect", port, "exec", READ], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"mpremote did not finish within {timeout} s"
    except FileNotFoundError:
        return 127, "", "mpremote is not installed"
    return p.returncode, p.stdout, p.stderr


def verdict(rc, out, err):
    """(ok, reason) from what the read gave."""
    said = dict(line.split(None, 1) for line in out.splitlines() if line.startswith(("SDK_RELEASE ", "MAIN_SHA256 ")))
    if rc != 0 or set(said) != {"SDK_RELEASE", "MAIN_SHA256"}:
        why = " ".join((err.strip() or out.strip()).splitlines()[-2:]) or "it printed nothing"
        return False, f"the board's SDK release and main.py could not be read (exit {rc}): {why}"
    release, digest = said["SDK_RELEASE"].strip().lstrip("v"), said["MAIN_SHA256"].strip()
    if release not in MAIN_PY_SHA256:
        known = ", ".join(sorted(MAIN_PY_SHA256))
        return False, f"no main.py is recorded for SDK release {release} (recorded: {known}): add it to tt_main_py.py"
    if digest != MAIN_PY_SHA256[release]:
        return False, f"the board's main.py is not SDK {release}'s own (its SHA-256 is {digest}): {RESTORE}"
    return True, f"main.py is SDK {release}'s own"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    args = parser.parse_args(argv)
    ok, reason = verdict(*read_board(args.port))
    print(f"MAIN_PY: {'OK' if ok else 'FAIL'}: {reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
