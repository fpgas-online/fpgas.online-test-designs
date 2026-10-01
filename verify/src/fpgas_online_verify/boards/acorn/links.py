"""The Acorn's links to its Pi besides PCIe: P1 (JTAG) and P2 (the UART, and the spare balls J5 and H5).

The pins, the cable and the GPIO chip come from the host's setup (setup.py, from wiring.toml).

  jtag     `openFPGALoader --detect` over the P1 cable must find one device with the variant's IDCODE, and
           `openFPGALoader --read-dna` must read the device DNA the SoC reports over BAR0. An IDCODE read
           needs only TCK, TMS and TDO (the IDCODE is in the data register after reset); the DNA read
           shifts the FUSE_DNA instruction in through TDI, so it proves the fourth wire. Neither reconfigures
           the FPGA, so the enumerated PCIe endpoint is safe (docs/hardware/acorn-pcie-programming.md).
           openFPGALoader leaves TMS/TDI/TCK driven, so the pins are put back as they were found: on a
           Compute Blade GPIO14 is TMS and also the UART's TX, so it goes back to its UART function.
  p2-uart  The UARTBone bridge on K2/J2: the identifier at the reset rate (1200 baud) must be the one BAR0
           gave; then the fast rate the gateware supports (921600, set through the PHY's tuning word); and
           at that rate the identifier again, the device DNA and the XADC readings. The link is left at the
           reset rate.
  p2-gpio  J5 and H5 through the `p2_gpio` GPIOTristate CSR over BAR0, in both directions: the FPGA drives,
           the Pi reads, then the Pi drives and the FPGA reads. Each ball is seen at 0 and at 1, and the
           reading side's pull is set against the driven level, so a floating wire cannot pass. Only on a
           setup whose cable carries them (the Pi 5's); everything goes back to an input afterwards.

Each gives a test entry in the board's report: {test, result, reason, output, ...what it read}.
"""

import contextlib
import os
import re

from ...core import Problem
from . import check, uartbone_link

JTAG_TIMEOUT = 60
# The IDCODE of each variant's FPGA, the revision nibble masked off (check.py's variants).
IDCODES = {"cle-215+": 0x3636093, "cle-215": 0x3636093, "cle-101": 0x3631093}
IDCODE_RE = re.compile(r"idcode\s+(0x[0-9a-fA-F]+)")
DNA_RE = re.compile(r"\bdna\"?\s*[:=]\s*\"?(0x[0-9a-fA-F]+)", re.IGNORECASE)
# openFPGALoader's libgpiod cable opens /dev/gpiochip0. The header's chip is found by its device-tree
# compatible (wiring.toml), not by number: a Pi 5 can have gpiochip11-15, 15 the RP1.
GPIOCHIP = "/dev/gpiochip0"
SYSFS_GPIO = "/sys/bus/gpio/devices"
# pinctrl get: "14: a4    pn | hi // GPIO14 = TXD0", "8: op dl pd | lo // GPIO8 = output"
PIN_RE = re.compile(r"^\s*(\d+):\s+(\w+)(?:\s+d[hl])?\s+(p[udn])\s*\|\s*(\w+|--)", re.MULTILINE)
# designs/_shared/acorn_p2.py SPARE_GPIO = ("J5", "H5"), the pins of p2_gpio: bit 0 is J5, bit 1 is H5.
P2_GPIO_BITS = {"J5": 0, "H5": 1}


# -- the Pi's pins -------------------------------------------------------------------------------------


def pin_states(run, gpios):
    """{gpio: (function, pull, level)} from pinctrl."""
    rc, out = run(["pinctrl", "get", ",".join(str(g) for g in gpios)], 10)
    found = {int(m[0]): (m[1], m[2], m[3]) for m in PIN_RE.findall(out)}
    if rc != 0 or set(found) != set(gpios):
        raise Problem("error", f"pinctrl get {','.join(map(str, gpios))} gave {out.strip()[:200]!r}")
    return found


def restore_pins(run, saved):
    """Put each pin back as it was found; a pin found as an output goes back as an input. Returns faults."""
    faults = []
    for gpio, (func, pull, _) in sorted(saved.items()):
        try:
            rc, out = run(["pinctrl", "set", str(gpio), "ip" if func == "op" else func, pull], 10)
        except Problem as p:
            rc, out = 1, p.reason
        if rc != 0:
            faults.append(f"could not put GPIO{gpio} back to {func} {pull}: {out.strip()[:200]}")
    return faults


def header_chip(compatible, sysfs=SYSFS_GPIO, dev="/dev"):
    """The device path of the GPIO chip with this device-tree compatible, or None."""
    for chip in sorted(os.listdir(sysfs)) if os.path.isdir(sysfs) else []:
        try:
            with open(f"{sysfs}/{chip}/of_node/compatible", "rb") as f:
                if compatible.encode() in f.read().split(b"\0"):
                    return f"{dev}/{chip}"
        except OSError:
            continue
    return None


def header_gpiochip(compatible, gpiochip=GPIOCHIP, sysfs=SYSFS_GPIO, dev="/dev"):
    """Make /dev/gpiochip0 the header chip (a symlink in devtmpfs, gone at reboot). A freshly booted Pi 5 has
    no gpiochip0; if some other chip is gpiochip0, probing it would test the wrong pins, so that is refused."""
    header = header_chip(compatible, sysfs, dev)
    if header is None:
        raise Problem("error", f"no GPIO chip compatible with {compatible}: P1 JTAG not probed")
    if not os.path.lexists(gpiochip):
        os.symlink(header, gpiochip)
    elif os.path.realpath(gpiochip) != os.path.realpath(header):
        raise Problem("error", f"{gpiochip} is not the header's GPIO chip ({header}): P1 JTAG not probed")


def _entry(test, faults, output=(), **seen):
    """A test entry: the worst fault's result, every fault's reason."""
    entry = {"test": test, **seen, "output": list(output)[-12:]}
    if not faults:
        return {**entry, "result": "pass"}
    result = "error" if all(r == "error" for r, _ in faults) else "fail"
    return {**entry, "result": result, "reason": "; ".join(reason for _, reason in faults)}


# -- P1: JTAG ------------------------------------------------------------------------------------------


def jtag(setup, variant, run, bar0_dna=None, gpiochip=None):
    want = IDCODES[variant]
    base = ["openFPGALoader", "--cable", setup.jtag_cable, "--pins", setup.jtag_pins]
    faults, output, seen = [], [], {}
    try:
        saved = pin_states(run, setup.jtag_gpios)
    except Problem as p:
        # openFPGALoader leaves the pins driven; with no way to put them back (on a Blade GPIO14 is also the
        # UART's TX) the probe is not run at all
        reason = f"P1 JTAG not probed: the JTAG pins' state could not be read, so it could not be put back: {p.reason}"
        return _entry("jtag", [("error", reason)])
    try:
        (gpiochip or header_gpiochip)(setup.gpiochip)
        rc, out = run([*base, "--detect"], JTAG_TIMEOUT)
        output += out.strip().splitlines()[-6:]
        found = [int(x, 16) & 0x0FFFFFFF for x in IDCODE_RE.findall(out)]
        if found:
            seen["idcode"] = ", ".join(f"{i:#09x}" for i in found)
        if rc != 0 or not found:
            faults.append(("fail", "no device on the P1 JTAG chain"))
        elif found != [want]:
            faults.append(("fail", f"P1 JTAG chain has {seen['idcode']}, expected {want:#09x} for {variant}"))
        else:
            rc, out = run([*base, "--read-dna"], JTAG_TIMEOUT)
            output += out.strip().splitlines()[-4:]
            m = DNA_RE.search(out)
            if rc != 0 or not m:
                faults.append(("fail", "openFPGALoader --read-dna read no device DNA over P1 JTAG"))
            else:
                dna = int(m.group(1), 16)
                seen["dna"] = f"{dna:#x}"
                if bar0_dna is not None and dna != bar0_dna:
                    faults.append(("fail", f"device DNA over JTAG {dna:#x} is not the one over BAR0 {bar0_dna:#x}: "
                                           "TDI (or the DNA readout) is wrong"))  # fmt: skip
    except (Problem, OSError) as e:
        # A missing tool or a wrong gpiochip is the check not running ("error"); a hung probe is a fail.
        result = e.result if isinstance(e, Problem) else "error"
        faults.append((result, f"P1 JTAG could not be probed: {e}"))
    finally:
        faults += [("error", f) for f in restore_pins(run, saved)]
    return _entry("jtag", faults, output, **seen)


# -- P2: the UARTBone bridge ---------------------------------------------------------------------------


def _uart_link(setup, open_port, settle):
    opener = open_port or uartbone_link._serial_opener(setup.uart)
    return uartbone_link.UARTBoneLink(opener, settle) if settle else uartbone_link.UARTBoneLink(opener)


def _fast(link, csrs):
    """Up to the build's fast rate, through its own tuning word CSR and value."""
    word = csrs.constants.get("uart_fast_tuning_word")
    baud = csrs.constants.get("uart_fast_baud", uartbone_link.FAST_BAUD)
    return link.speed_up(csrs.addr("uartbone_bridge_phy_tuning_word"), word, baud)


def p2_uart(setup, builds, expected, bar0=None, open_port=None, settle=None):
    """`builds`: {identifier (case-folded): Csrs} of the release's builds for this variant. `bar0`: what BAR0
    gave ({"identifier", "dna"}), when it was read."""
    bar0 = bar0 or {}
    where = f"{setup.uart} (P2 K2/J2)"
    try:
        link = _uart_link(setup, open_port, settle)
    except ImportError as e:  # pyserial
        return _entry("p2-uart", [("error", f"P2 UART not checked: {e}")])
    faults, output, seen = [], [], {}
    try:
        try:
            seen["baud"] = [link.connect(fast=False)]
            ident = link.ident()
        except (uartbone_link.LinkError, OSError) as e:
            return _entry("p2-uart", [("fail", f"no UARTBone reply on {where}")], [str(e)])
        seen["identifier"] = ident
        output.append(f"{seen['baud'][0]} baud: ident {ident!r}")
        if bar0.get("identifier") and ident != bar0["identifier"]:
            faults.append(("fail", f"UARTBone ident {ident!r} is not the BAR0 identifier {bar0['identifier']!r}"))
        csrs = builds.get(ident.casefold())
        if csrs is None:  # not a build we know: its CSR map is unknown, so nothing else is sent
            faults.append(("fail", f"UARTBone ident {ident!r} is not a build of the installed release"))
            return _entry("p2-uart", faults, output, **seen)
        try:
            seen["baud"].append(_fast(link, csrs))
            again = link.ident()
            dna = check.read_dna(lambda a: link.read(a)[0], csrs)
            xadc = check.read_xadc(lambda a: link.read(a)[0], csrs)
        except (uartbone_link.LinkError, OSError) as e:
            faults.append(("fail", f"P2 UART at the fast rate: {e}"))
            return _entry("p2-uart", faults, output, **seen)
        except Problem as p:
            faults.append((p.result, p.reason))
            return _entry("p2-uart", faults, output, **seen)
        output.append(f"{seen['baud'][-1]} baud: ident {again!r}, dna {dna:#x}, xadc {xadc}")
        seen.update(dna=f"{dna:#x}", xadc=xadc)
        if again != ident:
            faults.append(("fail", f"at {seen['baud'][-1]} baud the ident reads {again!r}"))
        faults += [("fail", f) for f in check.dna_faults(dna, "P2 UART")]
        if bar0.get("dna") is not None and dna != bar0["dna"]:
            faults.append(("fail", f"device DNA over P2 UART {dna:#x} is not the one over BAR0 {bar0['dna']:#x}"))
        faults += [("fail", f) for f in check.xadc_faults(xadc, expected.get("xadc", {}), "P2 UART")]
        return _entry("p2-uart", faults, output, **seen)
    finally:
        with contextlib.suppress(OSError):
            link.reset()
        link.close()


def uart_scratch(setup, builds, open_port=None, settle=None):
    """The ctrl scratch round trip over the P2 UARTBone, at the fast rate: (faults, what was done)."""
    try:
        link = _uart_link(setup, open_port, settle)
    except ImportError as e:
        return [("error", f"P2 UART not checked: {e}")]
    try:
        link.connect(fast=False)
        csrs = builds.get(link.ident().casefold())
        if csrs is None:
            return [("fail", "the P2 UART does not answer as a build of the installed release")]
        _fast(link, csrs)
        faults = check.scratch_faults(lambda a: link.read(a)[0], lambda a, v: link.write(a, [v]), csrs, "P2 UART")
        return [("fail", f) for f in faults]
    except (uartbone_link.LinkError, OSError) as e:
        return [("fail", f"scratch over P2 UART: no reply on {setup.uart} ({e})")]
    except Problem as p:
        return [(p.result, p.reason)]
    finally:
        with contextlib.suppress(OSError):
            link.reset()
        link.close()


# -- P2: the spare balls -------------------------------------------------------------------------------


def _levels(run, gpios):
    return {g: {"hi": 1, "lo": 0}.get(level) for g, (_, _, level) in pin_states(run, gpios).items()}


def p2_gpio(setup, bus, csrs, run):
    """J5/H5 both ways through `p2_gpio` over BAR0 (`bus`), the Pi's side with pinctrl."""
    balls = {ball: gpio for ball, gpio in setup.p2_gpio.items() if ball in P2_GPIO_BITS}
    faults, output = [], []
    try:
        oe, din, dout = csrs.addr("p2_gpio_oe"), csrs.addr("p2_gpio_in"), csrs.addr("p2_gpio_out")
    except Problem as p:
        return _entry("p2-gpio", [(p.result, f"J5/H5 not checked: {p.reason}")])
    gpios = sorted(balls.values())
    try:
        saved = pin_states(run, gpios)
    except Problem as p:
        return _entry("p2-gpio", [("error", f"J5/H5 not checked: {p.reason}")])
    mask = sum(1 << P2_GPIO_BITS[b] for b in balls)
    # all low, all high, and each ball high on its own: each ball at 0 and at 1, and a short between two shows
    patterns = sorted({0, mask, *(1 << P2_GPIO_BITS[b] for b in balls)})
    try:
        bus.write(oe, 0)
        for pattern in patterns:  # the FPGA drives, the Pi reads with its pull against the driven level
            for ball, gpio in balls.items():
                bit = pattern >> P2_GPIO_BITS[ball] & 1
                run(["pinctrl", "set", str(gpio), "ip", "pd" if bit else "pu"], 10)
            bus.write(dout, pattern)
            bus.write(oe, mask)
            levels = _levels(run, gpios)
            bus.write(oe, 0)
            for ball, gpio in balls.items():
                bit = pattern >> P2_GPIO_BITS[ball] & 1
                if levels[gpio] != bit:
                    faults.append(("fail", f"{ball} -> GPIO{gpio}: the FPGA drove {bit}, the Pi read {levels[gpio]}"))
            output.append(f"FPGA drives {pattern:02b}: Pi reads " + " ".join(f"GPIO{g}={levels[g]}" for g in gpios))
        for pattern in patterns:  # the Pi drives, the FPGA reads (its pins are inputs)
            for ball, gpio in balls.items():
                run(["pinctrl", "set", str(gpio), "op", "dh" if pattern >> P2_GPIO_BITS[ball] & 1 else "dl"], 10)
            got = bus.read(din) & mask
            for ball, gpio in balls.items():
                bit, read = pattern >> P2_GPIO_BITS[ball] & 1, got >> P2_GPIO_BITS[ball] & 1
                if read != bit:
                    faults.append(("fail", f"GPIO{gpio} -> {ball}: the Pi drove {bit}, the FPGA read {read}"))
            output.append(f"Pi drives {pattern:02b}: FPGA reads {got:02b}")
    except Problem as p:
        faults.append((p.result, f"J5/H5: {p.reason}"))
    finally:
        bus.write(oe, 0)
        bus.write(dout, 0)
        faults += [("error", f) for f in restore_pins(run, saved)]
    seen = {"wired": {ball: f"GPIO{gpio}" for ball, gpio in balls.items()}}
    return _entry("p2-gpio", faults, output, **seen)
