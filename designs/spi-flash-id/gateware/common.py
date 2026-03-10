"""
SPI Flash ID test design-specific helpers.

Provides the SPI flash integration used by both the Arty and NeTV2 targets.
"""

from litex.soc.cores.spi_flash import S7SPIFlash


def add_spi_flash(soc, platform, sys_clk_freq: int) -> None:
    """Add an S7SPIFlash peripheral to *soc* with bitbang access."""
    soc.submodules.spiflash = S7SPIFlash(
        pads=platform.request("spiflash"),
        sys_clk_freq=sys_clk_freq,
    )
    soc.add_csr("spiflash")
