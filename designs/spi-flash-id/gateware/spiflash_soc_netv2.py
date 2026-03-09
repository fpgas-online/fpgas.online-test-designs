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

import os

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_netv2 import Platform

from common import (
    YOSYS_TEMPLATE_SCOPEINFO_FIX,
    add_spi_flash,
    default_build_dir,
)

_HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for NeTV2")
    target_group = parser.target_group
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident          = "fpgas-online SPI Flash Test SoC -- NeTV2",
        uart_baudrate  = 115200,
        output_dir     = default_build_dir(_HERE, "netv2"),
    )
    args = parser.parse_args()

    platform = Platform(toolchain=args.toolchain)
    # Fix device string: NeTV2 platform uses "xc7a35t-fgg484-2" but the openxc7
    # toolchain (prjxray-db/bbaexport) expects "xc7a35tfgg484-2" (no hyphen
    # between the device family and package).
    platform.device = platform.device.replace("t-fgg", "tfgg")
    sys_clk_freq = int(args.sys_clk_freq)

    platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_SCOPEINFO_FIX)

    soc = SoCCore(
        platform       = platform,
        clk_freq       = sys_clk_freq,
        **parser.soc_argdict,
    )

    add_spi_flash(soc, platform, sys_clk_freq)

    builder = Builder(soc, **parser.builder_argdict)
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
