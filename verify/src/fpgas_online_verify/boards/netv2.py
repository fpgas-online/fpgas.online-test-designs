"""Kosagi NeTV2 (XC7A35T or XC7A100T, FGG484): no USB, so found by a JTAG scan over the Pi's GPIO header,
whose IDCODE also says which part is fitted and so which variant's bitstreams to use.

JTAG on the header (docs/hardware/netv2.md): TCK GPIO4, TMS GPIO17, TDI GPIO27, TDO GPIO22. On a Pi 3/4,
openocd's bcm2835gpio driver (fast; needs the SoC's peripheral base, from the device tree); on a Pi 5,
openFPGALoader's rp1pio cable, which only the fpgas.online builds of openFPGALoader have.

The scan drives GPIO 4, 17 and 27, so fpgas-verify only scans when this board is configured, or, with
`fpga-board = auto`, when no other board was found without driving anything.

The flash readback uses openFPGALoader's SPI-over-JTAG bridge for the part (libgpiod on a Pi 3/4, rp1pio on a
Pi 5). Debian bookworm's openfpgaloader has no bridge for the XC7A35T-FGG484 (trixie's has); the fpgas.online
builds have both.
"""

import contextlib
import re
from typing import ClassVar

from ..core import Problem, host_facts, is_pi, is_pi5, peripheral_base, run
from ..testbench import TestBoard

TCK, TMS, TDI, TDO = 4, 17, 27, 22
PINS = f"{TDI}:{TDO}:{TCK}:{TMS}"  # openFPGALoader's order
# Xilinx IDCODEs with the silicon revision nibble masked off.
PARTS = {0x0362D093: "a7-35", 0x03631093: "a7-100"}
FPGA_PART = {"a7-35": "xc7a35tfgg484", "a7-100": "xc7a100tfgg484"}


def parse_idcodes(text):
    """IDCODEs from openocd's `tap/device found: 0x...` or openFPGALoader's `idcode 0x...` lines."""
    return [int(m, 16) for m in re.findall(r"(?:device found:|idcode)\s*(0x[0-9a-fA-F]{1,8})", text)]


def part_of(idcodes):
    """(variant or None, the first IDCODE seen or None)."""
    for code in idcodes:
        if code & 0x0FFFFFFF in PARTS:
            return PARTS[code & 0x0FFFFFFF], code
    return None, (idcodes[0] if idcodes else None)


class NeTV2(TestBoard):
    name = slug = "netv2"
    title = "Kosagi NeTV2"
    doc = "netv2.md"
    probes = True
    variants: ClassVar[dict] = {"a7-35": "a7-35t", "a7-100": "a7-100t"}
    port = "/dev/ttyAMA0"
    flash_region: ClassVar[dict] = {
        "a7-35": 0x220000,
        "a7-100": 0x3B0000,
    }  # a .bit for each part: 2,192,122 / 3,825,899 bytes
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-netv2-{v}/kosagi_netv2.bit", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "netv2", "--skip-banner"], "verify": True},
        "ddr": {"artifact": "ddr-test-netv2-{v}/kosagi_netv2.bit", "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "netv2"], "verify": True},
        "spiflash": {"artifact": "spiflash-test-netv2-{v}/kosagi_netv2.bit", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "netv2"], "verify": True},
        "ethernet": {"artifact": "ethernet-test-netv2-{v}/kosagi_netv2.bit", "script": "test_ethernet.py",
                     "args": ["--board", "netv2", "--uart-port", "{port}"]},
        "pmod": {"artifact": "gpio-loopback-netv2-{v}/top.bit", "script": "test_pmod_loopback.py",
                 "args": ["--board", "netv2"]},
        "pin-id": {"artifact": "pmod-pin-id-netv2-{v}/top.bit", "script": "identify_pmod_pins.py", "args": []},
    }  # fmt: skip

    def facts(self, port=None):
        host = {**host_facts(), "port": port or self.port, "base": None}
        if is_pi(host["model"]) and not is_pi5(host["model"]):
            with contextlib.suppress(Problem):  # openocd_argv says so if it is needed
                host["base"] = peripheral_base()
        return host

    def openocd_argv(self, host, commands):
        if host.get("base") is None:
            raise Problem("error", "cannot read the SoC's peripheral base from the device tree: cannot drive JTAG")
        adapter = (
            "adapter driver bcm2835gpio; "
            f"bcm2835gpio peripheral_base {host['base']:#x}; "
            "bcm2835gpio speed_coeffs 100000 5; "
            f"bcm2835gpio jtag_nums {TCK} {TMS} {TDI} {TDO}; "
            "adapter speed 1000; transport select jtag"
        )
        return ["openocd", "-c", adapter, "-f", "cpld/xilinx-xc7.cfg", "-c", commands]

    def probe(self, host, runner=run):
        if not is_pi(host["model"]):
            return []  # no GPIO header to scan
        if is_pi5(host["model"]):
            argv = ["openFPGALoader", "-c", "rp1pio", "--pins", PINS, "--detect"]
        else:
            argv = self.openocd_argv(host, "init; exit")
        _, text = runner(argv, 60)
        variant, code = part_of(parse_idcodes(text))
        if code is None:
            return []
        if variant is None:
            raise Problem("error", f"the JTAG chain answers with IDCODE {code:#010x}, which is no NeTV2 part")
        return [{"variant": variant, "idcode": f"{code:#010x}"}]

    def program_argv(self, bitstream, host, test):
        if is_pi5(host["model"]):
            return ["openFPGALoader", "-c", "rp1pio", "--pins", PINS, bitstream]
        return self.openocd_argv(host, f"init; pld load 0 {bitstream}; exit")

    def flash_dump_argv(self, host, variant, size, out):
        cable = ["-c", "rp1pio"] if is_pi5(host["model"]) else ["--cable", "libgpiod"]
        return ["openFPGALoader", *cable, "--pins", PINS, "--fpga-part", FPGA_PART[variant],
                "--dump-flash", "--file-size", str(size), out]  # fmt: skip

    def uart_pre(self, host):
        steps = super().uart_pre(host)
        if is_pi5(host["model"]):  # GPIO14/15 to UART0
            steps += [["pinctrl", "set", "14", "a4"], ["pinctrl", "set", "15", "a4"]]
        return steps


BOARD = NeTV2()
