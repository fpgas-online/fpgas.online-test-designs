#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Kosagi NeTV2.

NeTV2 SPI Flash: Quad SPI, CS=T19.
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_netv2.py --toolchain openxc7 --build

The bitstream is written to: designs/spi-flash-id/build/netv2/gateware/netv2_spiflash_test.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_netv2 import Platform

from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import fix_openxc7_device_name, ensure_chipdb_symlink
from designs._shared.yosys_workarounds import patch_yosys_template

from common import add_spi_flash


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for NeTV2")
    target_group = parser.target_group
    target_group.add_argument("--variant", default="a7-35",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)")
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident          = "fpgas-online SPI Flash Test SoC -- NeTV2",
        uart_baudrate  = 115200,
        output_dir     = default_build_dir(__file__, "netv2"),
    )
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    fix_openxc7_device_name(platform)
    ensure_chipdb_symlink(platform)
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
