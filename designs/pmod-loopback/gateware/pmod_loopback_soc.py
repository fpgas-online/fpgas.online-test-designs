#!/usr/bin/env python3
# designs/pmod-loopback/gateware/pmod_loopback_soc.py
"""LiteX SoC with tristate GPIO cores for PMOD loopback testing on Arty A7.

Each PMOD port (A-D) gets a GPIOTristate peripheral with three CSR registers:
  - pmod{x}_oe  (CSRStorage, 8-bit): output enable (1 = output, 0 = input)
  - pmod{x}_out (CSRStorage, 8-bit): output value (driven when oe=1)
  - pmod{x}_in  (CSRStatus,  8-bit): input value (active when oe=0)

The firmware sets direction via oe, then reads/writes via in/out registers.
"""

import argparse
import os
import sys

# Ensure the gateware directory is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migen_compat  # noqa: F401, E402  -- patch migen tracer for Python 3.12+

from migen import *

from litex.gen import *

from litex.soc.cores.clock import S7PLL
from litex.soc.cores.gpio import GPIOTristate
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import digilent_arty
from litex_boards.platforms.digilent_arty import raw_pmod_io


# CRG -------------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst    = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk/Rst.
        clk100 = platform.request("clk100")
        rst    = ~platform.request("cpu_reset")

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(rst | self.rst)
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# SoC --------------------------------------------------------------------------------------------------

class PmodLoopbackSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="openxc7",
                 sys_clk_freq=int(100e6), **kwargs):
        platform = digilent_arty.Platform(variant=variant, toolchain=toolchain)

        # CRG ------------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore --------------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq,
            ident="PMOD Loopback Test SoC",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=32768,
            integrated_main_ram_size=8192,
            **kwargs,
        )

        # Add a GPIOTristate for each PMOD connector.
        # The Arty platform defines connectors "pmoda" through "pmodd",
        # each with 8 data pins. We use raw_pmod_io() to create proper
        # IO extensions from the connector definitions.
        for port_name in ["pmoda", "pmodb", "pmodc", "pmodd"]:
            platform.add_extension(raw_pmod_io(port_name))
            pads = platform.request(port_name)
            setattr(self, port_name, GPIOTristate(pads))


def _find_openxc7_dir():
    """Find the openXC7 toolchain directory by walking up from this file.

    Requires the squashfs-root subdirectory to exist, which distinguishes a
    real openXC7 installation from a stale/empty directory.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        candidate = os.path.join(d, ".venv", "toolchains", "openxc7")
        if os.path.isdir(os.path.join(candidate, "squashfs-root")):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _setup_openxc7_env():
    """Set environment variables for the openXC7 toolchain if not already set."""
    openxc7_dir = _find_openxc7_dir()
    if openxc7_dir is None:
        print("WARNING: Could not locate openXC7 toolchain directory.")
        return

    if "CHIPDB" not in os.environ:
        chipdb_dir = os.path.join(openxc7_dir, "chipdb")
        os.makedirs(chipdb_dir, exist_ok=True)
        os.environ["CHIPDB"] = chipdb_dir

    if "NEXTPNR_XILINX_PYTHON_DIR" not in os.environ:
        python_dir = os.path.join(openxc7_dir, "squashfs-root", "opt", "nextpnr-xilinx", "python")
        if os.path.isdir(python_dir):
            os.environ["NEXTPNR_XILINX_PYTHON_DIR"] = python_dir

    if "PRJXRAY_DB_DIR" not in os.environ:
        db_dir = os.path.join(openxc7_dir, "squashfs-root", "opt", "nextpnr-xilinx", "external", "prjxray-db")
        if os.path.isdir(db_dir):
            os.environ["PRJXRAY_DB_DIR"] = db_dir


def main():
    parser = argparse.ArgumentParser(description="PMOD Loopback SoC for Arty A7")
    parser.add_argument("--variant",    default="a7-35",          help="Arty variant: a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="openxc7",        help="Toolchain: vivado, yosys+nextpnr, or openxc7")
    parser.add_argument("--build",      action="store_true",      help="Build the bitstream")
    parser.add_argument("--load",       action="store_true",      help="Load bitstream to FPGA")
    parser.add_argument("--no-compile-gateware", action="store_true")
    args = parser.parse_args()

    if args.toolchain == "openxc7":
        _setup_openxc7_env()

    soc = PmodLoopbackSoC(variant=args.variant, toolchain=args.toolchain)

    builder = Builder(soc, compile_gateware=not args.no_compile_gateware)
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
