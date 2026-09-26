"""What every board's check shares: results, the host's facts, sysfs scans, commands, the lock, fleet-events.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import contextlib
import fcntl
import pathlib
import re
import struct
import subprocess
import sys

# Worst last: a run's result is the worst of its boards', a board's the worst of its checks'.
#   pass         everything checked out
#   degraded     works, but not as intended (an Acorn running its golden image)
#   unconverted  runs a design that is not ours, so it could not be checked (SQRL's factory image)
#   changed      a different board, or a different flash, from the one recorded: see `fpgas-verify --update`
#   fail         a test, a load or a flash comparison failed
#   missing      the configured board (or, with `auto`, any board) is not there
#   error        the check itself could not run (a missing tool, a damaged package, no configuration)
SEVERITY = ("pass", "degraded", "unconverted", "changed", "fail", "missing", "error")

RUN = pathlib.Path("/run/fpgas-online")
SYSFS_USB = pathlib.Path("/sys/bus/usb/devices")
SYSFS_PCI = pathlib.Path("/sys/bus/pci/devices")
DT_MODEL = pathlib.Path("/proc/device-tree/model")
DT_SOC_RANGES = pathlib.Path("/proc/device-tree/soc/ranges")
OUTPUT_TAIL = 20  # lines of a step's output kept in a report


class Problem(Exception):
    """Something that stops a check, with the result it gives and anything seen before it stopped."""

    def __init__(self, result, reason, **seen):
        super().__init__(reason)
        self.result, self.reason, self.seen = result, reason, seen


def worst(results, default="pass"):
    return max(results, key=SEVERITY.index, default=default)


def exit_code(result):
    return 0 if result == "pass" else 1


def tail(text, n=OUTPUT_TAIL):
    return [line for line in (text or "").splitlines() if line.strip()][-n:]


def run(argv, timeout, **kw):
    """Run argv, returning (returncode, combined output). A missing program or a timeout is a Problem."""
    argv = [str(a) for a in argv]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, **kw)
    except FileNotFoundError:
        raise Problem("error", f"{argv[0]} is not installed") from None
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        raise Problem("fail", f"{pathlib.Path(argv[0]).name} did not finish within {timeout} s: {out[-500:]}") from None
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# -- the host ---------------------------------------------------------------------------------------------


def pi_model(path=DT_MODEL):
    try:
        return path.read_bytes().rstrip(b"\0").decode(errors="replace")
    except OSError:
        return ""


def is_pi(model):
    return model.startswith("Raspberry Pi")


def is_pi5(model):
    return model.startswith(("Raspberry Pi 5", "Raspberry Pi Compute Module 5"))


def peripheral_base(ranges=DT_SOC_RANGES):
    """The SoC's peripheral base (for openocd's bcm2835gpio): the CPU address of the first `soc` range.

    The ranges cells are big-endian u32s, <child> <parent> <size>: 0x3f000000 on a Pi 3. On a Pi 4 the parent
    address has two cells (0x0 0xfe000000), which shows as a zero second cell.
    """
    try:
        data = ranges.read_bytes()
    except OSError as e:
        raise Problem("error", f"cannot read {ranges}: {e}") from None
    cells = struct.unpack(f">{len(data) // 4}I", data[: len(data) // 4 * 4])
    if len(cells) >= 4 and len(cells) % 4 == 0 and cells[1] == 0:
        return cells[2]
    if len(cells) >= 3:
        return cells[1]
    raise Problem("error", f"cannot read the peripheral base from {ranges}")


def host_facts(port=None):
    """What the checks need to know about this host. Board modules add their own (the peripheral base)."""
    return {"model": pi_model(), "port": port}


def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def usb_devices(root=SYSFS_USB):
    """Every USB device: {"vendor", "product", "serial", "path"}, IDs as lower-case hex strings."""
    found = []
    root = pathlib.Path(root)
    if not root.is_dir():
        return found
    for dev in sorted(root.iterdir()):
        vendor, product = _read(dev / "idVendor"), _read(dev / "idProduct")
        if vendor and product:  # interfaces have no IDs
            found.append({"vendor": vendor.lower(), "product": product.lower(), "serial": _read(dev / "serial"),
                          "path": dev.name})  # fmt: skip
    return found


def usb_matching(devices, wanted):
    """The devices matching any (vendor, product) in `wanted`; product None matches any product."""
    return [d for d in devices for v, p in wanted if d["vendor"] == v and (p is None or d["product"] == p)]


def pci_devices(root=SYSFS_PCI):
    """Every PCI function: {"bdf", "vendor", "device", "subsystem_vendor", "subsystem_device"} as ints."""
    found = []
    root = pathlib.Path(root)
    if not root.is_dir():
        return found
    names = ("vendor", "device", "subsystem_vendor", "subsystem_device")
    for dev in sorted(root.iterdir()):
        try:
            ids = [int(_read(dev / n), 16) for n in names]
        except (TypeError, ValueError):
            continue
        found.append({"bdf": dev.name, **dict(zip(names, ids))})
    return found


# -- one user of a board at a time ----------------------------------------------------------------------------


@contextlib.contextmanager
def hold_lock(path, what):
    """Hold `path` locked, waiting (and saying so) while someone else has it."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"waiting for another user of the {what} to finish...", file=sys.stderr)
            fcntl.flock(f, fcntl.LOCK_EX)
        yield


# -- fleet-events -------------------------------------------------------------------------------------------


def flatten(prefix, value, out):
    """fleet-event details are single strings: {"a": {"b": 1}} -> a_b=1, lists by index."""
    if isinstance(value, dict):
        for k, v in value.items():
            flatten(f"{prefix}_{k}" if prefix else str(k), v, out)
    elif isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            out[prefix] = " ".join(str(v) for v in value) or "-"
        else:
            for i, v in enumerate(value):
                flatten(f"{prefix}{i}", v, out)
    else:
        out[prefix] = "-" if value is None else str(value)
    return out


def fleet_event_argv(stage, details):
    argv = ["fleet-event", stage]
    for k, v in details.items():
        one_line = re.sub(r"[\r\n]+", " ", v)
        argv += ["--detail", f"{k}={one_line}"]
    return argv


def publish(stage, details, kept_in, prog="fpgas-verify"):
    """Send a fleet-event. A failure is reported loudly but does not change the result: the hardware is what
    it is whether or not the broker heard about it, and `kept_in` still holds the report."""
    try:
        subprocess.run(fleet_event_argv(stage, details), check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"{prog}: could not publish the result ({e}); the report is in {kept_in}", file=sys.stderr)
        return False
    return True
