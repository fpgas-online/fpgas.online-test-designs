"""
SPI Flash ID test design-specific helpers.

Provides the SPI flash integration used by both the Arty and NeTV2 targets.
"""

from designs._shared.s7_spi_flash import S7BitbangSPIFlash


def add_spi_flash(soc, platform) -> None:
    """Add a bitbang SPI Flash peripheral to *soc*.

    Uses S7BitbangSPIFlash which has the same CSR layout as
    Ice40SPIFlash (bitbang + miso), but routes the clock through
    STARTUPE2 for Xilinx 7-series configuration flash access.

    The CSR group is named ``spiflash`` so the firmware can resolve
    the bitbang/miso register addresses from the CSR map.
    """
    soc.submodules.spiflash = S7BitbangSPIFlash(
        pads=platform.request("spiflash"),
    )
    soc.add_csr("spiflash")
