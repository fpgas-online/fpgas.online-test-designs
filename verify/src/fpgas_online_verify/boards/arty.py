"""Digilent Arty A7 (XC7A35T): found by its FT2232H on USB (JTAG on interface 0, the UART on interface 1),
loaded with openFPGALoader. The check reads its whole IDCODE over that JTAG first (openFPGALoader's raw scan),
which must be an XC7A35T, then its device DNA (openFPGALoader --read-dna, over the same cable), then its SPI
flash's identity (openFPGALoader --flash-info-json), before any test. That and the readback of its flash (the
boot image region) go through openFPGALoader's SPI-over-JTAG bridge, which openFPGALoader loads into SRAM for
the purpose."""

from typing import ClassVar

from .. import idcode
from ..testbench import TestBoard

PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]  # the PMOD HAT's pins are the Pi's SPI0 too


class Arty(TestBoard):
    name = slug = "arty"
    title = "Digilent Arty A7"
    doc = "arty-a7.md"
    usb = (("0403", "6010"),)
    variants: ClassVar[dict] = {"a7-35": "a7-35t"}
    idcodes: ClassVar[dict] = {"a7-35": 0x0362D093}  # XC7A35T
    # and flash_uid or flash_uid_note, as flash_uid_state says (identify.missing; rpi-hwid's label needs them)
    label_fields = ("serial", "idcode", "dna", "flash_jedec", "flash_uid_state")
    port = "/dev/ttyUSB1"
    flash_region: ClassVar[dict] = {"a7-35": 0x220000}  # an XC7A35T .bit is 2,192,123 bytes
    jtag_loads_7_series = True  # openFPGALoader's `done` line says whether it loaded (#300)
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-arty/digilent_arty.bit", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        "ddr": {"artifact": "ddr-test-arty/digilent_arty.bit", "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        "flash": {"artifact": "spiflash-test-arty/digilent_arty.bit", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        # The Pi's USB Ethernet adapter cabled to the Arty's RJ45 (a Pi 4's own port is on-board, not USB).
        "ethernet": {"artifact": "ethernet-test-arty-{v}/digilent_arty.bit", "script": "test_ethernet.py",
                     "args": ["--board", "arty", "--uart-port", "{port}"], "verify": True, "says": "ETHERNET:"},
        "pmod": {"artifact": "gpio-loopback-arty-{v}/digilent_arty.bit", "script": "test_pmod_loopback.py",
                 "args": ["--board", "arty"], "pre": PMOD_PRE},
        # The Pmod HAT cabling, against identify_pmod_pins.BOARDS["arty"] (HAT JA/JB/JC -> Arty JA/JB/JC). It was
        # `pin-id` until 15 Oct 2026 (#340): `wiring` is the cabling test's name on every board.
        "wiring": {"artifact": "pmod-pin-id-arty-{v}/digilent_arty.bit", "script": "identify_pmod_pins.py",
                   "args": ["--board", "arty"], "pre": PMOD_PRE, "verify": True, "says": "PIN-ID:"},
    }  # fmt: skip

    abouts: ClassVar[dict] = {
        "jtag": "over its FT2232H, the JTAG IDCODE is an XC7A35T's and the device DNA reads",
        "uart": "the UART test design's BIOS banner arrives and printable text echoes back",
        "ddr": "the LiteX BIOS calibrates the DDR3 and its memory test passes",
        "flash": "a test design reads the SPI flash's JEDEC ID",
        "ethernet": "the design answers ARP and ping through the Pi's USB Ethernet adapter cabled to its RJ45",
        "wiring": (
            "each Pmod HAT wire but the six on the shared JA/JB pins carries the FPGA pin the cabling map puts there"
        ),
        "pmod": "the Pmod loopback wiring reads back (-debug only)",
    }

    def idcode_argv(self, host):
        return ["openFPGALoader", "-b", "arty", "--detect", *idcode.OPENFPGALOADER_RAW_ARGS]

    def dna_argv(self, host):
        return ["openFPGALoader", "-b", "arty", "--read-dna"]

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "arty", bitstream]

    def flash_argv(self, host, variant):
        """The bridge for the board's part (-b arty names it): the flash's readback and its identity."""
        return ["openFPGALoader", "-b", "arty"]


BOARD = Arty()
