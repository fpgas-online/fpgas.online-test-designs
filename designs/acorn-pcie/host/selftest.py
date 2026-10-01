#!/usr/bin/env python3
"""Exercise the Acorn SoC's DRAM BIST and every P2 pin, over PCIe BAR0, on the Pi the board is wired to.

Needs the operational image of a release that has the BIST and the P2 switch (csr.json lists `dram_generator`,
`dram_checker` and `p2_serial`), no kernel driver bound to the board, and `pinctrl` (raspi-utils) for the Pi's
side of the P2 pins. Run as root:

    sudo python3 selftest.py --csr acorn-cle-215p-csr.json [--bdf 0001:01:00.0] [--uart /dev/ttyAMA0]
        [--carrier pi5|blade]

0. The BIOS console (the crossover UART) is read out over BAR0 first. The BIOS sets the DRAM up after its
   banner, and with this LiteX it stops when its console fills and nobody reads it (PR #47), so on a
   board nobody has attached to, reading it is what lets DRAM initialisation finish.
1. DRAM: two passes over the whole DRAM, each split into a low and a high half. A pass writes both halves
   with `dram_generator` before it checks either with `dram_checker`, and the halves get different data: a
   PRBS in one, a counter in the other, swapped in the second pass. A broken top address bit, or a board
   with half the DRAM the image expects, makes the high half overwrite the low one, and the check of the
   half written first fails. Reports the errors and the bandwidth (bytes / (ticks / sys clock)).
2. P2: each P2 ball the carrier wires to the Pi (docs/wiring/acorn/wiring.toml), driven low then high from
   the FPGA and read on the Pi, then driven from the Pi and read on the FPGA. J2/K2 are borrowed from the
   UART with `p2_serial`; J5/H5 are `p2_gpio`. Balls the carrier does not wire are skipped (on the
   Compute Blade, J5/H5). No ball is tested on the Pi's TDI, TDO or TCK. A ball may share TMS (on the Compute
   Blade, J2 meets TMS on GPIO14): the Pi's UART TX drives GPIO14 all the time anyway, and with TCK still,
   TMS changing does nothing to JTAG.
3. The switch's own timeout: switch to GPIO with a 200 ms timeout and see it come back to serial alone.
4. With `--uart`: the UARTBone answers on P2 afterwards, with the identifier BAR0 reads.

Every Pi pin is put back as it was (`pinctrl get` before, `pinctrl set` after), and the switch is back on serial,
even when a step fails. If the script is killed while the pins are GPIOs, the switch goes back to serial by
itself after SWITCH_TIMEOUT_MS. Prints one line per check and exits 1 if any failed.

Uses only the Python standard library, except `--uart`, which needs pyserial and the installed
fpgas_online_verify package (fpgas-online-acorn-tools).
"""

import argparse
import json
import mmap
import os
import pathlib
import re
import struct
import subprocess
import sys
import time

BAR0_SIZE = 0x20000

# Where the FPGA side of each P2 ball lives: (CSR module, bit).
FPGA_SIDE = {
    "J2": ("p2_serial", 0),
    "K2": ("p2_serial", 1),
    "J5": ("p2_gpio", 0),
    "H5": ("p2_gpio", 1),
}
# Per carrier, from docs/wiring/acorn/wiring.toml (tests/test_acorn_selftest.py checks these against it): the
# Pi GPIO each wired P2 ball reaches, and the Pi GPIO of each JTAG signal.
P2_GPIO = {
    "pi5": {"J2": 14, "K2": 15, "J5": 3, "H5": 4},
    "blade": {"J2": 14, "K2": 15},
}
JTAG_GPIO = {
    "pi5": {"TDI": 10, "TDO": 9, "TCK": 11, "TMS": 8},
    "blade": {"TDI": 2, "TDO": 3, "TCK": 4, "TMS": 14},
}
# The JTAG signals a P2 ball may share: toggling TMS does nothing while TCK is still, and this test never moves
# TCK. TDI/TDO/TCK are never driven.
SHARED_JTAG_OK = {"TMS"}
# The P2 switch's timeout while this test has the pins: longer than the test, short enough that a killed run
# gives the serial link back soon. The gateware's reset value is put back afterwards.
SWITCH_TIMEOUT_MS = 10000
SWITCH_RESET_TIMEOUT_MS = 5000

# The BIST's `random` register: bit 0 = PRBS data (else a counter), bit 1 = random addresses (not used here).
PRBS, COUNTER = 1, 0
PATTERN_NAMES = {PRBS: "prbs", COUNTER: "counter"}


class Bar0:
    """BAR0 with memory decoding switched on for as long as it is open (it is off with no driver bound)."""

    def __init__(self, bdf):
        self.dev = pathlib.Path("/sys/bus/pci/devices") / bdf
        driver = self.dev / "driver"
        if driver.is_symlink():
            sys.exit(f"error: {os.path.basename(os.readlink(driver))} is bound to {bdf}; unbind it first")

    def __enter__(self):
        self.cfg = open(self.dev / "config", "r+b")
        self.cfg.seek(4)
        self.command = struct.unpack("<H", self.cfg.read(2))[0]
        self._command(self.command | 0x2)
        fd = os.open(self.dev / "resource0", os.O_RDWR | os.O_SYNC)
        try:
            self.map = mmap.mmap(fd, BAR0_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            os.close(fd)
        return self

    def __exit__(self, *exc):
        self.map.close()
        self._command(self.command)
        self.cfg.close()

    def _command(self, value):
        self.cfg.seek(4)
        self.cfg.write(struct.pack("<H", value))
        self.cfg.flush()

    def read(self, addr):
        off = addr & (BAR0_SIZE - 1)
        return struct.unpack("<I", self.map[off : off + 4])[0]

    def write(self, addr, value):
        off = addr & (BAR0_SIZE - 1)
        self.map[off : off + 4] = struct.pack("<I", value)


class Csr:
    def __init__(self, bus, csr_json):
        self.bus = bus
        self.regs = {name: r["addr"] for name, r in csr_json["csr_registers"].items()}
        self.constants = csr_json["constants"]
        self.memories = csr_json["memories"]

    def __getitem__(self, name):
        return self.bus.read(self.regs[name])

    def __setitem__(self, name, value):
        self.bus.write(self.regs[name], value)


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)
    return ok


# -- BIOS console ---------------------------------------------------------------------------------------------


def drain_console(csr, quiet_s=2.0, max_s=60.0):
    """Everything the BIOS has printed, read until it has been quiet for `quiet_s`."""
    text, start, last = bytearray(), time.monotonic(), time.monotonic()
    while time.monotonic() - last < quiet_s and time.monotonic() - start < max_s:
        if csr["uart_xover_rxempty"]:
            time.sleep(0.005)
            continue
        text.append(csr["uart_xover_rxtx"] & 0xFF)  # the read pops it
        last = time.monotonic()
    return text.decode(errors="replace")


# -- DRAM --------------------------------------------------------------------------------------------------


def _bist_pass(csr, core, base, length, pattern, timeout_s):
    """One generator or checker run. `reset` restarts the PRBS and the counter, so every run of a pattern
    produces the same data: the halves differ only because they get different patterns."""
    csr[f"{core}_reset"] = 1
    csr[f"{core}_reset"] = 0
    csr[f"{core}_base"] = base
    csr[f"{core}_end"] = base + length
    csr[f"{core}_length"] = length
    csr[f"{core}_random"] = pattern  # sequential addresses
    csr[f"{core}_start"] = 1
    deadline = time.monotonic() + timeout_s
    while not csr[f"{core}_done"]:
        if time.monotonic() > deadline:
            return None
        time.sleep(0.01)
    return csr[f"{core}_ticks"]


def dram(csr, length=None):
    """The whole DRAM, twice, in two halves (`length` and `end` are as wide as a DRAM address, so the full
    size does not fit them). Both halves are written before either is checked, with different data."""
    clk = csr.constants["config_clock_frequency"]
    length = length or csr.memories["main_ram"]["size"]
    half = length // 2
    halves = (0, half)
    out = {"bytes": length, "passes": 2, "sys_clk_hz": clk, "write_ticks": 0, "read_ticks": 0, "errors": 0}
    for n, patterns in enumerate(((PRBS, COUNTER), (COUNTER, PRBS)), start=1):
        for core, what in (("dram_generator", "write"), ("dram_checker", "read")):
            for base, pattern in zip(halves, patterns, strict=True):
                name = PATTERN_NAMES[pattern]
                ticks = _bist_pass(csr, core, base, half, pattern, timeout_s=30)
                if not check(f"pass {n}: dram {what} {name} at {base:#x} finished", ticks is not None):
                    return out
                out[f"{what}_ticks"] += ticks
                if core == "dram_checker":
                    errors = csr["dram_checker_errors"]
                    check(f"pass {n}: {name} at {base:#x}", errors == 0, f"{errors} errors")
                    out["errors"] += errors
    for what in ("write", "read"):
        out[f"{what}_MBps"] = round(2 * length / (out[f"{what}_ticks"] / clk) / 1e6, 1)
    check(
        "dram bist",
        out["errors"] == 0,
        f"{length >> 20} MiB x 2 passes, {out['errors']} errors, "
        f"write {out['write_MBps']} MB/s, read {out['read_MBps']} MB/s",
    )
    return out


# -- P2 ----------------------------------------------------------------------------------------------------


def _pinctrl(*args):
    return subprocess.run(["pinctrl", *args], check=True, capture_output=True, text=True).stdout


def pi_state(gpio):
    """`pinctrl get` as the arguments that put it back: function and pull, plus level for an output."""
    line = _pinctrl("get", str(gpio))
    m = re.match(r"\s*\d+:\s+(\S+)\s+(\S+)\s+\|\s+(\S+)", line)
    func, pull, level = m.groups()
    args = [func, pull]
    if func == "op":
        args.append("dh" if level == "hi" else "dl")
    return args


def pi_read(gpio):
    return 1 if "| hi" in _pinctrl("get", str(gpio)) else 0


def fpga_drive(csr, module, bit, value):
    csr[f"{module}_out"] = (csr[f"{module}_out"] & ~(1 << bit)) | (value << bit)
    csr[f"{module}_oe"] = 1 << bit


def fpga_read(csr, module, bit):
    return (csr[f"{module}_in"] >> bit) & 1


def carrier_of(model_path="/proc/device-tree/model"):
    """`pi5` or `blade`, from the Pi's model string."""
    model = pathlib.Path(model_path).read_text(errors="replace").rstrip("\0")
    if model.startswith("Raspberry Pi 5"):
        return "pi5"
    if "Compute Module" in model:
        return "blade"
    sys.exit(f"error: no Acorn carrier known for {model!r}; pass --carrier")


def pins_to_test(carrier):
    """{ball: Pi GPIO} for the balls this carrier wires to the Pi, except any on TDI/TDO/TCK, and
    {ball: why} for the rest."""
    wired = P2_GPIO[carrier]
    forbidden = {gpio: sig for sig, gpio in JTAG_GPIO[carrier].items() if sig not in SHARED_JTAG_OK}
    test = {ball: gpio for ball, gpio in wired.items() if gpio not in forbidden}
    skipped = {ball: "not wired on this carrier (wiring.toml)" for ball in FPGA_SIDE if ball not in wired}
    skipped |= {ball: f"GPIO{gpio} is JTAG {forbidden[gpio]}" for ball, gpio in wired.items() if gpio in forbidden}
    return test, skipped


def p2(csr, carrier):
    pins, skipped = pins_to_test(carrier)
    for ball, why in skipped.items():
        print(f"     {ball}: {why}, carrier {carrier}", flush=True)
    saved = {gpio: pi_state(gpio) for gpio in pins.values()}
    print(f"     Pi pins before: {saved}", flush=True)
    try:
        csr["p2_serial_timeout"] = SWITCH_TIMEOUT_MS  # back to serial by itself if this script is killed
        csr["p2_serial_mode"] = 1
        check("p2_serial switched to GPIO", csr["p2_serial_mode"] == 1)
        for ball, gpio in pins.items():
            module, bit = FPGA_SIDE[ball]
            # FPGA -> Pi
            _pinctrl("set", str(gpio), "ip", "pn")
            seen = []
            for level in (0, 1, 0, 1):
                fpga_drive(csr, module, bit, level)
                time.sleep(0.001)
                seen.append(pi_read(gpio))
            check(f"{ball} FPGA -> Pi GPIO{gpio}", seen == [0, 1, 0, 1], f"drove 0101, read {''.join(map(str, seen))}")
            csr[f"{module}_oe"] = 0
            # Pi -> FPGA
            seen = []
            for level in (0, 1, 0, 1):
                _pinctrl("set", str(gpio), "op", "pn", "dh" if level else "dl")
                time.sleep(0.001)
                seen.append(fpga_read(csr, module, bit))
            _pinctrl("set", str(gpio), "ip", "pn")
            check(f"{ball} Pi GPIO{gpio} -> FPGA", seen == [0, 1, 0, 1], f"drove 0101, read {''.join(map(str, seen))}")
    finally:
        for module in ("p2_serial", "p2_gpio"):
            csr[f"{module}_oe"] = 0
        for gpio, args in saved.items():
            _pinctrl("set", str(gpio), *args)
        csr["p2_serial_mode"] = 0
        csr["p2_serial_timeout"] = SWITCH_RESET_TIMEOUT_MS
    check("p2_serial back on serial", csr["p2_serial_mode"] == 0)
    print(f"     Pi pins after: { {gpio: pi_state(gpio) for gpio in saved} }", flush=True)

    csr["p2_serial_timeout"] = 200
    csr["p2_serial_mode"] = 1
    at_once = csr["p2_serial_mode"]
    time.sleep(0.5)
    later = csr["p2_serial_mode"]
    csr["p2_serial_mode"] = 0
    csr["p2_serial_timeout"] = SWITCH_RESET_TIMEOUT_MS
    check("p2_serial returns to serial by itself", (at_once, later) == (1, 0), f"mode {at_once}, 0.5 s later {later}")


def uart(port, ident):
    from fpgas_online_verify.boards.acorn import uartbone_link

    link = uartbone_link.UARTBoneLink(uartbone_link._serial_opener(port))
    try:
        link.connect()
        got = link.ident()
    finally:
        link.close()
    check("UARTBone on P2 answers after the switch", got == ident, repr(got))


def read_ident(csr, csr_json):
    base = csr_json["csr_bases"]["identifier_mem"]
    chars = []
    for i in range(256):
        c = csr.bus.read(base + 4 * i) & 0xFF
        if not c:
            break
        chars.append(chr(c))
    return "".join(chars)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csr", required=True, type=pathlib.Path, help="the running image's csr.json")
    parser.add_argument("--bdf", default="0001:01:00.0")
    parser.add_argument("--uart", metavar="PORT", help="also check the UARTBone on PORT afterwards")
    parser.add_argument("--carrier", choices=sorted(P2_GPIO), help="default: from /proc/device-tree/model")
    parser.add_argument("--dram-bytes", type=lambda s: int(s, 0), help="test this much DRAM (default: all of it)")
    parser.add_argument("--skip-console", action="store_true", help="do not read the BIOS console first")
    parser.add_argument("--skip-dram", action="store_true")
    parser.add_argument("--skip-p2", action="store_true")
    args = parser.parse_args()
    csr_json = json.loads(args.csr.read_text())
    carrier = args.carrier or carrier_of()

    report = {"carrier": carrier}
    with Bar0(args.bdf) as bus:
        csr = Csr(bus, csr_json)
        ident = read_ident(csr, csr_json)
        print(f"     running: {ident} (carrier {carrier})", flush=True)
        report["ident"] = ident
        if not args.skip_console:
            console = drain_console(csr)
            print("     BIOS console:\n" + "\n".join("       " + line for line in console.splitlines()), flush=True)
        if not args.skip_dram:
            report["dram"] = dram(csr, args.dram_bytes)
        if not args.skip_p2:
            p2(csr, carrier)
    if args.uart:
        uart(args.uart, ident)
    print(json.dumps(report))
    ok = all(results)
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
