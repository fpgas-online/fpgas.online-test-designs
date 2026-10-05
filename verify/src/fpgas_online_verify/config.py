"""Which board, or boards, this host verifies: `[verify] fpga-board = <board>|auto`; whether the result is
sent to the fleet: `[verify] publish = on|off`; and whether the opt-in power-cycle check is on: `[verify]
power-cycle-check = on|off`.

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


def _setting(directory, key="fpga-board"):
    """The directory's `key`, and the file it came from; two files that disagree are an error."""
    found = {}
    for path in sorted(pathlib.Path(directory).glob("*.ini")):
        parser = configparser.ConfigParser()
        try:
            parser.read(path)
        except configparser.Error as e:
            raise Problem("error", f"{path}: {e}") from None
        value = parser.get("verify", key, fallback=None)
        if value is not None:
            found[path] = value.strip()
    if len(set(found.values())) > 1:
        which = ", ".join(f"{p} says {v!r}" for p, v in found.items())
        raise Problem("error", f"conflicting {key} settings: {which}")
    return next(((v, p) for p, v in found.items()), (None, None))


def configured(mode_dir=MODE_DIR, admin_dir=ADMIN_DIR):
    """(the board name or "auto", the file that says so). No setting anywhere is an error."""
    for directory in (admin_dir, mode_dir):
        value, path = _setting(directory)
        if value:
            return value, path
    raise Problem("error", f"no FPGA board is configured: {HOW_TO}")


POWER_CYCLE_CHECK = "power-cycle-check"
ON, OFF = ("on", "yes", "true", "1"), ("off", "no", "false", "0")


def power_cycle_check(mode_dir=MODE_DIR, admin_dir=ADMIN_DIR):
    """(whether the opt-in power-cycle check is on, the file that says so or None): `[verify] power-cycle-check
    = on|off` in the same files as `fpga-board`, the admin's directory first. Off when no file says.

    The check fails a board whose FPGA has not restarted since the last check, that is, one that did not
    restart with its Pi. That only makes sense where a restart of the host is known to restart the card, as on
    the fpgas.online fleet, whose root turns it on in /etc/fpgas-verify; elsewhere it stays off."""
    return _switch(POWER_CYCLE_CHECK, mode_dir, admin_dir)


PUBLISH = "publish"


def publish(mode_dir=MODE_DIR, admin_dir=ADMIN_DIR):
    """(whether the check tells the fleet how it went, the file that says so or None): `[verify] publish =
    on|off` in the same files as `fpga-board`, the admin's directory first. Off when no file says.

    Publishing is for the fpgas.online fleet, whose Pi root turns it on in /etc/fpgas-verify: its site lists a
    board by what the boot check reported. Anywhere else there is nobody to tell, so a host that only has the
    packages sends nothing, at boot or by hand."""
    return _switch(PUBLISH, mode_dir, admin_dir)


def _switch(key, mode_dir, admin_dir):
    """(on, the file that says so or None) for an on/off setting; a value that is neither is an error."""
    for directory in (admin_dir, mode_dir):
        value, path = _setting(directory, key)
        if value is None:
            continue
        if value.lower() not in (*ON, *OFF):
            raise Problem("error", f"{path}: {key} is {value!r}; it is `on` or `off`")
        return value.lower() in ON, path
    return False, None
