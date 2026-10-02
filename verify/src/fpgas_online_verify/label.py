"""fpgas-verify --label: this host's rpi-hwid labels (the Pi's and its FPGA board's), made by rpi-hwid.

  1. read the identity, as --identify does (identify.py), each board under its own lock;
  2. with every lock released, write it to /run/fpgas-online/identity-<pid>.json;
  3. run `rpi-hwid labels --this-host [--out F] [--list]` with FPGAS_VERIFY_IDENTITY naming that file, so the
     fpgas-verify --identify rpi-hwid runs prints it and touches nothing (no lock is taken twice, no board is
     read twice, and rpi-hwid is never run again from inside);
  4. delete the file, whatever happened: an error, Ctrl-C, or a SIGTERM.

rpi-hwid is a soft dependency: it is found on PATH and run, never imported. Without it, --label exits 2 and
says how to install it. It also exits 2 when the identity file cannot be written: /run/fpgas-online is root's,
so --label runs as root. Otherwise the exit status is rpi-hwid's; a SIGTERM to --label itself exits 143.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import os
import pathlib
import shutil
import signal
import subprocess
import sys

from . import identify

IDENTITY_DIR = pathlib.Path("/run/fpgas-online")
TOOL = "rpi-hwid"
INSTALL = (
    "rpi-hwid is not installed: install python3-rpi-hwid (apt), or `uv tool install 'rpi-hwid[labels]'` "
    "(Python 3.11 or newer)"
)


def argv(tool, out=None, listing=False):
    """rpi-hwid's command for this host's labels."""
    return [tool, "labels", "--this-host", *(["--out", str(out)] if out else []), *(["--list"] if listing else [])]


def _terminated(signum, frame):
    """SIGTERM while the identity file exists: leave through the finally that deletes it."""
    raise SystemExit(128 + signum)


def _create(path, text):
    """Write `text` to a new file at `path`, readable by root alone; never through a link, never over a file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def run(options, out=None, listing=False, prog="fpgas-verify", boards=None, runner=subprocess.run):
    tool = shutil.which(TOOL)
    if tool is None:
        print(f"{prog} --label: {INSTALL}", file=sys.stderr)
        return 2
    doc, gaps = identify.read(options, boards)  # every board's lock is released when this returns
    for gap in gaps:
        print(f"{prog} --label: {gap}", file=sys.stderr)
    directory = pathlib.Path(options.get("identity_dir") or IDENTITY_DIR)
    path = directory / f"identity-{os.getpid()}.json"
    previous = signal.signal(signal.SIGTERM, _terminated)
    try:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _create(path, identify.dumps(doc))
        except FileExistsError:
            print(f"{prog} --label: {path} is already there (another run's, or not ours): not overwritten",
                  file=sys.stderr)  # fmt: skip
            return 2
        except OSError as e:
            print(f"{prog} --label: cannot write the identity for rpi-hwid to {path}: {e.strerror or e} "
                  "(run it as root)", file=sys.stderr)  # fmt: skip
            return 2
        try:
            return runner(argv(tool, out, listing), env={**os.environ, identify.ENV: str(path)}, check=False).returncode
        finally:
            path.unlink(missing_ok=True)
    finally:
        signal.signal(signal.SIGTERM, previous)
