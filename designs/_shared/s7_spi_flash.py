"""Bitbang SPI Flash peripheral for Xilinx 7-Series FPGAs.

Uses the same CSR layout as Ice40SPIFlash (bitbang + miso registers),
but routes the SPI clock through the STARTUPE2 primitive — required
because the configuration SPI flash clock pin is not available as
regular I/O on 7-series parts.

CSR layout (identical to Ice40SPIFlash):

    +0x00  bitbang  (read/write)  bit 0 = MOSI, bit 1 = CLK, bit 2 = CS_N
    +0x04  miso     (read-only)   bit 0 = MISO

This allows the same RV32I firmware to work on both iCE40 and 7-series.
"""

from migen import *

from litex.gen import LiteXModule
from litex.soc.interconnect.csr import *


class S7BitbangSPIFlash(LiteXModule):
    """Bitbang SPI Flash controller for Xilinx 7-Series.

    Parameters
    ----------
    pads : Record
        Platform pads with ``cs_n``, ``mosi``, ``miso`` subsignals
        (and optionally ``vpp``, ``hold``).
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

        # Route SPI clock through STARTUPE2 (configuration flash clock).
        self.specials += Instance("STARTUPE2",
            i_CLK       = 0,
            i_GSR       = 0,
            i_GTS       = 0,
            i_KEYCLEARB = 0,
            i_PACK      = 0,
            i_USRCCLKO  = self._bitbang.fields.clk,
            i_USRCCLKTS = 0,
            i_USRDONEO  = 1,
            i_USRDONETS = 1,
        )

        # Direct pin connections for CS, MOSI, MISO.
        if hasattr(pads, "cs_n"):
            self.comb += pads.cs_n.eq(self._bitbang.fields.cs_n)
        self.comb += [
            pads.mosi.eq(self._bitbang.fields.mosi),
            self._miso.fields.miso.eq(pads.miso),
        ]

        # Hold WP and HOLD pins high (inactive).
        if hasattr(pads, "vpp"):
            pads.vpp.reset = 1
        if hasattr(pads, "hold"):
            pads.hold.reset = 1
