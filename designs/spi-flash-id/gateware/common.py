"""
SPI Flash ID test design-specific helpers.

Provides the SPI flash integration used by both the Arty and NeTV2 targets.
"""

from litex.soc.cores.spi_flash import S7SPIFlash


def add_spi_flash(soc, platform, sys_clk_freq: int) -> None:
    """Add an S7SPIFlash peripheral to *soc* with bitbang access.

    S7SPIFlash uses a simple SPIMaster — it is *not* the LiteSPI
    memory-mapped flash core.  However, LiteX always compiles
    ``liblitespi`` as part of the BIOS, and since LiteX 2025.x the
    guard changed from ``CSR_SPIFLASH_CORE_BASE`` to
    ``CSR_SPIFLASH_BASE``.  The latter IS defined for any CSR group
    named "spiflash", so the liblitespi code compiles and references
    constants (``SPIFLASH_MODULE_NAME``, ``SPIFLASH_BASE``, etc.)
    that S7SPIFlash does not normally provide.

    We add the missing constants here so the BIOS compiles cleanly.
    ``SPIFLASH_BASE`` is pointed at address 0 (ROM, always readable)
    since S7SPIFlash has no memory-mapped flash region.  Frequency
    calibration is skipped (no PHY clock divisor CSR exists).
    """
    soc.submodules.spiflash = S7SPIFlash(
        pads=platform.request("spiflash"),
        sys_clk_freq=sys_clk_freq,
    )
    soc.add_csr("spiflash")

    # Satisfy liblitespi compilation — see docstring above.
    soc.add_constant("SPIFLASH_MODULE_NAME", "S7SPIFlash")
    soc.add_constant("SPIFLASH_BASE", 0)
    soc.add_constant("SPIFLASH_PHY_FREQUENCY", int(sys_clk_freq) // 4)
    soc.add_constant("SPIFLASH_SKIP_FREQ_INIT")
