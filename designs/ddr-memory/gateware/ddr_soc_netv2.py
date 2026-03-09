#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Kosagi NeTV2.

NeTV2 DRAM: 512 MB, 32-bit DDR3 (4 byte lanes).
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_netv2.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/ddr-memory/build/netv2/gateware/netv2_ddr_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms import kosagi_netv2

from litedram.modules import MT41K256M16
from litedram.phy import s7ddrphy


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="DDR Memory Test SoC for NeTV2")
    parser.add_target_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = kosagi_netv2.Platform(variant=args.variant, toolchain=args.toolchain),
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online DDR Test SoC -- NeTV2",
        **parser.soc_argdict,
    )

    # Add DDR3 SDRAM ----------------------------------------------------------
    # NeTV2 has 32-bit wide DDR3 (4 byte lanes, 512 MB total).
    soc.submodules.ddrphy = s7ddrphy.A7DDRPHY(
        soc.platform.request("ddram"),
        memtype   = "DDR3",
        nphases   = 4,
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_sdram(
        "sdram",
        phy       = soc.ddrphy,
        module    = MT41K256M16(sys_clk_freq, "1:4"),
        size      = 0x20000000,  # 512 MB
    )

    builder = Builder(soc, output_dir="designs/ddr-memory/build/netv2", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
