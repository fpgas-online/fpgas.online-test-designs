#!/usr/bin/env python3
"""Exercise the Acorn SoC's DRAM BIST and every P2 pin, over PCIe BAR0, on the Pi the board is wired to.

Needs the operational image of a release that has the BIST and the P2 switch (csr.json lists `dram_generator`,
`dram_checker` and `p2_serial`), no kernel driver bound to the board, and `pinctrl` (raspi-utils) for the Pi's
side of the P2 pins. Run as root:

    sudo python3 selftest.py --csr acorn-cle-215p-csr.json [--bdf 0001:01:00.0] [--uart /dev/ttyAMA0]

1. DRAM: write a PRBS pattern over the whole DRAM with `dram_generator`, read it back with `dram_checker`,
   and report the errors and both passes' bandwidth (bytes / (ticks / sys clock)).
2. P2: each of J2, K2, J5 and H5, driven low then high from the FPGA and read on the Pi, then driven from the
   Pi and read on the FPGA. J2/K2 are borrowed from the UART with `p2_serial`; J5/H5 are `p2_gpio`.
3. The switch's own timeout: switch to GPIO with a 200 ms timeout and see it come back to serial alone.
4. With `--uart`: the UARTBone answers on P2 afterwards, with the identifier BAR0 reads.

Every Pi pin is put back as it was (`pinctrl get` before, `pinctrl set` after), and the switch is back on serial,
even when a step fails. Prints one line per check and exits 1 if any failed.

Self-contained (stdlib only) for the Pis' tmpfs root.
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

# Pi GPIO on the other end of each P2 ball (docs/wiring/acorn/wiring.toml; the same on the Pi 5 HAT and the
# Compute Blade), and where the FPGA side lives: (CSR module, bit).
P2 = {
    "J2": (14, "p2_serial", 0),
    "K2": (15, "p2_serial", 1),
    "J5": (3, "p2_gpio", 0),
    "H5": (4, "p2_gpio", 1),
}


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


# -- DRAM --------------------------------------------------------------------------------------------------


def _bist_pass(csr, core, base, length, timeout_s):
    csr[f"{core}_reset"] = 1
    csr[f"{core}_reset"] = 0
    csr[f"{core}_base"] = base
    csr[f"{core}_end"] = base + length
    csr[f"{core}_length"] = length
    csr[f"{core}_random"] = 1  # PRBS data, sequential addresses
    csr[f"{core}_start"] = 1
    deadline = time.monotonic() + timeout_s
    while not csr[f"{core}_done"]:
        if time.monotonic() > deadline:
            return None
        time.sleep(0.01)
    return csr[f"{core}_ticks"]


def dram(csr, length=None):
    """The whole DRAM in two halves: `length` and `end` are as wide as a DRAM address, so the full size
    does not fit them."""
    clk = csr.constants["config_clock_frequency"]
    size = csr.memories["main_ram"]["size"]
    length = length or size
    half = length // 2
    out = {"bytes": length, "sys_clk_hz": clk, "write_ticks": 0, "read_ticks": 0, "errors": 0}
    for base in (0, half):
        for core, what in (("dram_generator", "write"), ("dram_checker", "read")):
            ticks = _bist_pass(csr, core, base, half, timeout_s=30)
            if not check(f"dram {what} pass at {base:#x} finished", ticks is not None):
                return out
            out[f"{what}_ticks"] += ticks
        out["errors"] += csr["dram_checker_errors"]
    for what in ("write", "read"):
        out[f"{what}_MBps"] = round(length / (out[f"{what}_ticks"] / clk) / 1e6, 1)
    check(
        "dram bist",
        out["errors"] == 0,
        f"{length >> 20} MiB, {out['errors']} errors, write {out['write_MBps']} MB/s, read {out['read_MBps']} MB/s",
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


def p2(csr):
    saved = {gpio: pi_state(gpio) for gpio, _, _ in P2.values()}
    print(f"     Pi pins before: {saved}", flush=True)
    try:
        csr["p2_serial_timeout"] = 0  # this test switches back itself
        csr["p2_serial_mode"] = 1
        check("p2_serial switched to GPIO", csr["p2_serial_mode"] == 1)
        for ball, (gpio, module, bit) in P2.items():
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
        csr["p2_serial_timeout"] = 5000
    check("p2_serial back on serial", csr["p2_serial_mode"] == 0)
    print(f"     Pi pins after: { {gpio: pi_state(gpio) for gpio in saved} }", flush=True)

    csr["p2_serial_timeout"] = 200
    csr["p2_serial_mode"] = 1
    at_once = csr["p2_serial_mode"]
    time.sleep(0.5)
    later = csr["p2_serial_mode"]
    csr["p2_serial_mode"] = 0
    csr["p2_serial_timeout"] = 5000
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
    parser.add_argument("--dram-bytes", type=lambda s: int(s, 0), help="test this much DRAM (default: all of it)")
    parser.add_argument("--skip-dram", action="store_true")
    parser.add_argument("--skip-p2", action="store_true")
    args = parser.parse_args()
    csr_json = json.loads(args.csr.read_text())

    report = {}
    with Bar0(args.bdf) as bus:
        csr = Csr(bus, csr_json)
        ident = read_ident(csr, csr_json)
        print(f"     running: {ident}", flush=True)
        report["ident"] = ident
        if not args.skip_dram:
            report["dram"] = dram(csr, args.dram_bytes)
        if not args.skip_p2:
            p2(csr)
    if args.uart:
        uart(args.uart, ident)
    print(json.dumps(report))
    ok = all(results)
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
