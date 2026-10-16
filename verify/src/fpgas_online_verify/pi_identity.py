"""The Pi's own facts for its label, read at boot by rpi-hwid and sent to the site as `pi-identified` (#76).

rpi-hwid's LABEL-CONTRACT.md, section 5: fpgas-verify runs `rpi-hwid label-input --pi-only` once at boot, before it
takes any board's lock, and sends the summary as `pi-identified` (`schema=pi-identity/1`), encoded as section 3
says (identity.detail): a field not read is left out, a scalar read as none is "-", a list is one key of compact
sorted JSON, a list read empty is "[]". `--pi-only` reads the HAT on the ID bus (GPIO0/1) and /proc/device-tree/hat,
the MACs, the USB network adapters, the power class and, on a Pi 5, the fan, the RTC battery and the PMIC's
readings; it never touches GPIO2/3 or a board (the `--user-bus` scan waits for each setup's wiring to say it is
safe: the contract's gap 2).

Without it the site has no Pi label: Tim, 16 Oct 2026 (coord-74), "Why are there no RPi labels on
https://welland.fpgas.online/fleet/55effc3376226b41/".

Only the fields the site reads from the event are sent (fpgas.online-site fleet/hwid.py PI_FIELDS): model, serial,
revision and memory come from the Pi's registration. rpi-hwid not installed is `reader=none`, as the contract
says; rpi-hwid installed and failing, or printing what is not a label input, is `reader_error=<why>`: the site
refuses the Pi's own label and shows why, and a Pi label is never made from half a read. The boards' result is
untouched (the coordinator's decision of 17 Oct 2026, from Tim's rules of 5 and 16 Oct 2026).
"""

import json
import math
import shutil
import subprocess

from . import identity
from .core import Problem

TOOL = "rpi-hwid"
ARGV = (TOOL, "label-input", "--pi-only")
SCHEMA = "pi-identity/1"
TIMEOUT = 120  # the whole --pi-only read: the HAT EEPROM over GPIO0/1 (rpi-hwid #92), vcgencmd, sysfs
KILL_REAP_S = 5  # how long a killed rpi-hwid is given to exit
# rpi-hwid's Summary fields the site takes from this event (fpgas.online-site fleet/hwid.py PI_FIELDS), in its order
FIELDS = ("compatible", "power_class", "hat_uuid", "fan", "rtc_battery", "max_current_ma", "ext5v_v",
          "header", "macs", "usb_net")  # fmt: skip
LISTS = ("header", "macs", "usb_net")
# A reason is cut to this many characters, keeping its end, where the cause is ("… exited 1: <what rpi-hwid said>"),
# as checks.FIT keeps the fleet pages' per-test reasons; the site shows a reader_error whole up to its own limit.
REASON_MAX = 300


class Unread(Exception):
    """rpi-hwid ran and did not give the Pi's facts: the reason."""


def facts(document):
    """{field: value} of FIELDS from a `--pi-only` label input document. A document that is not one (another
    schema or version, no summary, a field of the wrong kind) raises Unread: nothing is sent from it."""
    if not isinstance(document, dict) or document.get("schema") != "rpi-hwid/label-input":
        raise Unread(f"{' '.join(ARGV)} printed no rpi-hwid/label-input document")
    if document.get("version") != 1 or isinstance(document.get("version"), bool):
        raise Unread(f"{' '.join(ARGV)} printed label input version {document.get('version')!r}, not 1")
    summary = document.get("summary")
    if not isinstance(summary, dict):
        raise Unread(f"{' '.join(ARGV)} printed a label input with no summary")
    out = {}
    for field in FIELDS:
        if field not in summary:
            continue  # not in rpi-hwid's summary: not read
        value = summary[field]
        if field in LISTS and value is not None and not isinstance(value, list):
            raise Unread(f"{' '.join(ARGV)} gave {field} as {type(value).__name__}, not a list")
        if field in LISTS and value is None:
            continue  # a list nobody read is left out (contract section 3), never "-"
        if isinstance(value, float) and not math.isfinite(value):
            raise Unread(f"{' '.join(ARGV)} gave {field} as {value!r}")
        out[field] = value
    return out


def details(read):
    """The `pi-identified` event's details for `read` (read(): {"reader": ..., "facts" or "reader_error"})."""
    out = {"schema": SCHEMA, "reader": read["reader"]}
    if "reader_error" in read:
        why = read["reader_error"]
        # the cause is at the end of a reason ("… exited 1: <rpi-hwid's last lines>"), so a long one keeps its end
        out["reader_error"] = why if len(why) <= REASON_MAX else "…" + why[-(REASON_MAX - 1) :]
        return out
    for field, value in read.get("facts", {}).items():
        out[field] = detail(value)
    return out


def detail(value):
    """One fact as an event detail: identity.detail's encoding, and a float (the Pi 5's `ext5v_v`, which an FPGA
    board's identity never has) in Python's shortest form, which the site reads back with float(). A NaN or an
    infinity is refused, as rpi-hwid refuses it in a label input."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"a Pi fact is not a finite number: {value!r}")
        return repr(value)
    return identity.detail(value)


def run_apart(argv, timeout):
    """(returncode, stdout, stderr) of argv, kept apart: rpi-hwid prints its document on stdout and what it did on
    stderr, so the document is all of stdout. A timeout kills the child and waits for it a bounded KILL_REAP_S at
    most, then raises Problem: a child stuck in the kernel (mithro/rpi-hwid #91) never holds up the boot check.
    A command that cannot be started is a Problem too."""
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        raise Problem("error", f"{argv[0]} could not be run: {e.strerror or e}") from None
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        how = "it was killed"
        try:
            p.kill()
            p.wait(timeout=KILL_REAP_S)
        except OSError as e:
            how = f"it could not be killed ({e.strerror or e})"
        except subprocess.TimeoutExpired:
            how = f"it was killed but had not exited {KILL_REAP_S} s later"
        for pipe in (p.stdout, p.stderr):
            pipe.close()
        raise Problem("error", f"{' '.join(argv)} did not finish within {timeout} s; {how}") from None
    return p.returncode, out, err


def read(run=run_apart, which=shutil.which):
    """{"reader": "rpi-hwid", "facts": {...}}; {"reader": "none"} when rpi-hwid is not installed; or
    {"reader": "rpi-hwid", "reader_error": why} when it ran and did not give the facts. Whatever goes wrong in the
    read is a reader_error, never an exception: the boards are still checked."""
    try:
        return _read(run, which)
    except Exception as e:  # a bug here must not stop the boards' checks: the boot is still an error, saying why
        return {"reader": TOOL, "reader_error": f"reading the Pi's facts crashed: {type(e).__name__}: {e}"}


def _read(run, which):
    if not which(TOOL):
        return {"reader": "none"}
    try:
        rc, out, err = run(list(ARGV), TIMEOUT)
    except Problem as p:
        return {"reader": TOOL, "reader_error": p.reason}
    if rc != 0:
        last = " / ".join(line for line in (err or out).strip().splitlines()[-3:] if line.strip()) or "no output"
        return {"reader": TOOL, "reader_error": f"{' '.join(ARGV)} exited {rc}: {last}"}
    if not out.strip():
        return {"reader": TOOL, "reader_error": f"{' '.join(ARGV)} printed no JSON document"}
    try:
        document = json.loads(out)
        return {"reader": TOOL, "facts": facts(document)}
    except json.JSONDecodeError as e:
        return {"reader": TOOL, "reader_error": f"{' '.join(ARGV)} printed JSON that does not parse: {e}"}
    except Unread as e:
        return {"reader": TOOL, "reader_error": str(e)}
