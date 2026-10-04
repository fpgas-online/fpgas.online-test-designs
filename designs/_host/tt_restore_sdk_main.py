#!/usr/bin/env python3
"""Put the Tiny Tapeout SDK's own main.py back on a demo board.

Until 2026-10 the test wrapper replaced the board's main.py with a no-op after
every bitstream upload, so the SDK never started and the board could not say
what it is (issue #117). This writes the SDK's main.py back.

It is not a guess at the file: you give it the main.py of the SDK release the
board runs, from that release's source (src/main.py at the release tag of
tt-micropython-firmware, or from the release's filesystem image), and it
refuses a file whose SHA-256 is not the one recorded here for that release.

Steps, each printed:
  1. read the SDK release from the board (`ttboard.VERSION`)
  2. check the given file's SHA-256 against MAIN_PY_SHA256 for that release
  3. show the main.py now on the board
  4. copy the file to the board as main.py (the only write) and read it back
  5. start the SDK (tt_sdk_start.py) and report whether it came up

Usage (on the Pi, as root, with fpgas-tt.service stopped):
    python3 tt_restore_sdk_main.py /dev/ttyACM0 /path/to/sdk-3.1.0-main.py [--dry-run]
"""

import argparse
import hashlib
import pathlib
import subprocess
import sys

# SDK release (ttboard.VERSION, without a leading "v") -> SHA-256 of that release's src/main.py.
# 3.1.0: https://github.com/TinyTapeout/tt-micropython-firmware/blob/v3.1.0/src/main.py
# (tag v3.1.0 = 9e15305dadaed39697970fe753dfccd5b5cbd926, 3999 bytes), read 2026-10-04.
MAIN_PY_SHA256 = {
    "3.1.0": "9ebe551a54715dd730261201ff4f21ad8ecbcd518b4809aa81675cca161e0cb4",
}
HERE = pathlib.Path(__file__).resolve().parent
# Run on the board: the SHA-256 of the main.py now on it.
READ_BACK = (
    "import hashlib, binascii\nprint(binascii.hexlify(hashlib.sha256(open('main.py', 'rb').read()).digest()).decode())"
)


def mpremote(port, *args, timeout=60):
    p = subprocess.run(["mpremote", "connect", port, *args], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def release(text):
    """The SDK release in what `print(ttboard.VERSION)` printed, without a leading "v"; None if there is none."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1].removeprefix("v") if lines else None


def check_file(path, sdk):
    """None when `path` is the main.py recorded for SDK release `sdk`; otherwise why not."""
    if sdk not in MAIN_PY_SHA256:
        return f"no main.py is recorded for SDK release {sdk!r} (known: {', '.join(sorted(MAIN_PY_SHA256))})"
    digest = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    if digest != MAIN_PY_SHA256[sdk]:
        return f"{path} is not SDK {sdk}'s main.py: its SHA-256 is {digest}, not {MAIN_PY_SHA256[sdk]}"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    parser.add_argument("main_py", help="main.py from the source of the SDK release the board runs")
    parser.add_argument("--dry-run", action="store_true", help="check everything, write nothing")
    args = parser.parse_args(argv)

    rc, out, err = mpremote(args.port, "exec", "import ttboard\nprint(ttboard.VERSION)")
    sdk = release(out) if rc == 0 else None
    if not sdk:
        print(f"RESTORE: FAIL: the board did not say which SDK release it runs: {(out + err).strip()[-300:]}")
        return 1
    print(f"board runs Tiny Tapeout SDK {sdk}")

    why_not = check_file(args.main_py, sdk)
    if why_not:
        print(f"RESTORE: FAIL: {why_not}")
        return 1
    print(f"{args.main_py} is SDK {sdk}'s main.py (SHA-256 matches)")

    rc, out, err = mpremote(args.port, "exec", "print(open('main.py').read())")
    print("main.py on the board now:")
    for line in (out if rc == 0 else f"(could not be read: {err.strip()[-200:]})").splitlines()[:12]:
        print("  | " + line)

    if args.dry_run:
        print("RESTORE: dry run, nothing written")
        return 0

    rc, out, err = mpremote(args.port, "cp", args.main_py, ":main.py", timeout=120)
    if rc != 0:
        print(f"RESTORE: FAIL: copying main.py to the board failed, and main.py there may now be incomplete: "
              f"{(out + err).strip()[-300:]}")  # fmt: skip
        return 1
    rc, out, err = mpremote(args.port, "exec", READ_BACK)
    on_board = out.strip().splitlines()[-1] if rc == 0 and out.strip() else None
    if on_board != MAIN_PY_SHA256[sdk]:
        print(f"RESTORE: FAIL: main.py on the board does not read back as written (SHA-256 {on_board}): "
              f"run this again before the board is restarted {err.strip()[-200:]}")  # fmt: skip
        return 1
    print("main.py written and read back")

    started = subprocess.run([sys.executable, str(HERE / "tt_sdk_start.py"), args.port], check=False).returncode
    print(
        "RESTORE: " + ("OK: the SDK starts" if started == 0 else "FAIL: main.py is written but the SDK did not start")
    )
    return started


if __name__ == "__main__":
    sys.exit(main())
