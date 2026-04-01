#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Sqrl Acorn CLE-215+ / NiteFury / LiteFury.

Builds a minimal SoC with CPU + UART + bitbang SPI Flash. Custom RV32I
firmware reads the JEDEC ID via command 0x9F and prints the result.

Acorn SPI Flash: S25FL256S, quad SPI, CS=T19. Clock routed via STARTUPE2.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_acorn.py --toolchain openxc7 --build

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
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms.sqrl_acorn import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

kB = 1024


# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """Minimal CRG for Acorn: generates sys clock from the 200 MHz differential oscillator."""

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk.
        clk200 = platform.request("clk200")

        # PLL.
        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# BaseSoC -----------------------------------------------------------------------------------------


class BaseSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7", sys_clk_freq=100e6, **kwargs):
        platform = Platform(variant=variant, toolchain=toolchain)

        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        kwargs["uart_name"] = "serial"
        kwargs["integrated_rom_size"] = 1 * kB
        kwargs["integrated_sram_size"] = 4 * kB
        kwargs.setdefault("cpu_variant", "minimal")
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # SPI Flash (bitbang via STARTUPE2) ----------------------------------------------------
        # The sqrl_acorn platform defines "flash" + "flash_cs_n" rather than
        # the standard "spiflash" resource. Build a combined pads record from
        # the platform's existing resources.
        from designs._shared.s7_spi_flash import S7BitbangSPIFlash

        flash_pads = platform.request("flash")
        flash_cs_n = platform.request("flash_cs_n")
        flash_pads.cs_n = flash_cs_n
        self.submodules.spiflash = S7BitbangSPIFlash(pads=flash_pads)
        self.add_csr("spiflash")


# Build --------------------------------------------------------------------------------------------


def main():
    from litex.build.parser import LiteXArgumentParser

    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for Acorn/LiteFury")
    target_group = parser.target_group
    target_group.add_argument("--variant", default="cle-215+", choices=["cle-215+", "cle-215", "cle-101"],
                              help="Board variant: cle-215+ (Acorn), cle-215 (NiteFury), cle-101 (LiteFury).")
    target_group.add_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident="fpgas-online SPI Flash Test SoC -- Acorn/LiteFury",
        uart_baudrate=115200,
        output_dir=default_build_dir(__file__, "acorn"),
    )
    args = parser.parse_args()

    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=int(args.sys_clk_freq),
        **parser.soc_argdict,
    )

    ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder_args = dict(parser.builder_argdict)
    builder_args["compile_software"] = False
    builder = Builder(soc, **builder_args)

    from designs._shared.ice40_firmware import install_spiflash_firmware

    ident = "fpgas-online SPI Flash Test SoC -- Acorn/LiteFury"
    install_spiflash_firmware(soc, ident)

    builder.build(run=args.build)


if __name__ == "__main__":
    main()
