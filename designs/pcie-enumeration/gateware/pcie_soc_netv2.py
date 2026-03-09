#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for NeTV2 PCIe enumeration testing.

Builds a LiteX SoC that includes:
  - VexRiscv CPU + BIOS + UART (115200 baud on /dev/ttyAMA0)
  - DDR3 SDRAM (512 MB)
  - LitePCIe endpoint using the Xilinx 7-Series hard IP PCIe block
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
"""

import argparse

from migen import *

from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import kosagi_netv2

# Try to import LitePCIe
try:
    from litepcie.phy.s7pciephy import S7PCIEPHY
    from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
    from litepcie.frontend.wishbone import LitePCIeWishboneBridge
    HAS_LITEPCIE = True
except ImportError:
    HAS_LITEPCIE = False
    print("WARNING: LitePCIe not installed.  Install with: pip install litepcie")


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="yosys+nextpnr", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq=50e6,
            ident="PCIe Enumeration Test SoC (NeTV2)",
            ident_version=True,
            uart_baudrate=115200,
            **kwargs,
        )

        # Add DDR3 SDRAM
        from litex.soc.cores.sdram import SDRAMModule
        from litex.soc.integration.soc import SoCRegion
        from litedram.modules import MT41K256M16
        from litedram.phy import s7ddrphy

        self.ddrphy = s7ddrphy.A7DDRPHY(
            platform.request("ddram"),
            memtype="DDR3",
            nphases=4,
            sys_clk_freq=50e6,
        )
        self.add_sdram(
            "sdram",
            phy=self.ddrphy,
            module=MT41K256M16(50e6, "1:4"),
            l2_cache_size=8192,
        )

        # Add LitePCIe endpoint
        if not HAS_LITEPCIE:
            raise ImportError("LitePCIe is required. Install with: pip install litepcie")

        # PCIe PHY -- uses the Xilinx 7-Series integrated hard block
        self.pcie_phy = S7PCIEPHY(
            platform,
            platform.request("pcie_x1"),
            data_width=64,
            bar0_size=0x20000,  # 128 KB BAR0
        )
        self.add_module(name="pcie_phy", module=self.pcie_phy)

        # PCIe endpoint
        self.pcie_endpoint = LitePCIeEndpoint(self.pcie_phy, max_pending_requests=4)

        # PCIe Wishbone bridge (allows host to access SoC registers via BAR0)
        self.pcie_bridge = LitePCIeWishboneBridge(
            self.pcie_endpoint, base_address=self.bus.regions["main_ram"].origin
        )
        self.bus.add_master(master=self.pcie_bridge.wishbone)

        # PCIe MSI (Message Signaled Interrupts)
        self.pcie_msi = LitePCIeMSI()
        self.add_module(name="pcie_msi", module=self.pcie_msi)

        # Connect MSI to PHY
        self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)

        # PCIe interrupt (active low reset from connector)
        platform.add_period_constraint(self.pcie_phy.cd_pcie.clk, 1e9 / 62.5e6)


def main():
    parser = argparse.ArgumentParser(description="PCIe Enumeration Test SoC for NeTV2")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream via OpenOCD")
    args = parser.parse_args()

    soc = PCIeEnumerationSoC(variant=args.variant, toolchain=args.toolchain)

    builder = Builder(soc, output_dir="build/netv2")
    builder.build(run=args.build)

    if args.load:
        import subprocess
        bitstream = builder.get_bitstream_filename(mode="sram")
        subprocess.run(
            ["openocd", "-f", "openocd/alphamax-rpi.cfg",
             "-c", f"init; pld load 0 {bitstream}; exit"],
            check=True,
        )


if __name__ == "__main__":
    main()
