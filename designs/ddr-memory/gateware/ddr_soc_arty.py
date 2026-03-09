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

from migen import *

from litex.gen import *

from litex_boards.platforms import digilent_arty

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

from litedram.modules import MT41K128M16
from litedram.phy import s7ddrphy

# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq, with_rst=True):
        self.rst          = Signal()
        self.cd_sys       = ClockDomain("sys")
        self.cd_sys4x     = ClockDomain("sys4x")
        self.cd_sys4x_dqs = ClockDomain("sys4x_dqs")
        self.cd_idelay    = ClockDomain("idelay")

        # Clk/Rst.
        clk100 = platform.request("clk100")
        rst    = ~platform.request("cpu_reset") if with_rst else 0

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(rst | self.rst)
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys,       sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay,    200e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)

        # IdelayCtrl.
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="vivado", sys_clk_freq=100e6, **kwargs):
        platform = digilent_arty.Platform(variant=variant, toolchain=toolchain)

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident = "fpgas-online DDR Test SoC -- Arty A7",
            **kwargs,
        )

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.ddrphy = s7ddrphy.A7DDRPHY(
                platform.request("ddram"),
                memtype      = "DDR3",
                nphases      = 4,
                sys_clk_freq = sys_clk_freq,
            )
            self.add_sdram("sdram",
                phy           = self.ddrphy,
                module        = MT41K128M16(sys_clk_freq, "1:4"),
                l2_cache_size = kwargs.get("l2_size", 8192),
            )

# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="DDR Memory Test SoC for Arty A7")
    parser.add_target_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **parser.soc_argdict,
    )

    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = "designs/ddr-memory/build/arty"
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
