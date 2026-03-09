#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Digilent Arty A7.

Builds a minimal SoC with CPU + BIOS + UART. The BIOS automatically prints
an identification banner on boot and provides an interactive serial console
that echoes characters — this is all we need for the UART test.

Build command:
    uv run python designs/uart/gateware/uart_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/uart/build/arty/gateware/arty_uart_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms import digilent_arty


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="UART Test SoC for Arty A7")
    parser.add_target_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    platform = digilent_arty.Platform(variant=args.variant, toolchain=args.toolchain)

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]         = "fpgas-online UART Test SoC -- Arty A7"
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200

    soc = SoCCore(
        platform     = platform,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    builder = Builder(soc, output_dir="designs/uart/build/arty", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
