#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for NeTV2 PCIe enumeration testing.

Builds a LiteX SoC targeting the NeTV2 board (Xilinx 7-Series).

With the Vivado toolchain, the full SoC includes:
  - VexRiscv CPU + BIOS + UART (115200 baud)
  - DDR3 SDRAM (512 MB) via Xilinx A7DDRPHY
  - LitePCIe endpoint using the Xilinx 7-Series hard IP PCIe block
    - Vendor ID: 0x10EE (Xilinx)
    - Device ID: 0x7011
    - PCIe Gen2 x1
    - BAR0 for Wishbone bridge access

With the yosys+nextpnr (open-source) toolchain, a minimal SoC is built:
  - VexRiscv CPU + BIOS + UART (115200 baud)
  - Integrated SRAM only (no DDR3 -- A7DDRPHY needs Vivado primitives)
  - No PCIe (S7PCIEPHY needs Vivado IP generation)

The FPGA must be programmed via JTAG (OpenOCD) BEFORE the RPi5 scans
the PCIe bus.  After programming, the host triggers a bus rescan.

NeTV2 PCIe pinout:
  - CLK: F10 (P) / E10 (N)
  - RST_N: E18
  - Lane 0: RX D11/C11, TX D5/C5
"""

import argparse
import importlib

# Monkey-patch litex memory Verilog generator to handle write-only ports.
# The migen git version (needed for Python 3.12) can create memory ports
# with dat_r=None (write-only), but litex's memory.py doesn't handle this.
_litex_memory = importlib.import_module("litex.gen.fhdl.memory")
_orig_memory_generate_verilog = _litex_memory._memory_generate_verilog

def _patched_memory_generate_verilog(name, memory, namespace, add_data_file):
    from migen.fhdl.structure import Signal
    patched_ports = []
    for port in memory.ports:
        if port.dat_r is None:
            port.dat_r = Signal(memory.width, name_override="_dummy_dat_r")
            patched_ports.append(port)
    try:
        return _orig_memory_generate_verilog(name, memory, namespace, add_data_file)
    finally:
        for port in patched_ports:
            port.dat_r = None

_litex_memory._memory_generate_verilog = _patched_memory_generate_verilog

from migen import *

from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import kosagi_netv2


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="yosys+nextpnr", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        sys_clk_freq = 50e6
        is_vivado = (toolchain == "vivado")

        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="PCIe Enumeration Test SoC (NeTV2)",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=0x10000,       # 64 KB BIOS ROM
            integrated_main_ram_size=0x10000,   # 64 KB (used when no DDR3)
            **kwargs,
        )

        # DDR3 SDRAM -- requires Xilinx ISERDES/OSERDES primitives (Vivado only)
        if is_vivado:
            from litedram.modules import MT41K256M16
            from litedram.phy import s7ddrphy

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

        # LitePCIe endpoint -- requires Xilinx 7-Series hard IP (Vivado only)
        if is_vivado:
            from litepcie.phy.s7pciephy import S7PCIEPHY
            from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
            from litepcie.frontend.wishbone import LitePCIeWishboneBridge

            # PCIe PHY -- uses the Xilinx 7-Series integrated hard block
            self.pcie_phy = S7PCIEPHY(
                platform,
                platform.request("pcie_x1"),
                data_width=64,
                bar0_size=0x20000,  # 128 KB BAR0
            )

            # PCIe endpoint
            self.pcie_endpoint = LitePCIeEndpoint(
                self.pcie_phy, max_pending_requests=4,
            )

            # PCIe Wishbone bridge (host accesses SoC registers via BAR0)
            self.pcie_bridge = LitePCIeWishboneBridge(
                self.pcie_endpoint,
                base_address=self.bus.regions["main_ram"].origin,
            )
            self.bus.add_master(master=self.pcie_bridge.wishbone)

            # PCIe MSI (Message Signaled Interrupts)
            self.pcie_msi = LitePCIeMSI()

            # Connect MSI to PHY
            self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)

            # PCIe clock period constraint
            platform.add_period_constraint(
                self.pcie_phy.cd_pcie.clk, 1e9 / 62.5e6,
            )
        else:
            print("INFO: PCIe and DDR3 disabled (requires Vivado toolchain).")
            print("INFO: Building minimal SoC with CPU + SRAM + UART.")


def main():
    parser = argparse.ArgumentParser(
        description="PCIe Enumeration Test SoC for NeTV2",
    )
    parser.add_argument(
        "--variant", default="a7-35", help="a7-35 or a7-100",
    )
    parser.add_argument(
        "--toolchain", default="yosys+nextpnr",
        help="vivado or yosys+nextpnr",
    )
    parser.add_argument(
        "--build", action="store_true", help="Build bitstream",
    )
    parser.add_argument(
        "--load", action="store_true", help="Load bitstream via OpenOCD",
    )
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
