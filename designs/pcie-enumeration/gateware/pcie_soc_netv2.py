#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for NeTV2 PCIe enumeration testing.

Builds a LiteX SoC targeting the NeTV2 board (Xilinx 7-Series) with:
  - VexRiscv CPU + BIOS + UART (115200 baud)
  - DDR3 SDRAM (512 MB) via Xilinx A7DDRPHY
  - LitePCIe endpoint using the open-source pcie_7x core
    - Vendor ID: 0x10EE (Xilinx)
    - Device ID: 0x7011
    - PCIe Gen2 x1
    - BAR0 for Wishbone bridge access

The FPGA must be programmed via JTAG (OpenOCD) BEFORE the RPi5 scans
the PCIe bus.  After programming, the host triggers a bus rescan.

NeTV2 PCIe pinout:
  - CLK: F10 (P) / E10 (N)
  - RST_N: E18
  - Lane 0: RX D11/C11, TX D5/C5

Build command:
    uv run python designs/pcie-enumeration/gateware/pcie_soc_netv2.py \\
        --variant a7-35 --toolchain openxc7 --build
"""

import glob
import os
import pathlib
import sys

# Add repo root to sys.path so shared modules can be imported.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litedram.modules import MT41K256M16
from litedram.phy import s7ddrphy
from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
from litepcie.frontend.wishbone import LitePCIeWishboneBridge
from litepcie.phy.s7pciephy import S7PCIEPHY
from litex.gen import *
from litex.soc.cores.clock import S7IDELAYCTRL, S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import kosagi_netv2
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer for Python >= 3.11
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template

# Path to the open-source pcie_7x Verilog sources (git submodule).
PCIE_7X_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pcie_7x", "src")

# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """CRG for NeTV2 with DDR3 clock domains."""

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")
        self.cd_sys4x = ClockDomain("sys4x")
        self.cd_sys4x_dqs = ClockDomain("sys4x_dqs")
        self.cd_idelay = ClockDomain("idelay")

        # Clk.
        clk50 = platform.request("clk50")

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        pll.create_clkout(self.cd_sys4x, 4 * sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4 * sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay, 200e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)

        # IdelayCtrl.
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)


# SoC ----------------------------------------------------------------------------------------------


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="openxc7", sys_clk_freq=50e6, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        if toolchain in ("openxc7", "yosys+nextpnr"):
            fix_openxc7_device_name(platform)
            # S7PCIEPHY.add_sources() appends Vivado-specific TCL commands to
            # these toolchain attributes.  Provide empty lists for openxc7.
            for attr in ("pre_synthesis_commands", "pre_placement_commands"):
                if not hasattr(platform.toolchain, attr):
                    setattr(platform.toolchain, attr, [])

        # Add pcie_7x open-source Verilog sources — provides the pcie_s7 module
        # that S7PCIEPHY instantiates, replacing Vivado's proprietary pcie_7x IP.
        for vfile in sorted(glob.glob(os.path.join(PCIE_7X_SRC, "*.v"))):
            platform.add_source(vfile)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="PCIe Enumeration Test SoC (NeTV2)",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=0x10000,  # 64 KB BIOS ROM
            **kwargs,
        )

        # DDR3 SDRAM ---------------------------------------------------------------------------
        self.ddrphy = s7ddrphy.A7DDRPHY(
            platform.request("ddram"),
            memtype="DDR3",
            nphases=4,
            sys_clk_freq=sys_clk_freq,
        )
        self.add_sdram(
            "sdram",
            phy=self.ddrphy,
            module=MT41K256M16(sys_clk_freq, "1:4"),
            l2_cache_size=8192,
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

        # PCIe clock period constraint
        platform.add_period_constraint(
            self.pcie_phy.cd_pcie.clk,
            1e9 / 62.5e6,
        )


# Build --------------------------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PCIe Enumeration Test SoC for NeTV2",
    )
    parser.add_argument(
        "--variant",
        default="a7-35",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)",
    )
    parser.add_argument(
        "--toolchain",
        default="openxc7",
        help="openxc7 or yosys+nextpnr",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build bitstream",
    )
    args = parser.parse_args()

    soc = PCIeEnumerationSoC(variant=args.variant, toolchain=args.toolchain)

    if args.toolchain in ("openxc7", "yosys+nextpnr"):
        ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder = Builder(soc, output_dir=default_build_dir(__file__, "netv2"))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
