"""The Acorn SoC's self-test hardware, driven from the Pi: the DRAM BIST, the BIOS console, and the P2 pins.

One copy, used by both the boot check (suite.py's `ddr`, `p2-serial` and `p2-gpio` tests) and the bring-up
script designs/acorn-pcie/host/selftest.py, so the two cannot drift apart. Stdlib only: no LiteX.

`regs` is a Regs: the running build's CSRs by name (from its csr.json) over a bus (BAR0, or the P2 UARTBone).
`run(argv, timeout) -> (returncode, output)` runs `pinctrl` for the Pi's side of the P2 pins.

  * console()  reads the BIOS console (the crossover UART) until it is quiet. The BIOS sets the DRAM up after
               its banner, and with this LiteX it stops once that console is full and nobody reads it (#47):
               on a board nobody has attached to, reading it is what lets DRAM initialisation finish.
  * dram()     two passes over the whole DRAM, in a low and a high half. A pass writes both halves before it
               checks either, with different data in each (a PRBS and a counter), and the second pass swaps
               them: a dead top address bit, or a board with half the DRAM the image expects, makes the high
               half land on the low one, and the check of the half written first fails.
  * balls()    P2 balls in both directions: the FPGA drives and the Pi reads, then the Pi drives and the FPGA
               reads, each ball at 0 and at 1, with the reading side's pull set against the driven level so
               a cut wire cannot pass. The Pi's pins are put back exactly as they were found.
  * borrowed_serial()  J2/K2 as GPIOs through the `p2_serial` switch, with a finite timeout, so a run that is
               killed gives the serial link back by itself; switch_times_out() checks that timeout works.
"""

import contextlib
import re
import time

from ...core import Problem

# Where the FPGA side of each P2 ball is: (CSR module, bit). designs/_shared/acorn_p2.py: p2_gpio's pins are
# SPARE_GPIO = ("J5", "H5"); P2SerialSwitch's are SWITCH_BITS = {"J2": 0, "K2": 1}.
FPGA_SIDE = {"J2": ("p2_serial", 0), "K2": ("p2_serial", 1), "J5": ("p2_gpio", 0), "H5": ("p2_gpio", 1)}
# The JTAG signal a P2 ball may share on the Pi: TMS changing does nothing while TCK is still, and nothing here
# moves TCK. A ball on TDI, TDO or TCK is never driven.
SHARED_JTAG_OK = {"TMS"}
# How long `p2_serial` keeps J2/K2 as GPIOs after the last write to `mode` while this code has them: longer than
# a test, short enough that a killed run gives the serial link back soon.
SWITCH_TIMEOUT_MS = 10000
SELF_TIMEOUT_MS = 200  # switch_times_out()'s own

# The BIST's `random` register: bit 0 = PRBS data (else a counter); bit 1 = random addresses (not used).
PRBS, COUNTER = 1, 0
PATTERN_NAMES = {PRBS: "prbs", COUNTER: "counter"}
BIST_TIMEOUT_S = 30  # one half; 512 MiB at the ~1.3 GB/s measured takes 0.4 s
MEMTEST_RE = re.compile(r"memtest.*", re.IGNORECASE)


class Regs:
    """CSRs by name: `regs["dram_checker_errors"]`, `regs["p2_serial_mode"] = 1`. `csrs` is a check.Csrs."""

    def __init__(self, read, write, csrs):
        self._read, self._write, self.csrs = read, write, csrs
        self.constants = csrs.constants
        self.memories = csrs.memories

    def __getitem__(self, name):
        return self._read(self.csrs.addr(name))

    def __setitem__(self, name, value):
        self._write(self.csrs.addr(name), value)


# -- the BIOS console --------------------------------------------------------------------------------------


def console(regs, quiet_s=2.0, max_s=60.0, clock=time.monotonic, sleep=None):
    """Everything the BIOS has printed since the console was last read, until it has been quiet for `quiet_s`."""
    sleep = sleep or time.sleep
    text, start, last = bytearray(), clock(), clock()
    while clock() - last < quiet_s and clock() - start < max_s:
        if regs["uart_xover_rxempty"]:
            sleep(0.005)
            continue
        text.append(regs["uart_xover_rxtx"] & 0xFF)  # the read pops it
        last = clock()
    return text.decode(errors="replace")


def memtest_line(text):
    """The BIOS's own memtest result line, if the console had it."""
    lines = [m.group(0).strip() for m in MEMTEST_RE.finditer(text)]
    return next((line for line in reversed(lines) if "ok" in line.lower() or "ko" in line.lower()), None)


# -- the DRAM --------------------------------------------------------------------------------------------


def _run(regs, core, base, length, pattern, timeout_s, sleep, clock):
    """One generator or checker run; its ticks, or None if it did not finish. `reset` restarts the PRBS and the
    counter, so every run of a pattern produces the same data: the halves differ only by their pattern."""
    regs[f"{core}_reset"] = 1
    regs[f"{core}_reset"] = 0
    regs[f"{core}_base"] = base
    regs[f"{core}_end"] = base + length
    regs[f"{core}_length"] = length
    regs[f"{core}_random"] = pattern  # sequential addresses
    regs[f"{core}_start"] = 1
    deadline = clock() + timeout_s
    while not regs[f"{core}_done"]:
        if clock() > deadline:
            return None
        sleep(0.01)
    return regs[f"{core}_ticks"]


def dram(regs, length=None, timeout_s=BIST_TIMEOUT_S, log=None, sleep=None, clock=time.monotonic):
    """Two passes over `length` bytes (default: the whole DRAM, from csr.json). Returns the measurements and
    `faults`, a list of sentences. `log(name, ok, detail)` hears each step (selftest.py prints them)."""
    log = log or (lambda name, ok, detail="": None)
    sleep = sleep or time.sleep
    clk = regs.constants["config_clock_frequency"]
    length = length or regs.memories["main_ram"]["size"]
    half = length // 2  # `length` and `end` are as wide as a DRAM address, so the full size does not fit them
    halves = (0, half)
    out = {"bytes": length, "passes": 2, "sys_clk_hz": clk, "write_ticks": 0, "read_ticks": 0, "errors": 0}
    faults = []
    started = clock()
    for n, patterns in enumerate(((PRBS, COUNTER), (COUNTER, PRBS)), start=1):
        for core, what in (("dram_generator", "write"), ("dram_checker", "read")):
            for base, pattern in zip(halves, patterns):
                name = PATTERN_NAMES[pattern]
                ticks = _run(regs, core, base, half, pattern, timeout_s, sleep, clock)
                log(f"pass {n}: dram {what} {name} at {base:#x} finished", ticks is not None)
                if ticks is None:
                    faults.append(f"pass {n}: the DRAM {what} of {name} at {base:#x} did not finish in {timeout_s} s")
                    out["faults"] = faults
                    return out
                out[f"{what}_ticks"] += ticks
                if core == "dram_checker":
                    errors = regs["dram_checker_errors"]
                    log(f"pass {n}: {name} at {base:#x}", errors == 0, f"{errors} errors")
                    out["errors"] += errors
                    if errors:
                        faults.append(f"pass {n}: {errors} words wrong in the {name} half at {base:#x}")
    for what in ("write", "read"):
        out[f"{what}_MBps"] = round(2 * length / (out[f"{what}_ticks"] / clk) / 1e6, 1) if out[f"{what}_ticks"] else 0.0
    out["seconds"] = round(clock() - started, 1)
    out["faults"] = faults
    return out


# -- the Pi's pins ---------------------------------------------------------------------------------------

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


def _levels(run, gpios):
    return {g: {"hi": 1, "lo": 0}.get(level) for g, (_, _, level) in pin_states(run, gpios).items()}


def balls(regs, module, wired, run, log=None):
    """`wired`: {ball: Pi GPIO} of balls whose FPGA side is `module` (p2_gpio, or p2_serial in GPIO mode).
    Returns (faults, output lines). The Pi's pins are put back exactly as they were, and the FPGA's are inputs.

    For p2_serial the switch is renewed (its `mode` written again, which restarts its timeout) before each
    pattern, so however slow pinctrl is, J2/K2 cannot go back to serial while the Pi is driving them."""
    log = log or (lambda name, ok, detail="": None)

    def renew():
        if module == "p2_serial":
            regs["p2_serial_mode"] = 1

    bit = {ball: FPGA_SIDE[ball][1] for ball in wired}
    gpios = sorted(wired.values())
    saved = pin_states(run, gpios)
    mask = sum(1 << bit[b] for b in wired)
    # all low, all high, and each ball high on its own: each ball at 0 and at 1, and a short between two shows
    patterns = sorted({0, mask, *(1 << bit[b] for b in wired)})
    faults, output = [], []
    try:
        regs[f"{module}_oe"] = 0
        for pattern in patterns:  # the FPGA drives, the Pi reads with its pull against the driven level
            renew()
            for ball, gpio in wired.items():
                run(["pinctrl", "set", str(gpio), "ip", "pd" if pattern >> bit[ball] & 1 else "pu"], 10)
            regs[f"{module}_out"] = pattern
            regs[f"{module}_oe"] = mask
            levels = _levels(run, gpios)
            regs[f"{module}_oe"] = 0
            for ball, gpio in wired.items():
                want = pattern >> bit[ball] & 1
                ok = levels[gpio] == want
                log(f"{ball} FPGA -> Pi GPIO{gpio} at {want}", ok, f"read {levels[gpio]}")
                if not ok:
                    faults.append(f"{ball} -> GPIO{gpio}: the FPGA drove {want}, the Pi read {levels[gpio]}")
            output.append(f"FPGA drives {pattern:02b}: Pi reads " + " ".join(f"GPIO{g}={levels[g]}" for g in gpios))
        for pattern in patterns:  # the Pi drives, the FPGA reads (its pins are inputs)
            renew()
            for ball, gpio in wired.items():
                run(["pinctrl", "set", str(gpio), "op", "dh" if pattern >> bit[ball] & 1 else "dl"], 10)
            got = regs[f"{module}_in"] & mask
            for ball, gpio in wired.items():
                want, read = pattern >> bit[ball] & 1, got >> bit[ball] & 1
                log(f"{ball} Pi GPIO{gpio} -> FPGA at {want}", read == want, f"read {read}")
                if read != want:
                    faults.append(f"GPIO{gpio} -> {ball}: the Pi drove {want}, the FPGA read {read}")
            output.append(f"Pi drives {pattern:02b}: FPGA reads {got:02b}")
    finally:
        regs[f"{module}_oe"] = 0
        regs[f"{module}_out"] = 0
        renew()  # the Pi's pins go back while J2/K2 are still GPIOs
        faults += restore_pins(run, saved)
    return faults, output


def testable(wired, jtag):
    """({ball: gpio} that may be driven, {ball: why not}): never a ball on the Pi's TDI, TDO or TCK.
    `jtag`: {signal: Pi GPIO}."""
    forbidden = {gpio: sig for sig, gpio in jtag.items() if sig not in SHARED_JTAG_OK}
    ok = {ball: gpio for ball, gpio in wired.items() if gpio not in forbidden}
    why = {ball: f"GPIO{gpio} is JTAG {forbidden[gpio]}" for ball, gpio in wired.items() if gpio in forbidden}
    return ok, why


# -- the P2 serial switch --------------------------------------------------------------------------------


@contextlib.contextmanager
def borrowed_serial(regs, timeout_ms=SWITCH_TIMEOUT_MS):
    """J2/K2 as GPIOs for the duration, with a finite timeout; then the FPGA's outputs off, the switch back on
    serial and its timeout as it was. Whatever restores the Pi's pins must do so inside, before the switch goes
    back: GPIO14 must be the UART's TX (idle high) again, or the UART takes what it drove for a start bit."""
    before = regs["p2_serial_timeout"]
    regs["p2_serial_timeout"] = timeout_ms  # back to serial by itself if this is killed
    regs["p2_serial_mode"] = 1
    try:
        if regs["p2_serial_mode"] != 1:
            raise Problem("fail", "p2_serial did not switch J2/K2 to GPIOs")
        yield
    finally:
        regs["p2_serial_oe"] = 0
        regs["p2_serial_mode"] = 0
        regs["p2_serial_timeout"] = before


def switch_times_out(regs, timeout_ms=SELF_TIMEOUT_MS, sleep=None):
    """The switch goes back to serial by itself `timeout_ms` after the last write to `mode`: (ok, detail)."""
    sleep = sleep or time.sleep
    before = regs["p2_serial_timeout"]
    try:
        regs["p2_serial_timeout"] = timeout_ms
        regs["p2_serial_mode"] = 1
        at_once = regs["p2_serial_mode"]
        sleep(timeout_ms / 1000 * 2.5)
        later = regs["p2_serial_mode"]
    finally:
        regs["p2_serial_mode"] = 0
        regs["p2_serial_timeout"] = before
    return (at_once, later) == (1, 0), f"mode {at_once}, {timeout_ms * 2.5 / 1000:g} s later {later}"
