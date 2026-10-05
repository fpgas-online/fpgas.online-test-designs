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
    label_fields = ("serial",)
    port = "/dev/serial0"
    flash_note = "not read: every verify rewrites the user image by DFU"
    # #135: seen on a Pi 3B+ on 2026-10-05: the Fomu left USB 36 s into the boot, when the check loaded its
    # design, and the next boot, a reboot, reported it missing.
    gone_after_check = ("the check's own test design has no USB, so a Fomu that has been checked is off USB until "
                        "it is power-cycled: power-cycle the Pi (a reboot is not enough)")  # fmt: skip
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-fomu/kosagi_fomu_evt.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "fomu", "--skip-banner"], "verify": True},
        "spiflash": {"artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "fomu"]},
        "pmod": {"artifact": "gpio-loopback-fomu-{v}/kosagi_fomu_evt.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "fomu"], "pre": PMOD_PRE},
        "pin-id": {"artifact": "pmod-pin-id-fomu-{v}/kosagi_fomu_evt.bin", "script": "identify_pmod_pins.py",
                   "args": [], "pre": PMOD_PRE},
    }  # fmt: skip

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "fomu", bitstream]


BOARD = Fomu()
