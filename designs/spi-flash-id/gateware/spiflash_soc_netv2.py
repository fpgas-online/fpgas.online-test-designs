#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Kosagi NeTV2.

Builds a minimal SoC with CPU + UART + bitbang SPI Flash.  Custom RV32I
firmware reads the JEDEC ID via command 0x9F and prints the result.

NeTV2 SPI Flash: Quad SPI, CS=T19.  Clock routed via STARTUPE2.
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_netv2.py --toolchain openxc7 --build

The bitstream is written to: designs/spi-flash-id/build/netv2/gateware/netv2_spiflash_test.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from common import add_spi_flash
from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms.kosagi_netv2 import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

kB = 1024


# CRG (Clock Reset Generator) ---------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal CRG for NeTV2: generates sys clock from the 50 MHz on-board oscillator."""
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk.
        clk50 = platform.request("clk50")

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-100", toolchain="openxc7", sys_clk_freq=50e6, **kwargs):
        platform = Platform(variant=variant, toolchain=toolchain)

        # Fix dashed device name for openXC7 compatibility.
        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)

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
    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for NeTV2")
    target_group = parser.target_group
    target_group.add_argument("--variant", default="a7-100",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)")
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident          = "fpgas-online SPI Flash Test SoC -- NeTV2",
        uart_baudrate  = 115200,
        output_dir     = default_build_dir(__file__, "netv2"),
    )
    args = parser.parse_args()

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **parser.soc_argdict,
    )

    ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder_args = dict(parser.builder_argdict)
    builder_args["compile_software"] = False
    builder = Builder(soc, **builder_args)

    from designs._shared.ice40_firmware import install_spiflash_firmware
    ident = "fpgas-online SPI Flash Test SoC -- NeTV2"
    install_spiflash_firmware(soc, ident)

    builder.build(run=args.build)


if __name__ == "__main__":
    main()
