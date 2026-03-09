#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Kosagi NeTV2.

Same approach as the Arty target: minimal SoC with CPU + BIOS + UART.
The NeTV2 UART connects to the RPi via GPIO (FPGA TX=E14, RX=E13).
Serial port on the RPi is /dev/ttyAMA0.

Build command:
    uv run python designs/uart/gateware/uart_soc_netv2.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/uart/build/netv2/gateware/netv2_uart_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms import kosagi_netv2


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="UART Test SoC for NeTV2")
    parser.add_target_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    platform = kosagi_netv2.Platform(variant=args.variant, toolchain=args.toolchain)

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]         = "fpgas-online UART Test SoC -- NeTV2"
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200

    soc = SoCCore(
        platform     = platform,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    builder = Builder(soc, output_dir="designs/uart/build/netv2", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
