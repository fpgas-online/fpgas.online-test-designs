"""Which board, or boards, this host verifies: `[verify] fpga-board = <board>|auto`.

Read from `*.ini` in the mode directory (/usr/share/fpgas-online/verify/mode.d, written by the one installed
mode package: fpgas-online-<board>, or fpgas-online-multi-board for `auto`) and then the admin's directory
(/etc/fpgas-verify), which wins. The mode packages' files are not conffiles, so swapping one mode package for
another leaves no stale file behind; the mode packages conflict, so there is only ever one of theirs.
"""

import configparser
import pathlib

from .core import Problem

MODE_DIR = pathlib.Path("/usr/share/fpgas-online/verify/mode.d")
ADMIN_DIR = pathlib.Path("/etc/fpgas-verify")
AUTO = "auto"
HOW_TO = (
    "install fpgas-online-<board> for the one board this host has, or fpgas-online-multi-board (or "
    "fpgas-online-all-boards) to find whichever board it has, or set `fpga-board` in /etc/fpgas-verify/*.ini"
)


def _setting(directory):
    """The directory's `fpga-board`, and the file it came from; two files that disagree are an error."""
    found = {}
    for path in sorted(pathlib.Path(directory).glob("*.ini")):
        parser = configparser.ConfigParser()
        try:
            parser.read(path)
        except configparser.Error as e:
            raise Problem("error", f"{path}: {e}") from None
        value = parser.get("verify", "fpga-board", fallback=None)
        if value is not None:
            found[path] = value.strip()
    if len(set(found.values())) > 1:
        which = ", ".join(f"{p} says {v!r}" for p, v in found.items())
        raise Problem("error", f"conflicting fpga-board settings: {which}")
    return next(((v, p) for p, v in found.items()), (None, None))


def configured(mode_dir=MODE_DIR, admin_dir=ADMIN_DIR):
    """(the board name or "auto", the file that says so). No setting anywhere is an error."""
    for directory in (admin_dir, mode_dir):
        value, path = _setting(directory)
        if value:
            return value, path
    raise Problem("error", f"no FPGA board is configured: {HOW_TO}")
