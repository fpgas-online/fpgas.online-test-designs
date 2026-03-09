#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_netv2.py
"""LiteX SoC with LiteEth (RMII) for NeTV2 Ethernet testing.

The NeTV2 has an independent RMII 100Base-T Ethernet PHY with:
  - RMII reference clock on pin D17 (50 MHz)
  - Separate RJ45 jack (not shared with the RPi's Ethernet)

This builds a standard LiteX SoC using the kosagi_netv2 target with
--with-ethernet enabled.

Note on yosys+nextpnr toolchain:
  DDR3 should be disabled and the clock frequency lowered when using the
  open-source toolchain.  This script therefore uses
  --integrated-main-ram-size=8192 and --sys-clk-freq=50e6 by default.
"""

import gateware._migen_compat  # noqa: F401  -- patch migen tracer for Python >= 3.11

from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2
from litex_boards.targets.kosagi_netv2 import BaseSoC


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="Ethernet Test SoC for NeTV2")
    parser.add_target_argument("--variant",      default="a7-35",           help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=50e6,  type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]         = "fpgas-online Ethernet Test SoC -- NeTV2"
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200

    soc = BaseSoC(
        variant       = args.variant,
        sys_clk_freq  = int(args.sys_clk_freq),
        with_ethernet = True,
        **soc_kwargs,
    )

    builder = Builder(soc, output_dir="build/netv2", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
