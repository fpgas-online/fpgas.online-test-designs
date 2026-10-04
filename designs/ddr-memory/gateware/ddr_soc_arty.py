#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SDRAM (LiteDRAM). The BIOS
runs DRAM calibration and a memtest on boot; the host test (host/test_ddr.py)
attaches to the BIOS prompt and asks for both again (`sdram_init`, `sdram_test`).

Arty A7 DRAM: Micron MT41K128M16JT-125, 256 MB, 16-bit DDR3.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --toolchain openxc7 --build

The bitstream is written to:
    designs/ddr-memory/build/arty-<variant>-<flow>/gateware/digilent_arty.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litedram.modules import MT41K128M16
from litedram.phy import s7ddrphy
from litex.gen import *
from litex.soc.cores.clock import *
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import *
from litex_boards.platforms import digilent_arty
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.platform_fixups import constrain_openxc7_clocks

# nextpnr-xilinx cannot place this SoC at 100 MHz: with the clocks constrained, 100 MHz builds reach 69-90 MHz
# and 80 MHz ones 75-95 MHz, while 75 MHz builds reached 80-86 MHz in every seed tried (2026-09-29). With a
# 100 MHz input, the PLL's next choices below 80 MHz that still give 4x sys and the 200 MHz IDELAY reference
# are 75 and 70 MHz. 75 MHz runs the DDR3 at 600 MT/s, a tCK of 3.33 ns (1% beyond the 3.3 ns DLL-on
# maximum); every Welland Arty passes memtest there.
SYS_CLK_FREQ = {"openxc7": 75e6}

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
        constrain_openxc7_clocks(platform, {
            self.cd_sys:       sys_clk_freq,
            self.cd_sys4x:     4*sys_clk_freq,
            self.cd_sys4x_dqs: 4*sys_clk_freq,
            self.cd_idelay:    200e6,
        })

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
    parser.add_target_argument("--sys-clk-freq",  default=None, type=float,
        help="System clock frequency (default: 75 MHz for openxc7, 100 MHz otherwise).")
    args = parser.parse_args()
    sys_clk_freq = args.sys_clk_freq or SYS_CLK_FREQ.get(args.toolchain, 100e6)

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(sys_clk_freq),
        **parser.soc_argdict,
    )

    from designs._shared.build_helpers import board_dir, default_build_dir, flow_suffix
    from designs._shared.yosys_workarounds import patch_yosys_template

    patch_yosys_template(soc)

    board_name = board_dir("arty", args.variant) + flow_suffix(
        parser._toolchain, parser.toolchain_argdict.get("synth_mode"))
    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = default_build_dir(__file__, board_name)
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
