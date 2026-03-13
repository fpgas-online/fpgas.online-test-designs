#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Digilent Arty A7.

Builds a minimal SoC with CPU + UART + bitbang SPI Flash.  Custom RV32I
firmware reads the JEDEC ID via command 0x9F and prints the result.

Arty A7 SPI Flash: Quad SPI, CS=L13.  Clock routed via STARTUPE2.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --toolchain openxc7 --build

The bitstream is written to: designs/spi-flash-id/build/arty/gateware/arty_spiflash_test.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *

from litex.gen import *

from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.digilent_arty import Platform

from designs._shared.build_helpers import default_build_dir
from designs._shared.yosys_workarounds import patch_yosys_template

from common import add_spi_flash

kB = 1024


# CRG (Clock Reset Generator) ---------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal CRG for Arty A7: generates sys clock from the 100 MHz on-board oscillator."""
    def __init__(self, platform, sys_clk_freq, with_rst=True):
        self.rst    = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk/Rst.
        clk100 = platform.request("clk100")
        rst    = ~platform.request("cpu_reset") if with_rst else 0

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(rst | self.rst)
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="vivado", sys_clk_freq=100e6, **kwargs):
        platform = Platform(variant=variant, toolchain=toolchain)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        kwargs["uart_name"] = "serial"
        kwargs["integrated_rom_size"]  = 1*kB
        kwargs["integrated_sram_size"] = 4*kB
        kwargs.setdefault("cpu_variant", "minimal")
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # SPI Flash (bitbang via STARTUPE2) ----------------------------------------------------
        add_spi_flash(self, platform)


# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for Arty A7")
    target_group = parser.target_group
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident          = "fpgas-online SPI Flash Test SoC -- Arty A7",
        uart_baudrate  = 115200,
        output_dir     = default_build_dir(__file__, "arty"),
    )
    args = parser.parse_args()

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **parser.soc_argdict,
    )

    patch_yosys_template(soc)

    builder_args = dict(parser.builder_argdict)
    builder_args["compile_software"] = False
    builder = Builder(soc, **builder_args)

    from designs._shared.ice40_firmware import install_spiflash_firmware
    ident = "fpgas-online SPI Flash Test SoC -- Arty A7"
    install_spiflash_firmware(soc, ident)

    builder.build(run=args.build)


if __name__ == "__main__":
    main()
