#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Sqrl Acorn CLE-215+ / NiteFury / LiteFury.

Builds a SoC with CPU + BIOS + UART + SDRAM (LiteDRAM). The BIOS
automatically runs DRAM calibration and memtest on boot. The host
just needs to parse the UART output for "Memtest OK" or "Memtest KO".

Acorn DRAM: one 16-bit DDR3 chip: Micron MT41K512M16 (1 GiB) on the CLE-215/215+, MT41K256M16 (512 MiB) on the
CLE-101 / LiteFury.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_acorn.py --toolchain openxc7 --build

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3, MT41K512M16, 1 GiB)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2, MT41K512M16, 1 GiB)
    cle-101  : Acorn CLE-101 / LiteFury (XC7A100T-2, MT41K256M16, 512 MiB)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litedram.modules import MT41K256M16, MT41K512M16
from litedram.phy import s7ddrphy
from litex.gen import *
from litex.soc.cores.clock import *
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import *
from litex_boards.platforms import sqrl_acorn
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.platform_fixups import constrain_openxc7_clocks

# nextpnr-xilinx cannot place this SoC at 100 MHz (a constrained build reached 64.9 MHz). Over three seeds
# each (2026-09-29), 80 MHz builds reached 81.4-93.2 MHz and 75 MHz ones 74.0-92.5 MHz. 80 MHz keeps the
# DDR3 at 640 MT/s, inside its 300 MHz DLL-on minimum clock.
SYS_CLK_FREQ = {"openxc7": 80e6}

# The DDR3 chip each variant has (as acorn-pcie's acorn_pcie_soc.py).
DDR3_MODULE = {
    "cle-215+": MT41K512M16,
    "cle-215": MT41K512M16,
    "cle-101": MT41K256M16,
}

# CRG ----------------------------------------------------------------------------------------------


class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")
        self.cd_sys4x = ClockDomain("sys4x")
        self.cd_sys4x_dqs = ClockDomain("sys4x_dqs")
        self.cd_idelay = ClockDomain("idelay")

        # Clk.
        clk200 = platform.request("clk200")

        # PLL.
        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        pll.create_clkout(self.cd_sys4x, 4 * sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4 * sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay, 200e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)
        constrain_openxc7_clocks(
            platform,
            {
                self.cd_sys: sys_clk_freq,
                self.cd_sys4x: 4 * sys_clk_freq,
                self.cd_sys4x_dqs: 4 * sys_clk_freq,
                self.cd_idelay: 200e6,
            },
        )

        # IdelayCtrl.
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)


# BaseSoC ------------------------------------------------------------------------------------------


class BaseSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7", sys_clk_freq=100e6, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)

        if toolchain == "openxc7":
            from designs._shared.fasm_io_fixups import add_openxc7_fasm_io_fixups
            from designs._shared.platform_fixups import fix_openxc7_device_name

            fix_openxc7_device_name(platform)
            # nextpnr-xilinx gives every SSTL bank 0.675 V; the platform (and Vivado) want 0.75 V for SSTL15.
            add_openxc7_fasm_io_fixups(platform, vref_mv=750)

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq,
            ident="fpgas-online DDR Test SoC -- Acorn/LiteFury",
            **kwargs,
        )

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.ddrphy = s7ddrphy.A7DDRPHY(
                platform.request("ddram"),
                memtype="DDR3",
                nphases=4,
                sys_clk_freq=sys_clk_freq,
            )
            self.add_sdram(
                "sdram",
                phy=self.ddrphy,
                module=DDR3_MODULE[variant](sys_clk_freq, "1:4"),
                l2_cache_size=kwargs.get("l2_size", 8192),
            )


# Build --------------------------------------------------------------------------------------------


def main():
    from litex.build.parser import LiteXArgumentParser

    parser = LiteXArgumentParser(platform=sqrl_acorn.Platform, description="DDR Memory Test SoC for Acorn/LiteFury")
    parser.add_target_argument(
        "--variant",
        default="cle-215+",
        choices=sorted(DDR3_MODULE),
        help="Board variant: cle-215+ (Acorn, 1 GiB), cle-215 (NiteFury, 1 GiB), cle-101 (LiteFury, 512 MiB).",
    )
    parser.add_target_argument(
        "--sys-clk-freq",
        default=None,
        type=float,
        help="System clock frequency (default: 80 MHz for openxc7, 100 MHz otherwise).",
    )
    args = parser.parse_args()
    sys_clk_freq = args.sys_clk_freq or SYS_CLK_FREQ.get(args.toolchain, 100e6)

    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=int(sys_clk_freq),
        **parser.soc_argdict,
    )

    from designs._shared.build_helpers import default_build_dir
    from designs._shared.platform_fixups import ensure_chipdb_symlink
    from designs._shared.yosys_workarounds import patch_yosys_template

    ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = default_build_dir(__file__, "acorn")
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
