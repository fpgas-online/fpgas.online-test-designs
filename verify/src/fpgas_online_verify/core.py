"""What every board's check shares: results, the host's facts, sysfs scans, commands, the lock, fleet-events.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import contextlib
import errno
import fcntl
import os
import pathlib
import re
import struct
import subprocess
import sys
import time

# Worst last: a run's result is the worst of its boards', a board's the worst of its checks'. Only "pass" means
# the board is ready for users; every other result is a fail of the check, named for what failed.
#   pass         everything checked out
#   changed      a different board, or a different flash, from the one recorded: see `fpgas-verify --update`
#   fail         a test, a load or a flash comparison failed, or the board runs a design that is not ours
#                (an Acorn on SQRL's factory image: "unconverted" in the reason)
#   missing      the configured board (or, with `auto`, any board) is not there
#   error        the check itself could not run (a missing tool, a damaged package, no configuration)
SEVERITY = ("pass", "changed", "fail", "missing", "error")

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


# -- the Pi's pins -------------------------------------------------------------------------------------------

# pinctrl get: "14: a4    pn | hi // GPIO14 = TXD0", "8: op dl pd | lo // GPIO8 = output"
PIN_RE = re.compile(r"^\s*(\d+):\s+(\w+)(?:\s+d[hl])?\s+(p[udn])\s*\|\s*(\w+|--)", re.MULTILINE)


def pin_states(run, gpios):
    """{gpio: (function, pull, level)} from pinctrl."""
    rc, out = run(["pinctrl", "get", ",".join(str(g) for g in gpios)], 10)
    found = {int(m[0]): (m[1], m[2], m[3]) for m in PIN_RE.findall(out)}
    if rc != 0 or set(found) != set(gpios):
        raise Problem("error", f"pinctrl get {','.join(map(str, gpios))} gave {out.strip()[:200]!r}")
    return found


def restore_pins(run, saved, exact=True):
    """Put each pin back as it was found. `exact`: an output goes back to an output at the level it had;
    otherwise to an input. Returns the faults."""
    faults = []
    for gpio, (func, pull, level) in sorted(saved.items()):
        args = [func, pull]
        if func == "op":
            args = [func, pull, "dh" if level == "hi" else "dl"] if exact else ["ip", pull]
        try:
            rc, out = run(["pinctrl", "set", str(gpio), *args], 10)
        except Problem as p:
            rc, out = 1, p.reason
        if rc != 0:
            faults.append(f"could not put GPIO{gpio} back to {' '.join(args)}: {out.strip()[:200]}")
    return faults


# -- one user of a board at a time ----------------------------------------------------------------------------


BUSY = "board busy"  # why a bounded wait for a board's lock gave up


class Busy(Problem):
    """Someone else held the board's lock for longer than the caller would wait."""

    def __init__(self, what, timeout):
        super().__init__("error", BUSY)
        self.what, self.timeout = what, timeout


def _owner(path):
    """Who owns `path`, as a user name if there is one."""
    import pwd  # stdlib, Unix only

    try:
        uid = os.stat(path).st_uid
    except OSError:
        return "unknown"
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return f"uid {uid}"


LOCK_OPEN_TRIES = 3  # a lock file that vanishes and reappears more often than this is an error, not a spin


def open_lock(path):
    """A read-only file descriptor of the lock file `path`, for flock. A lock file that is there is opened
    without O_CREAT: in a sticky, world-writable directory (/run/lock) the kernel's fs.protected_regular refuses
    even root an O_CREAT open of a file another user owns, which would stop the check until a reboot. Only a
    missing one is created (0644). The package's tmpfiles.d entry creates them root-owned at boot. A lock
    that cannot be opened is a Problem naming the file and its owner.

    A symlink is never followed (O_NOFOLLOW), and is a Problem naming it: a dangling one would make the open
    fail with ENOENT and the create with EEXIST for ever. The open is tried LOCK_OPEN_TRIES times at most."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nofollow = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    for _ in range(LOCK_OPEN_TRIES):
        try:
            if path.is_symlink():  # lstat: a link, dangling or not, is refused before anything opens it
                raise OSError(errno.ELOOP, "is a symlink")
            try:
                return os.open(path, nofollow)
            except FileNotFoundError:
                pass
            try:
                return os.open(path, nofollow | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue  # someone created it in between: open theirs
        except PermissionError as e:
            raise Problem("error", f"cannot open the lock file {path} (owned by {_owner(path)}): {e.strerror}; "
                                   "it should be root's: remove it, or reboot") from None  # fmt: skip
        except OSError as e:
            if e.errno != errno.ELOOP:
                raise
            raise Problem("error", f"the lock file {path} is a symlink, which is never followed: remove it, "
                                   "or reboot") from None  # fmt: skip
    raise Problem("error", f"cannot open the lock file {path}: it was gone, then there, {LOCK_OPEN_TRIES} times "
                           "over") from None  # fmt: skip


@contextlib.contextmanager
def hold_lock(path, what, timeout=None, poll=0.2, clock=time.monotonic, sleep=time.sleep):
    """Hold `path` locked, waiting (and saying so) while someone else has it. With `timeout` (seconds), give up
    after that long and raise Busy; without it (the boot check, fpgas-<board>-debug), wait as long as it takes."""
    with os.fdopen(open_lock(path), "r") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            limit = "" if timeout is None else f" (at most {timeout:g} s)"
            print(f"waiting for another user of the {what} to finish{limit}...", file=sys.stderr)
            if timeout is None:
                fcntl.flock(f, fcntl.LOCK_EX)
            else:
                _wait_for_lock(f, what, timeout, poll, clock, sleep)
        yield


def _wait_for_lock(f, what, timeout, poll, clock, sleep):
    deadline = clock() + timeout
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            left = deadline - clock()
            if left <= 0:
                raise Busy(what, timeout) from None
            sleep(min(poll, left))


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


def publish(stage, details, kept_in=None, prog="fpgas-verify", timeout=60):
    """Send a fleet-event. A failure is reported loudly but does not change the result: the hardware is what
    it is whether or not the broker heard about it, and `kept_in` (when given) still holds the report."""
    try:
        subprocess.run(fleet_event_argv(stage, details), check=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        where = f"; the report is in {kept_in}" if kept_in else ""
        print(f"{prog}: could not publish {stage} ({e}){where}", file=sys.stderr)
        return False
    return True
