#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Digilent Arty A7.

Builds a minimal SoC with CPU + BIOS + UART. The BIOS automatically prints
an identification banner on boot and provides an interactive serial console
that echoes characters -- this is all we need for the UART test.

Build command:
    uv run python designs/uart/gateware/uart_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/uart/build/arty/gateware/arty.bit
"""

from migen import *

from litex.gen import *

from litex_boards.platforms import digilent_arty

from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder


# CRG (Clock Reset Generator) ---------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal CRG for Arty A7: generates sys clock from the 100 MHz on-board oscillator."""
    def __init__(self, platform, sys_clk_freq, with_rst=True):
        self.rst    = Signal()
        self.cd_sys = ClockDomain()

        # Clk/Rst.
        clk100 = platform.request("clk100")
        rst    = ~platform.request("cpu_reset") if with_rst else 0

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(rst | self.rst)
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="vivado", sys_clk_freq=100e6, **kwargs):
        platform = digilent_arty.Platform(variant=variant, toolchain=toolchain)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)


# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="UART Test SoC for Arty A7")
    parser.add_target_argument("--variant",      default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]                    = "fpgas-online UART Test SoC -- Arty A7"
    soc_kwargs["ident_version"]            = True
    soc_kwargs["uart_baudrate"]            = 115200
    soc_kwargs["integrated_main_ram_size"] = 8192

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    builder = Builder(soc, output_dir="designs/uart/build/arty", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
