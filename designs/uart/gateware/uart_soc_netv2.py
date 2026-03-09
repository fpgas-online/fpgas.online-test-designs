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
import re

from migen import *

from litex.gen import *

from litex_boards.platforms import kosagi_netv2

from litex.soc.cores.clock import S7PLL
from litex.soc.integration.soc_core import SoCCore

from common import default_soc_kwargs, patch_yosys_template, build_soc


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
    def __init__(self, variant="a7-35", toolchain="openxc7", sys_clk_freq=100e6, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        # The NeTV2 platform uses dashed device names (e.g. "xc7a35t-fgg484-2")
        # for Vivado compatibility. The openxc7 toolchain's prjxray database
        # expects no dash between device and package (e.g. "xc7a35tfgg484-2").
        # Remove the dash so fasm2frames can find the part.
        if toolchain == "openxc7":
            old_device = platform.device
            new_device = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", old_device)
            if new_device != old_device:
                platform.device = new_device

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)


def _ensure_chipdb_symlink(platform):
    """Create a chipdb symlink for the un-dashed device name if needed.

    The openxc7 chipdb directory may only have a file for the dashed
    device name. This creates a symlink so nextpnr can find the database
    under the un-dashed name.
    """
    chipdb_dir = os.environ.get("CHIPDB", "")
    if not chipdb_dir:
        return

    device = platform.device
    old_device_dashed = re.sub(r"^(xc7[aksz]\d+t)(.*)", r"\1-\2", device)
    old_dbpart = re.sub(r"-\d+$", "", old_device_dashed)
    new_dbpart = re.sub(r"-\d+$", "", device)

    if old_dbpart == new_dbpart:
        return

    old_chipdb = os.path.join(chipdb_dir, old_dbpart + ".bin")
    new_chipdb = os.path.join(chipdb_dir, new_dbpart + ".bin")

    if os.path.exists(old_chipdb) and not os.path.exists(new_chipdb):
        try:
            os.symlink(old_chipdb, new_chipdb)
        except FileExistsError:
            pass  # Another process may have created it concurrently.


# Build --------------------------------------------------------------------------------------------

def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="UART Test SoC for NeTV2")
    parser.add_target_argument("--variant",      default="a7-35",     help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = default_soc_kwargs(parser, ident="fpgas-online UART Test SoC -- NeTV2")

    soc = BaseSoC(
        variant      = args.variant,
        toolchain    = args.toolchain,
        sys_clk_freq = int(args.sys_clk_freq),
        **soc_kwargs,
    )

    _ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)
    build_soc(soc, parser, subdir="netv2")


if __name__ == "__main__":
    main()
