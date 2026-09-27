"""Digilent Arty A7 (XC7A35T): found by its FT2232H on USB (JTAG on interface 0, the UART on interface 1),
loaded with openFPGALoader. Its flash (the boot image region) is read back with openFPGALoader's SPI-over-JTAG
bridge, which openFPGALoader loads into SRAM for the purpose."""

from typing import ClassVar

from ..testbench import TestBoard

PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]  # the PMOD HAT's pins are the Pi's SPI0 too


class Arty(TestBoard):
    name = slug = "arty"
    title = "Digilent Arty A7"
    doc = "arty-a7.md"
    usb = (("0403", "6010"),)
    variants: ClassVar[dict] = {"a7-35": "a7-35t"}
    port = "/dev/ttyUSB1"
    flash_region: ClassVar[dict] = {"a7-35": 0x220000}  # an XC7A35T .bit is 2,192,123 bytes
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-arty/digilent_arty.bit", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        "ddr": {"artifact": "ddr-test-arty/digilent_arty.bit", "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        "spiflash": {"artifact": "spiflash-test-arty/digilent_arty.bit", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "arty"], "verify": True},
        "ethernet": {"artifact": "ethernet-test-arty-{v}/digilent_arty.bit", "script": "test_ethernet.py",
                     "args": ["--board", "arty", "--uart-port", "{port}"]},
        "pmod": {"artifact": "gpio-loopback-arty-{v}/top.bit", "script": "test_pmod_loopback.py",
                 "args": ["--board", "arty"], "pre": PMOD_PRE},
        "pin-id": {"artifact": "pmod-pin-id-arty-{v}/top.bit", "script": "identify_pmod_pins.py", "args": [],
                   "pre": PMOD_PRE},
    }  # fmt: skip

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "arty", bitstream]

    def flash_dump_argv(self, host, variant, size, out):
        return ["openFPGALoader", "-b", "arty", "--dump-flash", "--file-size", str(size), out]


BOARD = Arty()
