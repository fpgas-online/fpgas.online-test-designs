"""fpgas-verify --label: this host's rpi-hwid labels (the Pi's and its FPGA board's), made by rpi-hwid.

  1. read the identity, as --identify does (identify.py), each board under its own lock;
  2. with every lock released, write it to /run/fpgas-online/identity-<pid>.json;
  3. run `rpi-hwid labels --this-host [--out F] [--list]` with FPGAS_VERIFY_IDENTITY naming that file, so the
     fpgas-verify --identify rpi-hwid runs prints it and touches nothing (no lock is taken twice, no board is
     read twice, and rpi-hwid is never run again from inside);
  4. delete the file, whatever happened.

rpi-hwid is a soft dependency: it is found on PATH and run, never imported. Without it, --label exits 2 and
says how to install it. The exit status is rpi-hwid's.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import contextlib
import os
import pathlib
import shutil
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


def run(options, out=None, listing=False, prog="fpgas-verify", boards=None, runner=subprocess.run):
    tool = shutil.which(TOOL)
    if tool is None:
        print(f"{prog} --label: {INSTALL}", file=sys.stderr)
        return 2
    doc, gaps = identify.read(options, boards)  # every board's lock is released when this returns
    for gap in gaps:
        print(f"{prog} --label: {gap}", file=sys.stderr)
    directory = pathlib.Path(options.get("identity_dir") or IDENTITY_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"identity-{os.getpid()}.json"
    try:
        path.write_text(identify.dumps(doc))
        return runner(argv(tool, out, listing), env={**os.environ, identify.ENV: str(path)}, check=False).returncode
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
