#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for Acorn/LiteFury PCIe enumeration testing.

Builds a SoC with CPU + BIOS + UART + PCIe Gen2 x1 endpoint using openxc7
and the open-source pcie_7x core (github.com/regymm/pcie_7x) instead of
Vivado's proprietary pcie_7x IP.

The host (RPi5 via mPCIe HAT) provides a single PCIe Gen2 x1 lane.
After programming the FPGA (SRAM only!) and triggering a bus rescan,
the host should see the FPGA as a PCIe device (10ee:7022).

SAFETY: The Acorn has NO JTAG or UART directly connected.  The flash
contains a factory bitstream that enables PCIe programming.  NEVER use
--write-flash — only volatile SRAM loads.

Build command:
    uv run python designs/pcie-enumeration/gateware/pcie_soc_acorn.py \\
        --toolchain openxc7 --build

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)
"""

import glob
import os
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

# Path to the open-source pcie_7x Verilog sources (git submodule).
PCIE_7X_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pcie_7x", "src")

# PCIe x1 resource — uses lane 0 from the Acorn's x4 edge connector.
# The RPi 5 mPCIe HAT provides a single Gen2 x1 lane.
_pcie_x1_io = [
    ("pcie_x1", 0,
        Subsignal("rst_n", Pins("J1"), IOStandard("LVCMOS33"), Misc("PULLUP=TRUE")),
        Subsignal("clk_p", Pins("F6")),
        Subsignal("clk_n", Pins("E6")),
        Subsignal("rx_p", Pins("B10")),
        Subsignal("rx_n", Pins("A10")),
        Subsignal("tx_p", Pins("B6")),
        Subsignal("tx_n", Pins("A6")),
    ),
]


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
            # dropped and the PCIe hard IP is handled by pcie_7x Verilog sources.
            for attr in ("pre_synthesis_commands", "pre_placement_commands"):
                if not hasattr(platform.toolchain, attr):
                    setattr(platform.toolchain, attr, [])

        # Add PCIe x1 resource (lane 0 from the x4 connector).
        platform.add_extension(_pcie_x1_io)

        # Add pcie_7x open-source Verilog sources — provides the pcie_s7 module
        # that S7PCIEPHY instantiates, replacing Vivado's proprietary pcie_7x IP.
        for vfile in sorted(glob.glob(os.path.join(PCIE_7X_SRC, "*.v"))):
            platform.add_source(vfile)

        # Assert CLKREQ# to keep PCIe reference clock active.
        self.comb += platform.request("pcie_clkreq_n").eq(0)

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

        # PCIe Gen2 x1 endpoint ---------------------------------------------------------------
        self.pcie_phy = S7PCIEPHY(
            platform,
            platform.request("pcie_x1"),
            data_width=64,
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
