#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SPI Flash access. The BIOS prints
the SPI flash identification on boot. Additionally, custom firmware can
be loaded to explicitly read the JEDEC ID via command 0x9F.

Arty A7 SPI Flash: Quad SPI, CS=L13.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --toolchain openxc7 --build

The bitstream is written to: designs/spi-flash-id/build/arty/gateware/arty_spiflash_test.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.digilent_arty import Platform

from designs._shared.build_helpers import default_build_dir
from designs._shared.yosys_workarounds import patch_yosys_template

from common import add_spi_flash


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

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = platform,
        clk_freq       = sys_clk_freq,
        **parser.soc_argdict,
    )

    patch_yosys_template(soc)
    add_spi_flash(soc, platform, sys_clk_freq)

    builder = Builder(soc, **parser.builder_argdict)
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
