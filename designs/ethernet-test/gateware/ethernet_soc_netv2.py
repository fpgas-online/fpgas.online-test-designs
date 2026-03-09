#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_netv2.py
"""LiteX SoC with LiteEth (RMII) for NeTV2 Ethernet testing.

The NeTV2 has an independent RMII 100Base-T Ethernet PHY with:
  - RMII reference clock on pin D17 (50 MHz)
  - Separate RJ45 jack (not shared with the RPi's Ethernet)

This builds a standard LiteX SoC using the kosagi_netv2 target with
--with-ethernet and --with-sdram enabled.
"""

import argparse

from litex.soc.integration.builder import Builder

from litex_boards.targets.kosagi_netv2 import BaseSoC


def main():
    parser = argparse.ArgumentParser(description="Ethernet Test SoC for NeTV2")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream")
    args = parser.parse_args()

    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=50e6,
        with_ethernet=True,
        with_sdram=True,
        uart_baudrate=115200,
        ident="Ethernet Test SoC (NeTV2)",
        ident_version=True,
    )

    builder = Builder(soc, output_dir="build/netv2")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
