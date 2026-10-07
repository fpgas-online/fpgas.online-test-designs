"""Kosagi NeTV2 (XC7A35T or XC7A100T, FGG484): no USB, so found by a JTAG scan over the Pi's GPIO header,
whose IDCODE also says which part is fitted and so which variant's bitstreams to use.

JTAG on the header (docs/hardware/netv2.md): TCK GPIO4, TMS GPIO17, TDI GPIO27, TDO GPIO22. On a Pi 3/4,
openocd's bcm2835gpio driver (fast; needs the SoC's peripheral base, from the device tree); on a Pi 5,
openFPGALoader's rp1pio cable, which only the fpgas.online builds of openFPGALoader have.

The scan drives GPIO 4, 17 and 27, so fpgas-verify only scans when this board is configured, or, with
`fpga-board = auto`, when no other board was found without driving anything. The JTAG pins' state is read with
pinctrl before the scan and put back after it (an output as an input: openocd and openFPGALoader leave theirs
driven); without pinctrl to do that, the scan is not run.

The device DNA is read with `openFPGALoader --read-dna` on the same pins (rp1pio on a Pi 5, libgpiod on a Pi 3/4,
as the flash readback), its pins put back the same way.

The flash readback uses openFPGALoader's SPI-over-JTAG bridge for the part (libgpiod on a Pi 3/4, rp1pio on a
Pi 5). Debian bookworm's openfpgaloader has no bridge for the XC7A35T-FGG484 (trixie's has); the fpgas.online
builds have both.
"""

import contextlib
from typing import ClassVar

from .. import idcode
from ..core import Problem, host_facts, is_pi, is_pi5, peripheral_base, pin_states, restore_pins, run, tail
from ..testbench import TestBoard

TCK, TMS, TDI, TDO = 4, 17, 27, 22
PINS = f"{TDI}:{TDO}:{TCK}:{TMS}"  # openFPGALoader's order
JTAG_GPIOS = (TCK, TMS, TDI, TDO)
# Each part's Xilinx IDCODE at version 0; any version of the part is that variant.
PARTS = {0x0362D093: "a7-35", 0x03631093: "a7-100"}
FPGA_PART = {"a7-35": "xc7a35tfgg484", "a7-100": "xc7a100tfgg484"}


def part_of(idcodes):
    """(variant or None, the first whole IDCODE seen or None)."""
    for code in idcodes:
        if idcode.masked(code) in PARTS:
            return PARTS[idcode.masked(code)], code
    return None, (idcodes[0] if idcodes else None)


class NeTV2(TestBoard):
    name = slug = "netv2"
    title = "Kosagi NeTV2"
    doc = "netv2.md"
    probes = True
    variants: ClassVar[dict] = {"a7-35": "a7-35t", "a7-100": "a7-100t"}
    idcodes: ClassVar[dict] = {variant: code for code, variant in PARTS.items()}
    label_fields = ("idcode", "dna", "flash_jedec", "flash_uid")
    port = "/dev/ttyAMA0"
    flash_region: ClassVar[dict] = {
        "a7-35": 0x220000,
        "a7-100": 0x3B0000,
    }  # a .bit for each part: 2,192,122 / 3,825,899 bytes
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-netv2-{v}/kosagi_netv2.bit", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "netv2", "--skip-banner"], "verify": True},
        # The BIOS prints its SDRAM calibration once, at start, before the memtest, and test_ddr.py needs both:
        # opened after the load, the Pi's own UART has already dropped the calibration (every Welland NeTV2,
        # 2026-10-06). So it listens from before the load, and its timeout covers the load, as spiflash's does.
        "ddr": {"artifact": "ddr-test-netv2-{v}/kosagi_netv2.bit", "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "netv2", "--timeout", "180"], "verify": True,
                "listen": True},
        # It prints its JEDEC ID once, at start, onto the Pi's own UART, so it listens from before the load
        # (listen.py), and its timeout covers the load too (openocd on a Pi 3 takes a minute or more).
        "spiflash": {"artifact": "spiflash-test-netv2-{v}/kosagi_netv2.bit", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "netv2", "--timeout", "180"], "verify": True,
                     "listen": True},
        "ethernet": {"artifact": "ethernet-test-netv2-{v}/kosagi_netv2.bit", "script": "test_ethernet.py",
                     "args": ["--board", "netv2", "--uart-port", "{port}"]},
        "pmod": {"artifact": "gpio-loopback-netv2-{v}/kosagi_netv2.bit", "script": "test_pmod_loopback.py",
                 "args": ["--board", "netv2"]},
        "pin-id": {"artifact": "pmod-pin-id-netv2-{v}/kosagi_netv2.bit", "script": "identify_pmod_pins.py", "args": []},
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

    def idcode_argv(self, host):
        """openFPGALoader's raw scan on a Pi 5; OpenOCD prints the whole IDCODE as it is."""
        if is_pi5(host["model"]):
            return ["openFPGALoader", "-c", "rp1pio", "--pins", PINS, "--detect", *idcode.OPENFPGALOADER_RAW_ARGS]
        return self.openocd_argv(host, "init; exit")

    def probe(self, host, runner=run):
        if not is_pi(host["model"]):
            return []  # no GPIO header to scan
        try:
            saved = pin_states(runner, JTAG_GPIOS)
        except Problem as p:
            raise Problem("error", "the NeTV2's JTAG was not scanned: the state of its pins could not be read, so "
                                   f"it could not be put back: {p.reason}") from None  # fmt: skip
        argv = self.idcode_argv(host)
        try:
            rc, text = runner(argv, 60)
        finally:
            faults = restore_pins(runner, saved, exact=False)
        if faults:
            raise Problem("error", f"after the NeTV2's JTAG scan: {'; '.join(faults)}")
        codes = idcode.parse(text)
        variant, code = part_of(codes)
        if code is None:
            return []
        if variant is None:
            raise Problem("error", f"the JTAG chain answers with IDCODE {code:#010x}, which is no NeTV2 part")
        # The JTAG check (TestBoard.jtag) uses this scan: it fails it if the tool exited non-zero, and, with
        # every IDCODE on the chain kept, if the chain has more than the one device, as for the other boards.
        scan = {"tool": argv[0], "exit": rc, "output": idcode.scan_lines(text) if rc == 0 else tail(text, 6)}
        return [{"variant": variant, "idcode": f"{code:#010x}", "idcodes": [f"{c:#010x}" for c in codes],
                 "idcode_scan": scan}]  # fmt: skip

    def openfpgaloader_cable(self, host):
        """openFPGALoader's cable for the header's JTAG: rp1pio on a Pi 5, libgpiod on a Pi 3/4."""
        cable = ["-c", "rp1pio"] if is_pi5(host["model"]) else ["--cable", "libgpiod"]
        return ["openFPGALoader", *cable, "--pins", PINS]

    def dna_argv(self, host):
        return [*self.openfpgaloader_cable(host), "--read-dna"]

    @contextlib.contextmanager
    def jtag_driven(self, runner, faults):
        """The JTAG pins as pinctrl found them, put back after (an output as an input, as after the scan). Without
        their state, nothing is driven: a Problem."""
        try:
            saved = pin_states(runner, JTAG_GPIOS)
        except Problem as p:
            raise Problem("error", "the JTAG pins' state could not be read, so it could not be put back: "
                                   f"{p.reason}") from None  # fmt: skip
        try:
            yield
        finally:
            faults += restore_pins(runner, saved, exact=False)

    def program_argv(self, bitstream, host, test):
        if is_pi5(host["model"]):
            return ["openFPGALoader", "-c", "rp1pio", "--pins", PINS, bitstream]
        return self.openocd_argv(host, f"init; pld load 0 {bitstream}; exit")

    def flash_dump_argv(self, host, variant, size, out):
        return [*self.openfpgaloader_cable(host), "--fpga-part", FPGA_PART[variant],
                "--dump-flash", "--file-size", str(size), out]  # fmt: skip

    def uart_pre(self, host):
        steps = super().uart_pre(host)
        if is_pi5(host["model"]):  # GPIO14/15 to UART0
            steps += [["pinctrl", "set", "14", "a4"], ["pinctrl", "set", "15", "a4"]]
        return steps


BOARD = NeTV2()
