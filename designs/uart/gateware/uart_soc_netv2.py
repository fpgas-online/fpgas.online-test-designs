#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Kosagi NeTV2.

Same approach as the Arty target: minimal SoC with CPU + BIOS + UART.
The NeTV2 UART connects to the RPi via GPIO (FPGA TX=E14, RX=E13).
Serial port on the RPi is /dev/ttyAMA0.

Build command (from repo root):
    uv run python designs/uart/gateware/uart_soc_netv2.py --toolchain openxc7 --build

Requires environment variables CHIPDB and PRJXRAY_DB_DIR pointing to the
openxc7 toolchain directories. The bitstream is written to:
    designs/uart/build/netv2/gateware/kosagi_netv2.bit
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import kosagi_netv2
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import build_soc, default_soc_kwargs
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

# CRG (Clock Reset Generator) ---------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal CRG for NeTV2: generates sys clock from the 50 MHz on-board oscillator."""
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk.
        clk50 = platform.request("clk50")

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="openxc7", sys_clk_freq=50e6, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        # Fix dashed device name for openXC7 compatibility.
        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)


# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="UART Test SoC for NeTV2")
    parser.add_target_argument("--variant",      default="a7-100", choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production).")
    parser.add_target_argument("--sys-clk-freq", default=50e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = default_soc_kwargs(parser, ident="fpgas-online UART Test SoC -- NeTV2")

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)
    build_soc(soc, parser, board_name="netv2", gateware_file=__file__, args=args)


if __name__ == "__main__":
    main()
