"""TT FPGA Demo Board (iCE40UP5K behind an RP2350): found by the RP2350 on USB, loaded through it (tt_fpga_program.py,
over mpremote). The FPGA's UART reaches the Pi only through the RP2350, so the UART and SPI-flash tests run
through tt_test_wrapper.py's bridge, which loads the design too.

Every load writes the bitstream to the RP2350's filesystem, so the flash cannot be part of the state; the state
is the RP2350's USB serial number. Loading needs mpremote (micropython-mpremote: in trixie, and only
bookworm-backports for bookworm)."""

import sys
from typing import ClassVar

from .. import host_tests
from ..testbench import TestBoard

PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]


class TTFPGA(TestBoard):
    name = "tt"
    slug = "tt-fpga"  # fpgas-online-tt is the TT site's own package
    title = "TT FPGA Demo Board"
    doc = "tt-fpga.md"
    usb = (("2e8a", None),)  # any Raspberry Pi USB product: the RP2350 running MicroPython
    variants: ClassVar[dict] = {"tt-fpga": "tt-fpga"}
    port = "/dev/ttyACM0"
    flash_note = "not read: every verify rewrites the bitstream on the RP2350"
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-tt-fpga/tt_fpga_platform.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "tt", "--skip-banner"], "verify": True,
                 "runner": "tt-bridge"},
        "spiflash": {"artifact": "spiflash-test-tt-fpga/tt_fpga_platform.bin", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "tt"], "verify": True, "runner": "tt-bridge"},
        "pmod": {"artifact": "gpio-loopback-{v}/top.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "tt"], "pre": PMOD_PRE, "program_args": ["--gpio-release"]},
        "pin-id": {"artifact": "pmod-pin-id-{v}/top.bin", "script": "identify_pmod_pins.py", "args": [],
                   "pre": PMOD_PRE, "program_args": ["--gpio-release"]},
    }  # fmt: skip

    def program_argv(self, bitstream, host, test):
        extra = self.tests.get(test, {}).get("program_args", [])
        return [sys.executable, host_tests.path("tt_fpga_program.py"), host["port"], bitstream, *extra]


BOARD = TTFPGA()
