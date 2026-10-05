"""The Acorn's links to its Pi besides PCIe: P1 (JTAG) and P2 (the UART on J2/K2, and the spare balls J5/H5).

The pins, the cable and the GPIO chip come from the host's setup (setup.py, from wiring.toml).

  rp1-pio  On a Pi 5 / CM5 (BCM2712): /dev/pio0 a character device that opens read-write, for
           openfpgaloader-rp1pio. No bootloader setting is read; when it fails, whether rp1_fw and rp1_pio
           are loaded and the kernel's rp1-pio / RP1 firmware lines say why. Not run on other hosts.
  jtag     `openFPGALoader --detect` over the P1 cable must find one device, the variant's part (any silicon
           version: the whole IDCODE is read from openFPGALoader's raw scan and decoded, idcode.py), and
           `openFPGALoader --read-dna` must read the device DNA the SoC reports over BAR0. An IDCODE read
           needs only TCK, TMS and TDO (the IDCODE is in the data register after reset); the DNA read
           shifts the FUSE_DNA instruction in through TDI, so it proves the fourth wire. Neither reconfigures
           the FPGA, so the enumerated PCIe endpoint is safe (docs/hardware/acorn-pcie-programming.md).
           openFPGALoader leaves TMS/TDI/TCK driven, so the pins are put back as they were found: on a
           Compute Blade GPIO14 is TMS and also the UART's TX, so it goes back to its UART function.
           Before the tool runs, the header's GPIO chip is asked whether it would hand out each JTAG pin
           (held_pins): a kernel whose pin controller is strict does not lend a pin a driver has, so on a
           Blade with the UART on, GPIO14 cannot be had. The tool is then not run, and the test fails
           naming the pin and its holder (#127).
  p2-uart  The UARTBone bridge on K2/J2: the identifier at the reset rate (1200 baud) must be the one BAR0
           gave; then the fast rate the gateware supports (921600, set through the PHY's tuning word); and
           at that rate the identifier again, the device DNA and the XADC readings. The link is left at the
           reset rate.
  p2-serial  J2 and K2, borrowed from the UART with the `p2_serial` switch (a finite timeout, so a killed run
           gives the link back), in both directions as bist.balls() does; then the switch must go back to
           serial by itself after its timeout, and the UARTBone must answer again with BAR0's identifier.
           On every setup: both carriers wire J2/K2.
  p2-gpio  J5 and H5 through the `p2_gpio` GPIOTristate CSR over BAR0, in both directions (bist.balls()).
           Only on a setup whose cable carries them (the Pi 5's).

Every Pi pin a P2 test drives is put back exactly as it was found.

Each gives a test entry in the board's report: {test, result, reason, output, ...what it read}.
"""

import contextlib
import fcntl
import os
import re
import stat
import struct

from ... import dna as device_dna
from ... import idcode
from ...core import Problem
from . import bist, check, uartbone_link

JTAG_TIMEOUT = 60
# The IDCODE of each variant's FPGA at version 0 (check.py's variants); compared without the version.
IDCODES = {"cle-215+": 0x03636093, "cle-215": 0x03636093, "cle-101": 0x03631093}
# openFPGALoader's libgpiod cable opens /dev/gpiochip0. The header's chip is found by its device-tree
# compatible (wiring.toml), not by number: a Pi 5 can have gpiochip11-15, 15 the RP1.
GPIOCHIP = "/dev/gpiochip0"
SYSFS_GPIO = "/sys/bus/gpio/devices"
# designs/_shared/acorn_p2.py SPARE_GPIO = ("J5", "H5"), the pins of p2_gpio: bit 0 is J5, bit 1 is H5.
P2_GPIO_BITS = {b: bit for b, (module, bit) in bist.FPGA_SIDE.items() if module == "p2_gpio"}
pin_states = bist.pin_states


def restore_pins(run, saved):
    """Put the JTAG pins back as they were found; one found as an output goes back as an input (openFPGALoader
    leaves its outputs driven, and a crashed run would leave them so)."""
    return bist.restore_pins(run, saved, exact=False)


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
    return gpiochip


# -- who holds a pin ------------------------------------------------------------------------------------------

# GPIO_V2_GET_LINEINFO_IOCTL (linux/gpio.h): struct gpio_v2_line_info is name[32], consumer[32], u32 offset,
# u32 num_attrs, u64 flags, 10 attributes of 16 bytes, 16 bytes of padding. GPIO_V2_LINE_FLAG_USED is bit 0.
LINEINFO_IOCTL, LINEINFO_SIZE, LINE_USED = 0xC100B405, 256, 1
DEBUGFS_PINCTRL = "/sys/kernel/debug/pinctrl"
# A strict controller's line (6.18, read on a CM5): "pin 14 (gpio14): device 1f00030000.serial function uart0
# group gpio14". Another's (6.12, a Pi 5): "pin 14 (gpio14): 1f00030000.serial (GPIO UNCLAIMED) function uart0
# group gpio14", and "pin 8 (gpio8): (MUX UNCLAIMED) (GPIO UNCLAIMED)" for a pin nothing has.
PINMUX_RE = re.compile(r"^pin (\d+) \(\S+\): (?:device )?([^\s(]\S*) (?:\(GPIO [^)]*\) )?function (\S+)", re.MULTILINE)


def _pinmux_owners(chip, sysfs=SYSFS_GPIO, debugfs=DEBUGFS_PINCTRL):
    """{pin: "the device (its function)"} from the pin controller's pinmux-pins in debugfs: which driver has
    each muxed pin. Only to name the holder: {} when debugfs or the controller's entry cannot be read."""
    try:
        controller = os.path.basename(os.path.dirname(os.path.realpath(f"{sysfs}/{os.path.basename(chip)}")))
        owners = {}
        for d in sorted(os.listdir(debugfs)):
            if d.startswith(f"{controller}-"):
                with open(f"{debugfs}/{d}/pinmux-pins") as f:
                    owners.update({int(pin): f"{device} ({function})" for pin, device, function
                                   in PINMUX_RE.findall(f.read())})  # fmt: skip
        return owners
    except (OSError, ValueError):  # ValueError: text that does not decode
        return {}


def held_pins(chip, gpios, sysfs=SYSFS_GPIO, debugfs=DEBUGFS_PINCTRL):
    """{gpio: who holds it} for the lines of `chip` the kernel will not hand out: one a program has requested,
    or, on a kernel whose pin controller is strict (the RP1's from 6.18 at least), one muxed to a driver, as
    GPIO14 is to the UART. A GPIO request for such a line fails, so a tool that needs it cannot run.
    {} when the chip cannot be asked: the tool then runs and says what it says."""
    held = {}
    try:
        fd = os.open(os.path.realpath(chip), os.O_RDONLY)
    except OSError:
        return {}
    try:
        for gpio in gpios:
            info = bytearray(LINEINFO_SIZE)
            struct.pack_into("I", info, 64, gpio)
            try:
                fcntl.ioctl(fd, LINEINFO_IOCTL, info)
            except OSError:
                continue  # this line cannot be asked about: what the others said still stands
            if struct.unpack_from("Q", info, 72)[0] & LINE_USED:
                held[gpio] = bytes(info[32:64]).split(b"\0")[0].decode(errors="replace")
    finally:
        os.close(fd)
    if held:
        owners = _pinmux_owners(os.path.realpath(chip), sysfs, debugfs)
        held = {g: owners.get(g) or (f'"{c}"' if c else "a kernel driver") for g, c in held.items()}
    return held


# -- The Pi 5's RP1 PIO, for openfpgaloader-rp1pio ---------------------------------------------------------

DT_COMPATIBLE = "/proc/device-tree/compatible"
SYSFS_MODULE = "/sys/module"
PIO_DEV = "/dev/pio0"
RP1_PIO_MODULES = ("rp1_fw", "rp1_pio")  # rp1_pio talks to the RP1 through rp1_fw, not a device-tree pio node
RP1_KERNEL_RE = re.compile(r"rp1-pio|rp1_firmware|rp1-firmware|RP1 Firmware")


def not_rp1_host(compatible=DT_COMPATIBLE):
    """Why the rp1-pio test does not apply here (not a BCM2712, so no RP1 PIO), or None if it does."""
    try:
        with open(compatible, "rb") as f:
            if b"brcm,bcm2712" in f.read().split(b"\0"):
                return None
    except OSError as e:
        return f"cannot read {compatible}: {e.strerror}"
    return "not a BCM2712 (Pi 5 / CM5): no RP1 PIO"


def rp1_pio(run, sysfs_module=SYSFS_MODULE, dev=PIO_DEV):
    """openfpgaloader-rp1pio drives JTAG through /dev/pio0: it must be there and open. Only when it does not are
    the modules looked at (a built-in driver has no /sys/module entry) and the kernel's own words added: a
    bootloader whose firmware rp1_pio cannot talk to logs "failed to contact RP1 firmware" and never creates
    /dev/pio0. The journal only explains a failure; a journal that cannot be read changes nothing."""
    faults = []
    try:
        is_char = stat.S_ISCHR(os.stat(dev).st_mode)
    except OSError as e:
        faults.append(("fail", f"{dev}: {e.strerror}"))
    else:
        if not is_char:
            faults.append(("fail", f"{dev} is not a character device"))
        else:
            try:
                os.close(os.open(dev, os.O_RDWR))
            except OSError as e:
                faults.append(("fail", f"cannot open {dev}: {e.strerror}"))
    output = []
    if faults:
        faults += [("fail", f"kernel module {m} is not loaded") for m in RP1_PIO_MODULES
                   if not os.path.isdir(f"{sysfs_module}/{m}")]  # fmt: skip
        try:
            rc, text = run(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"], 30)
        except Problem:
            rc, text = 1, ""
        output = [line for line in text.splitlines() if RP1_KERNEL_RE.search(line)] if rc == 0 else []
        if output:
            faults.append(("fail", f"kernel: {output[-1].strip()}"))
    return _entry("rp1-pio", faults, output)


def _entry(test, faults, output=(), **seen):
    """A test entry: the worst fault's result, every fault's reason."""
    entry = {"test": test, **seen, "output": list(output)[-12:]}
    if not faults:
        return {**entry, "result": "pass"}
    result = "error" if all(r == "error" for r, _ in faults) else "fail"
    return {**entry, "result": result, "reason": "; ".join(reason for _, reason in faults)}


# -- P1: JTAG ------------------------------------------------------------------------------------------

HELD = "the kernel does not hand out a pin that is held, so the JTAG chain cannot be scanned"


def pins_held(setup, holders):
    """Why JTAG cannot be probed: which of its pins are held, and by whom."""
    signal = dict(zip(setup.jtag_gpios, ("TDI", "TDO", "TCK", "TMS")))
    pins = ", ".join(f"GPIO{g} ({signal[g]}) is held by {who}" for g, who in sorted(holders.items()))
    return f"{pins}: {HELD}"


def jtag(setup, variant, run, bar0_dna=None, gpiochip=None, held=held_pins):
    want = IDCODES[variant]
    base = ["openFPGALoader", "--cable", setup.jtag_cable, "--pins", setup.jtag_pins]
    faults, output, seen = [], [], {}
    try:
        saved = pin_states(run, setup.jtag_gpios)
    except Problem as p:
        # openFPGALoader leaves the pins driven; with no way to put them back (on a Blade GPIO14 is also the
        # UART's TX) the probe is not run at all
        reason = f"P1 JTAG not probed: the JTAG pins' state could not be read, so it could not be put back: {p.reason}"
        return _entry("jtag", [("error", reason)], dna_error=f"not read over P1 JTAG: {reason}")
    # why the device DNA was not read, if it is not: apart from the IDCODE's faults (identity's dna_error)
    dna_error = "not read over P1 JTAG: --read-dna runs only once --detect has found the one FPGA expected"
    try:
        chip = (gpiochip or header_gpiochip)(setup.gpiochip)
        holders = held(chip, setup.jtag_gpios) if chip else {}
        if holders:
            # openFPGALoader would be refused the pin (and Debian's 0.13.1 aborts on a libgpiod assertion
            # instead of saying so, #127): not run, and the reason is the pin's holder
            raise Problem("fail", pins_held(setup, holders))
        rc, out = run([*base, "--detect", *idcode.OPENFPGALOADER_RAW_ARGS], JTAG_TIMEOUT)
        found = idcode.parse(out)
        output += (found and rc == 0 and idcode.scan_lines(out)) or out.strip().splitlines()[-6:]
        if found:
            seen["idcode"] = ", ".join(f"{i:#010x}" for i in found)
        if len(found) == 1:
            seen.update(idcode.decode(found[0]))
        faults += [("fail", f"P1 JTAG: {f}") for c in found for f in idcode.faults(c)]
        chain_ok = False
        scanned = bool(found) or idcode.empty_chain(out)
        if not scanned and rc != 0:  # the exit code is in this reason, so not said again below
            faults.append(("fail", f"P1 JTAG: {idcode.scan_failed('openFPGALoader --detect', rc, out)}"))
        elif not scanned:
            faults.append(("fail", f"P1 JTAG: {idcode.NO_RAW_SCAN}"))
        elif not found:
            faults.append(("fail", "no device on the P1 JTAG chain"))
        elif len(found) != 1 or not idcode.same_part(found[0], want):
            has = seen["idcode"] + (f" ({seen['idcode_device']})" if len(found) == 1 else "")
            faults.append(("fail", f"P1 JTAG chain has {has}, expected one {idcode.device(want)} "
                                   f"(IDCODE {want:#010x}, any version) for {variant}"))  # fmt: skip
        else:
            chain_ok = True
        if rc != 0 and scanned:  # whatever it printed, a scan that failed is not trusted
            faults.append(("fail", f"openFPGALoader --detect exited {rc} on the P1 JTAG chain"))
            if chain_ok:  # it found the one FPGA expected, so that is not why the DNA was not read
                dna_error = f"not read over P1 JTAG: openFPGALoader --detect exited {rc}, so --read-dna was not run"
        elif chain_ok:
            rc, out = run([*base, "--read-dna"], JTAG_TIMEOUT)
            output += out.strip().splitlines()[-4:]
            dna = device_dna.parse(out)
            if rc != 0 or dna is None:
                faults.append(("fail", "openFPGALoader --read-dna read no device DNA over P1 JTAG"))
                dna_error = f"openFPGALoader --read-dna read no device DNA over P1 JTAG (exit status {rc})"
            else:
                stuck = check.dna_faults(dna, "P1 JTAG")
                if stuck:  # a DNA port not being read, so not the board's DNA (identity uses dna_error instead)
                    faults += [("fail", f) for f in stuck]
                    dna_error = "; ".join(stuck)
                else:
                    seen["dna"] = f"{dna:#x}"
                if bar0_dna is not None and dna != bar0_dna:  # a good BAR0 DNA, so this may be TDI: both listed
                    faults.append(("fail", f"device DNA over JTAG {dna:#x} is not the one over BAR0 {bar0_dna:#x}: "
                                           "TDI (or the DNA readout) is wrong"))  # fmt: skip
    except (Problem, OSError) as e:
        # A missing tool or a wrong gpiochip is the check not running ("error"); a hung probe is a fail.
        result = e.result if isinstance(e, Problem) else "error"
        faults.append((result, f"P1 JTAG could not be probed: {e}"))
        dna_error = f"not read over P1 JTAG: P1 JTAG could not be probed: {e}"
    finally:
        faults += [("error", f) for f in restore_pins(run, saved)]
    if "dna" not in seen:
        seen["dna_error"] = dna_error
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


def p2_gpio(setup, bus, csrs, run):
    """J5/H5 both ways through `p2_gpio` over BAR0 (`bus`), the Pi's side with pinctrl."""
    wired = {ball: gpio for ball, gpio in setup.p2_gpio.items() if ball in P2_GPIO_BITS}
    regs = bist.Regs(bus.read, bus.write, csrs)
    try:
        for name in ("p2_gpio_oe", "p2_gpio_in", "p2_gpio_out"):
            csrs.addr(name)
        faults, output = bist.balls(regs, "p2_gpio", wired, run)
    except Problem as p:
        return _entry("p2-gpio", [(p.result, f"J5/H5 not checked: {p.reason}")])
    seen = {"wired": {ball: f"GPIO{gpio}" for ball, gpio in wired.items()}}
    return _entry("p2-gpio", [("fail" if "drove" in f else "error", f) for f in faults], output, **seen)


def p2_serial(setup, bus, csrs, run, identifier=None, open_port=None, settle=None, sleep=None):
    """J2/K2 both ways through `p2_serial` over BAR0, the switch's own timeout, and the UARTBone afterwards."""
    jtag = dict(zip(("TDI", "TDO", "TCK", "TMS"), setup.jtag_gpios))
    wired, skipped = bist.testable(setup.p2_serial, jtag)
    regs = bist.Regs(bus.read, bus.write, csrs)
    faults, output = [], [f"{ball} not driven: {why}" for ball, why in skipped.items()]
    seen = {"wired": {ball: f"GPIO{gpio}" for ball, gpio in wired.items()}}
    try:
        for name in ("p2_serial_mode", "p2_serial_oe", "p2_serial_in", "p2_serial_out", "p2_serial_timeout"):
            csrs.addr(name)
        with bist.borrowed_serial(regs):
            got, lines = bist.balls(regs, "p2_serial", wired, run)
        faults += [("fail" if "drove" in f else "error", f) for f in got]
        output += lines
        if regs["p2_serial_mode"] != 0:
            faults.append(("fail", "p2_serial did not go back to serial"))
        ok, detail = bist.switch_times_out(regs, sleep=sleep)
        output.append(f"switch timeout: {detail}")
        if not ok:
            faults.append(("fail", f"p2_serial did not go back to serial by itself ({detail})"))
    except Problem as p:
        faults.append((p.result, f"J2/K2: {p.reason}"))
        return _entry("p2-serial", faults, output, **seen)
    # the UARTBone answers again, as the switch left it: at the reset rate
    try:
        link = _uart_link(setup, open_port, settle)
    except ImportError as e:
        faults.append(("error", f"UARTBone not checked after the switch: {e}"))
        return _entry("p2-serial", faults, output, **seen)
    try:
        link.connect(fast=False)
        again = link.ident()
        output.append(f"UARTBone after the switch: {again!r}")
        if identifier and again != identifier:
            faults.append(("fail", f"after the switch the UARTBone answers {again!r}, not {identifier!r}"))
    except (uartbone_link.LinkError, OSError) as e:
        faults.append(("fail", f"the UARTBone does not answer on {setup.uart} after the switch ({e})"))
    finally:
        with contextlib.suppress(OSError):
            link.reset()
        link.close()
    return _entry("p2-serial", faults, output, **seen)
