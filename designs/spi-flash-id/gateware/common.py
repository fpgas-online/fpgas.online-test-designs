"""
SPI Flash ID test design-specific helpers.

Provides the SPI flash integration used by both the Arty and NeTV2 targets.
"""

from litex.soc.cores.spi_flash import S7SPIFlash


def add_spi_flash(soc, platform, sys_clk_freq: int) -> None:
    """Add an S7SPIFlash peripheral to *soc* with bitbang access.

    The submodule is named ``spi_id`` (not ``spiflash``) to avoid
    generating ``CSR_SPIFLASH_CORE_BASE`` which would trigger
    compilation of liblitespi's memory-mapped flash code that expects
    constants (``SPIFLASH_PHY_FREQUENCY``, ``SPIFLASH_BASE``, etc.)
    that are only provided by the LiteSPI memory-mapped flash setup.
    """
    soc.submodules.spi_id = S7SPIFlash(
        pads=platform.request("spiflash"),
        sys_clk_freq=sys_clk_freq,
    )
    soc.add_csr("spi_id")
