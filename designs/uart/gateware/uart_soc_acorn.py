#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Sqrl Acorn CLE-215+ / NiteFury / LiteFury.

Same approach as the NeTV2 target: minimal SoC with CPU + BIOS + UART.
The Acorn UART connects to the RPi via the P2 header (FPGA TX=K2, RX=J2).
Serial port on the RPi is /dev/ttyAMA0 (GPIO14/15).

Build command (from repo root):
    uv run python designs/uart/gateware/uart_soc_acorn.py --toolchain openxc7 --build

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import sqrl_acorn
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import build_soc, default_soc_kwargs
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """Minimal CRG for Acorn: generates sys clock from the 200 MHz differential oscillator."""

    def __init__(self, platform, sys_clk_freq, use_pll=True):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk.
        clk200 = platform.request("clk200")

        if use_pll:
            # PLL.
            self.pll = pll = S7PLL()
            self.comb += pll.reset.eq(self.rst)
            pll.register_clkin(clk200, 200e6)
            pll.create_clkout(self.cd_sys, sys_clk_freq)
            platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)
        else:
            # Direct 200 MHz clock (bypass PLL for debugging).
            clk200_buf = Signal()
            self.specials += Instance("IBUFDS",
                i_I=clk200.p, i_IB=clk200.n,
                o_O=clk200_buf)
            self.comb += self.cd_sys.clk.eq(clk200_buf)


# BaseSoC -----------------------------------------------------------------------------------------


class BaseSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7", sys_clk_freq=100e6, use_pll=True, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)

        # Fix dashed device name for openXC7 compatibility.
        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq, use_pll=use_pll)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)


# Build --------------------------------------------------------------------------------------------


def main():
    from litex.build.parser import LiteXArgumentParser

    parser = LiteXArgumentParser(platform=sqrl_acorn.Platform, description="UART Test SoC for Acorn/LiteFury")
    parser.add_target_argument(
        "--variant",
        default="cle-215+",
        choices=["cle-215+", "cle-215", "cle-101"],
        help="Board variant: cle-215+ (Acorn), cle-215 (NiteFury), cle-101 (LiteFury).",
    )
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    parser.add_target_argument("--no-pll", action="store_true", help="Bypass PLL, use 200 MHz oscillator directly.")
    args = parser.parse_args()

    # When bypassing PLL, force sys_clk to 200 MHz (raw oscillator frequency).
    if args.no_pll:
        args.sys_clk_freq = 200e6

    soc_kwargs = default_soc_kwargs(parser, ident="fpgas-online UART Test SoC -- Acorn/LiteFury")

    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=int(args.sys_clk_freq),
        use_pll=not args.no_pll,
        **soc_kwargs,
    )

    ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)
    build_soc(soc, parser, board_name="acorn", gateware_file=__file__, args=args)


if __name__ == "__main__":
    main()
