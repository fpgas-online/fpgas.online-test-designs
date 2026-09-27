"""Fomu EVT (iCE40UP5K): found by foboot's DFU bootloader on USB, which is there from power-up until a design is
loaded; loaded with openFPGALoader over DFU, which writes the design into the flash's user image and boots it.

So the boot check has room for one test (the next load needs the bootloader, which needs a power cycle:
verify_hardware.py PoE-cycles the Pi between tests), and the flash cannot be part of the state, since every
verify rewrites it. The state is the bootloader's USB serial number."""

from typing import ClassVar

from ..testbench import TestBoard

PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]


class Fomu(TestBoard):
    name = slug = "fomu"
    title = "Fomu EVT"
    doc = "fomu-evt.md"
    usb = (("1209", "5bf0"),)
    variants: ClassVar[dict] = {"evt": "evt"}
    port = "/dev/serial0"
    flash_note = "not read: every verify rewrites the user image by DFU"
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-fomu/kosagi_fomu_evt.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "fomu", "--skip-banner"], "verify": True},
        "spiflash": {"artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "fomu"]},
        "pmod": {"artifact": "gpio-loopback-fomu-{v}/top.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "fomu"], "pre": PMOD_PRE},
        "pin-id": {"artifact": "pmod-pin-id-fomu-{v}/top.bin", "script": "identify_pmod_pins.py", "args": [],
                   "pre": PMOD_PRE},
    }  # fmt: skip

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "fomu", bitstream]


BOARD = Fomu()
