#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for Acorn/LiteFury PCIe enumeration testing.

Builds a SoC with CPU + BIOS + UART + PCIe Gen2 x4 endpoint using openxc7.
The host (RPi5 via mPCIe HAT) should see the FPGA as a PCIe device
after programming and bus rescan.

  - VexRiscv CPU + BIOS + UART (115200 baud)
  - LitePCIe Gen2 x4 endpoint using the Xilinx 7-Series hard IP PCIe block
    - Vendor ID: 0x10EE (Xilinx)
    - Device ID: 0x7011 (+ nlanes)
    - 128 KB BAR0 for Wishbone bridge access

Build command:
    uv run python designs/pcie-enumeration/gateware/pcie_soc_acorn.py --toolchain openxc7 --build

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
from litepcie.frontend.wishbone import LitePCIeWishboneBridge
from litepcie.phy.s7pciephy import S7PCIEPHY
from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import sqrl_acorn
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """Minimal CRG for Acorn: generates sys clock from the 200 MHz on-board oscillator."""

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


# SoC ----------------------------------------------------------------------------------------------


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7", sys_clk_freq=100e6, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)

        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)
            # S7PCIEPHY.add_sources() appends Vivado-specific TCL commands to
            # these toolchain attributes.  The openxc7 (yosys+nextpnr) toolchain
            # doesn't have them, so provide empty lists — the TCL is silently
            # dropped and the PCIe hard IP is handled natively by nextpnr-xilinx.
            for attr in ("pre_synthesis_commands", "pre_placement_commands"):
                if not hasattr(platform.toolchain, attr):
                    setattr(platform.toolchain, attr, [])

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="PCIe Enumeration Test SoC (Acorn/LiteFury)",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=0x10000,  # 64 KB BIOS ROM
            integrated_main_ram_size=0x10000,  # 64 KB SRAM
            **kwargs,
        )

        # PCIe Gen2 x4 endpoint ---------------------------------------------------------------
        self.pcie_phy = S7PCIEPHY(
            platform,
            platform.request("pcie_x4"),
            data_width=128,
            bar0_size=0x20000,  # 128 KB BAR0
        )

        self.pcie_endpoint = LitePCIeEndpoint(
            self.pcie_phy,
            max_pending_requests=4,
        )

        self.pcie_bridge = LitePCIeWishboneBridge(
            self.pcie_endpoint,
            base_address=self.bus.regions["main_ram"].origin,
        )
        self.bus.add_master(master=self.pcie_bridge.wishbone)

        self.pcie_msi = LitePCIeMSI(width=1)
        self.comb += self.pcie_msi.irqs.eq(0)
        self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)

        # PCIe clock constraint
        platform.add_period_constraint(
            self.pcie_phy.cd_pcie.clk,
            1e9 / 125e6,  # Gen2 reference clock
        )


# Build --------------------------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PCIe Enumeration Test SoC for Acorn/LiteFury")
    parser.add_argument(
        "--variant",
        default="cle-215+",
        choices=["cle-215+", "cle-215", "cle-101"],
        help="Board variant: cle-215+ (Acorn), cle-215 (NiteFury), cle-101 (LiteFury).",
    )
    parser.add_argument("--toolchain", default="openxc7", help="openxc7 or vivado")
    parser.add_argument("--build", action="store_true", help="Build bitstream")
    args = parser.parse_args()

    soc = PCIeEnumerationSoC(variant=args.variant, toolchain=args.toolchain)

    if args.toolchain == "openxc7":
        ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder = Builder(soc, output_dir=default_build_dir(__file__, "acorn"))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
