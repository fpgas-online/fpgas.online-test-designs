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

# SDK release (ttboard.VERSION, without a leading "v") -> SHA-256 of that release's src/main.py: every release
# tag from v1.0.0 of https://github.com/TinyTapeout/tt-micropython-firmware (there is no v3.0.3), each read at
# its tag on 2026-10-05 (3.1.0 first on 2026-10-04: 3999 bytes). Releases that share a main.py share a hash.
# Only 3.1.0's has been compared with a board (2026-10-05); the others are the repository's file, and a board
# whose installed main.py differs from it fails here with its own hash in the reason.
# A board on a release that is not here fails the check until its main.py is recorded.
_MAIN_PY_RELEASES = {
    "cd90f2e24cf79e17a6397f28d57ea2d2df227d043e4fce656f1612e8989248f4": ("1.0.0", "1.1.0", "1.1.1"),
    "b7c5e0509847674318a4c7350d24f9efb0fa1d75f7b6399c6a03d71f3dd62ffc": ("1.2.0", "1.2.1", "1.2.2"),
    "8077a1d3f0584f1bfa51196fdfd96aac90a0aee3f9958b91a336f5f3118e72d3": ("2.0.0",),
    "072509b2c58b560174810f8fcb2091f8e4fa58c752febc06e5043559f9d41624": ("2.0.1", "2.0.2"),
    "61046bcccd22c79b6362d877b676e4d5493a5489933827ca81ac89ad18de9d3d": ("2.0.3",),
    "b4989604534cf4fe63f459b4da882d737cc6d9ad7bfab9bdb146f5372096423f": ("2.0.4",),
    "3e8a89152ceabaf973bbec9314ee7c7d44954aaae82065f3c79a460eb2827cea": ("3.0.0", "3.0.1"),
    "6b9893219c509047b0d7cabb6d41d69857381a1edc39a3ca5049941808a744e1": (
        "3.0.2", "3.0.4", "3.0.5", "3.0.6", "3.0.7", "3.0.8",
    ),
    "9ebe551a54715dd730261201ff4f21ad8ecbcd518b4809aa81675cca161e0cb4": ("3.1.0", "3.1.1"),
}  # fmt: skip
MAIN_PY_SHA256 = {release: digest for digest, releases in _MAIN_PY_RELEASES.items() for release in releases}
RESTORE = 'see "The SDK\'s main.py" in docs/hardware/tt-fpga.md'
# Run on the board. It reads and writes nothing: importing `ttboard` only finds the release (the SDK's
# src/ttboard/__init__.py sets VERSION from /VERSION's `version=` line in 3.x, and from the name of the
# /release_v<release> file in 1.x and 2.x; it does not build the board object), and main.py is read for its
# hash. On a demo board on 2026-10-05 `ttboard.VERSION` printed 3.1.0; no 1.x or 2.x board has been read.
READ = (
    "import hashlib, binascii, ttboard\n"
    "print('SDK_RELEASE', ttboard.VERSION)\n"
    "print('MAIN_SHA256', binascii.hexlify(hashlib.sha256(open('main.py', 'rb').read()).digest()).decode())\n"
)
TIMEOUT = 60


def _release_key(release):
    return tuple(int(part) for part in release.split("."))


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
    said = {}
    for line in out.splitlines():
        key, _, value = line.strip().partition(" ")
        if key in ("SDK_RELEASE", "MAIN_SHA256") and value.strip():  # a key with nothing after it is no answer
            said[key] = value.strip()
    if rc != 0 or set(said) != {"SDK_RELEASE", "MAIN_SHA256"}:
        why = " ".join((err.strip() or out.strip()).splitlines()[-2:]) or "it printed nothing"
        return False, f"the board's SDK release and main.py could not be read (exit {rc}): {why}"
    release, digest = said["SDK_RELEASE"].lstrip("v"), said["MAIN_SHA256"]
    if release not in MAIN_PY_SHA256:
        return False, (
            f"no main.py is recorded for SDK release {release} (recorded: 1.0.0 to "
            f"{max(MAIN_PY_SHA256, key=_release_key)}): add it to tt_main_py.py"
        )
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
