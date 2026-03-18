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
import os
import pathlib
import sys

# Add repo root to sys.path so shared modules can be imported.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer for Python >= 3.11
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import apply_nodram_workaround, patch_yosys_template

# Monkey-patch litex memory Verilog generator to handle write-only ports.
# The migen git version (needed for Python 3.12) can create memory ports
# with dat_r=None (write-only), but litex's memory.py doesn't handle this.
# We patch three sections: intermediate signals, read logic, and read mapping
# to skip ports where dat_r is None, avoiding undeclared wire warnings.
_litex_memory = importlib.import_module("litex.gen.fhdl.memory")
_orig_memory_generate_verilog = _litex_memory._memory_generate_verilog

def _patched_memory_generate_verilog(name, memory, namespace, add_data_file):
    # Check if any port has dat_r=None; if not, use original directly.
    if all(port.dat_r is not None for port in memory.ports):
        return _orig_memory_generate_verilog(name, memory, namespace, add_data_file)

    # Import everything needed from the original module's scope.
    from migen.fhdl.bitcontainer import bits_for
    from migen.fhdl.specials import (
        NO_CHANGE,
        READ_FIRST,
        WRITE_FIRST,
        Memory,
    )
    from migen.fhdl.structure import Signal
    from migen.fhdl.verilog import _printexpr as verilog_printexpr

    def _get_name(e):
        if isinstance(e, Memory):
            return namespace.get_name(e)
        else:
            return verilog_printexpr(namespace, e)[0]

    r = ""
    adr_regs = {}
    data_regs = {}

    clocks = [port.clock for port in memory.ports]
    if clocks.count(clocks[0]) != len(clocks):
        for port in memory.ports:
            port.mode = READ_FIRST

    for port in memory.ports:
        if port.we_granularity == 0:
            port.we_granularity = memory.width

    # Memory Description.
    r += "//" + "-" * 78 + "\n"
    r += f"// Memory {_get_name(memory)}: {memory.depth}-words x {memory.width}-bit\n"
    r += "//" + "-" * 78 + "\n"
    for n, port in enumerate(memory.ports):
        r += f"// Port {n} | "
        if port.async_read:
            r += "Read: Async | "
        else:
            r += "Read: Sync  | "
        if port.we is None:
            r += "Write: ---- | "
        else:
            r += "Write: Sync | "
            r += "Mode: "
            if port.mode == WRITE_FIRST:
                r += "Write-First | "
            elif port.mode == READ_FIRST:
                r += "Read-First  | "
            elif port.mode == NO_CHANGE:
                r += "No-Change | "
            r += f"Write-Granularity: {port.we_granularity} "
        r += "\n"

    # Memory Logic Declaration/Initialization.
    r += f"reg [{memory.width - 1}:0] {_get_name(memory)}[0:{memory.depth - 1}];\n"
    if memory.init is not None:
        content = ""
        formatter = f"{{:0{int(memory.width / 4)}x}}\n"
        for d in memory.init:
            content += formatter.format(d)
        memory_filename = add_data_file(
            f"{name}_{_get_name(memory)}.init", content,
        )
        r += "initial begin\n"
        r += f'\t$readmemh("{memory_filename}", {_get_name(memory)});\n'
        r += "end\n"

    # Port Intermediate Signals (skip write-only ports).
    for n, port in enumerate(memory.ports):
        if port.dat_r is None or port.async_read:
            continue
        if port.mode in [WRITE_FIRST]:
            adr_regs[n] = Signal(
                name_override=f"{_get_name(memory)}_adr{n}",
            )
            r += f"reg [{bits_for(memory.depth - 1) - 1}:0] {_get_name(adr_regs[n])};\n"
        if port.mode in [READ_FIRST, NO_CHANGE]:
            data_regs[n] = Signal(
                name_override=f"{_get_name(memory)}_dat{n}",
            )
            r += f"reg [{memory.width - 1}:0] {_get_name(data_regs[n])};\n"

    # Ports Write/Read Logic (skip read logic for write-only ports).
    for n, port in enumerate(memory.ports):
        r += f"always @(posedge {_get_name(port.clock)}) begin\n"
        if port.we is not None:
            for i in range(memory.width // port.we_granularity):
                wbit = f"[{i}]" if memory.width != port.we_granularity else ""
                r += f"\tif ({_get_name(port.we)}{wbit})\n"
                lbit = i * port.we_granularity
                hbit = (i + 1) * port.we_granularity - 1
                dslc = f"[{hbit}:{lbit}]" if (memory.width != port.we_granularity) else ""
                r += f"\t\t{_get_name(memory)}[{_get_name(port.adr)}]{dslc} <= {_get_name(port.dat_w)}{dslc};\n"

        if port.dat_r is not None and not port.async_read:
            if port.mode in [WRITE_FIRST]:
                rd = f"\t{_get_name(adr_regs[n])} <= {_get_name(port.adr)};\n"
            if port.mode in [READ_FIRST, NO_CHANGE]:
                rd = ""
                if port.mode == NO_CHANGE:
                    rd += f"\tif (!{_get_name(port.we)})\n\t"
                rd += f"\t{_get_name(data_regs[n])} <= {_get_name(memory)}[{_get_name(port.adr)}];\n"
            if port.re is None:
                r += rd
            else:
                r += f"\tif ({_get_name(port.re)})\n"
                r += "\t" + rd.replace("\n\t", "\n\t\t")
        r += "end\n"

    # Ports Read Mapping (skip write-only ports).
    for n, port in enumerate(memory.ports):
        if port.dat_r is None:
            continue
        if port.async_read:
            r += f"assign {_get_name(port.dat_r)} = {_get_name(memory)}[{_get_name(port.adr)}];\n"
            continue
        if port.mode in [WRITE_FIRST]:
            r += f"assign {_get_name(port.dat_r)} = {_get_name(memory)}[{_get_name(adr_regs[n])}];\n"
        if port.mode in [READ_FIRST, NO_CHANGE]:
            r += f"assign {_get_name(port.dat_r)} = {_get_name(data_regs[n])};\n"
    r += "\n\n"

    return r

_litex_memory._memory_generate_verilog = _patched_memory_generate_verilog

from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import kosagi_netv2
from migen import *

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


# SoC ----------------------------------------------------------------------------------------------

class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="openxc7", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        # Fix device name for openXC7 (removes dash between part and package).
        if toolchain in ("openxc7", "yosys+nextpnr"):
            fix_openxc7_device_name(platform)

        sys_clk_freq = 50e6
        is_vivado = (toolchain == "vivado")

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

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

        # Apply yosys workarounds for openXC7 toolchain.
        if toolchain in ("openxc7", "yosys+nextpnr"):
            patch_yosys_template(self)
            apply_nodram_workaround(self)

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
            from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
            from litepcie.frontend.wishbone import LitePCIeWishboneBridge
            from litepcie.phy.s7pciephy import S7PCIEPHY

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

            # PCIe MSI -- not needed for enumeration-only test, but kept
            # to match the typical LitePCIe SoC topology.  No IRQ sources
            # are connected (irqs tied to 0).
            self.pcie_msi = LitePCIeMSI(width=1)
            self.comb += self.pcie_msi.irqs.eq(0)

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
        "--variant", default="a7-100", choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)",
    )
    parser.add_argument(
        "--toolchain", default="openxc7",
        help="vivado, openxc7, or yosys+nextpnr",
    )
    parser.add_argument(
        "--build", action="store_true", help="Build bitstream",
    )
    parser.add_argument(
        "--load", action="store_true", help="Load bitstream via OpenOCD",
    )
    args = parser.parse_args()

    # Set openXC7 environment variables if not already set.
    # Supports two layouts:
    #   1. System snap: /snap/openxc7/current/opt/nextpnr-xilinx/...
    #   2. Local dev:   .venv/toolchains/openxc7/squashfs-root/opt/...
    if args.toolchain == "openxc7":
        snap_dir = "/snap/openxc7/current"
        if os.path.isdir(snap_dir):
            # System snap installation (e.g. CI).
            oxc7_snap = snap_dir
        else:
            # Local development layout.
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir)
            repo_root = project_root
            while repo_root != "/":
                if os.path.isdir(os.path.join(repo_root, ".venv", "toolchains")):
                    break
                repo_root = os.path.dirname(repo_root)
            oxc7_root = os.path.join(repo_root, ".venv", "toolchains", "openxc7")
            oxc7_snap = os.path.join(oxc7_root, "squashfs-root")
            if "CHIPDB" not in os.environ:
                os.environ["CHIPDB"] = os.path.join(oxc7_root, "chipdb")

            # Add local toolchain bin directories to PATH.
            toolchains_root = os.path.join(repo_root, ".venv", "toolchains")
            extra_paths = [
                os.path.join(oxc7_root, "bin"),
                os.path.join(oxc7_snap, "usr", "bin"),
                os.path.join(toolchains_root, "oss-cad-suite", "oss-cad-suite", "bin"),
            ]
            riscv_gcc_dir = os.path.join(toolchains_root, "riscv-gcc")
            if os.path.isdir(riscv_gcc_dir):
                for entry in os.listdir(riscv_gcc_dir):
                    bin_dir = os.path.join(riscv_gcc_dir, entry, "bin")
                    if os.path.isdir(bin_dir):
                        extra_paths.append(bin_dir)
            current_path = os.environ.get("PATH", "")
            for p in extra_paths:
                if os.path.isdir(p) and p not in current_path:
                    current_path = p + os.pathsep + current_path
            os.environ["PATH"] = current_path

        if "PRJXRAY_DB_DIR" not in os.environ:
            os.environ["PRJXRAY_DB_DIR"] = os.path.join(
                oxc7_snap, "opt", "nextpnr-xilinx", "external", "prjxray-db",
            )
        if "NEXTPNR_XILINX_PYTHON_DIR" not in os.environ:
            os.environ["NEXTPNR_XILINX_PYTHON_DIR"] = os.path.join(
                oxc7_snap, "opt", "nextpnr-xilinx", "python",
            )

    soc = PCIeEnumerationSoC(variant=args.variant, toolchain=args.toolchain)

    # Create chipdb symlink for the un-dashed device name if needed.
    if args.toolchain == "openxc7":
        ensure_chipdb_symlink(soc.platform)

    builder = Builder(soc, output_dir=default_build_dir(__file__, "netv2"))
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
