"""
Shared helpers for SPI Flash ID test SoC targets.

Provides the Yosys scopeinfo workaround and SPI flash integration
used by both the Arty and NeTV2 targets.
"""

import os

from litex.soc.cores.spi_flash import S7SPIFlash


def default_build_dir(here: str, board: str) -> str:
    """Return the default build output directory for *board*.

    *here* should be ``os.path.dirname(os.path.abspath(__file__))`` from
    the calling module so that the path is relative to the source tree
    rather than the current working directory.
    """
    return os.path.join(here, "..", "build", board)


# Workaround: newer Yosys emits $scopeinfo cells that older nextpnr-xilinx
# cannot place. Strip them after synthesis by using a custom Yosys template.
YOSYS_TEMPLATE_SCOPEINFO_FIX = [
    "verilog_defaults -push",
    "verilog_defaults -add -defer",
    "{read_files}",
    "verilog_defaults -pop",
    'attrmap -tocase keep -imap keep="true" keep=1 -imap keep="false" keep=0 -remove keep=0',
    "{yosys_cmds}",
    "synth_{target} {synth_opts} -top {build_name}",
    "delete t:$scopeinfo",
    "write_{write_fmt} {write_opts} {output_name}.{synth_fmt}",
]


def add_spi_flash(soc, platform, sys_clk_freq: int) -> None:
    """Add an S7SPIFlash peripheral to *soc* with bitbang access."""
    soc.submodules.spiflash = S7SPIFlash(
        pads=platform.request("spiflash"),
        sys_clk_freq=sys_clk_freq,
    )
    soc.add_csr("spiflash")
