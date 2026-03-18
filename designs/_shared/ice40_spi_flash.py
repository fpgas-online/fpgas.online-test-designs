"""Minimal SPI Flash bitbang peripheral for iCE40 FPGAs.

Unlike S7SPIFlash (which uses the Xilinx STARTUPE2 primitive), this module
directly drives the SPI pins as regular I/O — suitable for iCE40 where the
SPI flash configuration pins become standard GPIO after FPGA boot.

CSR layout (from the spiflash CSR base address):

    +0x00  bitbang  (read/write)  bit 0 = MOSI, bit 1 = CLK, bit 2 = CS_N
    +0x04  miso     (read-only)   bit 0 = MISO

The firmware controls SPI transactions by toggling these bits directly.
"""

from litex.gen import LiteXModule
from litex.soc.interconnect.csr import *
from migen import *


class Ice40SPIFlash(LiteXModule):
    """Bitbang SPI Flash controller for iCE40.

    Provides direct CPU control over SPI flash pins via two CSR registers.
    No hard IP or vendor-specific primitives required.

    Parameters
    ----------
    pads : Record
        Platform pads with ``cs_n``, ``clk``, ``mosi``, ``miso`` subsignals.
        Obtained via ``platform.request("spiflash")``.
    """
    def __init__(self, pads):
        self._bitbang = CSRStorage(3, description="SPI Bitbang Control", fields=[
            CSRField("mosi", size=1, offset=0, description="Master Out Slave In"),
            CSRField("clk",  size=1, offset=1, description="SPI Clock"),
            CSRField("cs_n", size=1, offset=2, description="Chip Select (active low)",
                     reset=1),
        ])
        self._miso = CSRStatus(1, description="SPI MISO", fields=[
            CSRField("miso", size=1, offset=0, description="Master In Slave Out"),
        ])

        self.comb += [
            pads.cs_n.eq(self._bitbang.fields.cs_n),
            pads.clk.eq(self._bitbang.fields.clk),
            pads.mosi.eq(self._bitbang.fields.mosi),
            self._miso.fields.miso.eq(pads.miso),
        ]
