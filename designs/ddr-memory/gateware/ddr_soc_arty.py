#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SDRAM (LiteDRAM). The BIOS
automatically runs DRAM calibration and memtest on boot. The host
just needs to parse the UART output for "Memtest OK" or "Memtest KO".

Arty A7 DRAM: Micron MT41K128M16JT-125, 256 MB, 16-bit DDR3.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/ddr-memory/build/arty/gateware/arty_ddr_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms import digilent_arty

from litedram.modules import MT41K128M16
from litedram.phy import s7ddrphy


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="DDR Memory Test SoC for Arty A7")
    parser.add_target_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = digilent_arty.Platform(variant=args.variant, toolchain=args.toolchain),
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online DDR Test SoC -- Arty A7",
        ident_version  = True,
        uart_baudrate  = 115200,
        **parser.soc_argdict,
    )

    # Add DDR3 SDRAM ----------------------------------------------------------
    soc.submodules.ddrphy = s7ddrphy.A7DDRPHY(
        soc.platform.request("ddram"),
        memtype   = "DDR3",
        nphases   = 4,
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_sdram(
        "sdram",
        phy       = soc.ddrphy,
        module    = MT41K128M16(sys_clk_freq, "1:4"),
        size      = 0x10000000,  # 256 MB
    )

    builder = Builder(soc, output_dir="designs/ddr-memory/build/arty", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
