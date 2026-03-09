#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Kosagi NeTV2.

Same approach as the Arty target: minimal SoC with CPU + BIOS + UART.
The NeTV2 UART connects to the RPi via GPIO (FPGA TX=E14, RX=E13).
Serial port on the RPi is /dev/ttyAMA0.

Build command (from repo root):
    uv run python designs/uart/gateware/uart_soc_netv2.py --toolchain openxc7 --build

Requires environment variables CHIPDB and PRJXRAY_DB_DIR pointing to the
openxc7 toolchain directories. The bitstream is written to:
    designs/uart/build/netv2/gateware/kosagi_netv2.bit
"""

import os
from pathlib import Path

from migen import *

from litex.gen import *

from litex_boards.platforms import kosagi_netv2

from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder


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


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="vivado", sys_clk_freq=100e6, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        # The NeTV2 platform uses dashed device names (e.g. "xc7a35t-fgg484-2")
        # for Vivado compatibility. The openxc7 toolchain's prjxray database
        # expects no dash between device and package (e.g. "xc7a35tfgg484-2").
        # Remove the dash so fasm2frames can find the part, and create a chipdb
        # symlink so nextpnr can find its database file under the new name.
        if toolchain == "openxc7":
            import re
            old_device = platform.device
            new_device = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", old_device)
            if new_device != old_device:
                platform.device = new_device
                # Ensure chipdb file can be found under the un-dashed dbpart name.
                chipdb_dir = os.environ.get("CHIPDB", "")
                if chipdb_dir:
                    old_dbpart = re.sub(r"-\d+$", "", old_device)
                    new_dbpart = re.sub(r"-\d+$", "", new_device)
                    old_chipdb = os.path.join(chipdb_dir, old_dbpart + ".bin")
                    new_chipdb = os.path.join(chipdb_dir, new_dbpart + ".bin")
                    if os.path.exists(old_chipdb) and not os.path.exists(new_chipdb):
                        os.symlink(old_chipdb, new_chipdb)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)


# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="UART Test SoC for NeTV2")
    parser.add_target_argument("--variant",      default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]                    = "fpgas-online UART Test SoC -- NeTV2"
    soc_kwargs["ident_version"]            = True
    soc_kwargs["uart_baudrate"]            = 115200
    soc_kwargs["integrated_main_ram_size"] = 8192

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    # Strip $scopeinfo cells that newer Yosys emits but nextpnr-xilinx does not support.
    # Set a custom Yosys template that adds "delete t:$scopeinfo" after synthesis.
    soc.platform.toolchain._yosys_template = [
        "verilog_defaults -push",
        "verilog_defaults -add -defer",
        "{read_files}",
        "verilog_defaults -pop",
        'attrmap -tocase keep -imap keep="true" keep=1 -imap keep="false" keep=0 -remove keep=0',
        "{yosys_cmds}",
        "synth_{target} {synth_opts} -top {build_name}",
        "delete t:$scopeinfo",
        "write_{write_fmt} {write_opts} {output_name}.{synth_fmt}",
    ]

    # Resolve output_dir relative to the design directory (two levels up from this script).
    design_dir = Path(os.path.realpath(__file__)).parent.parent
    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = str(design_dir / "build" / "netv2")
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
