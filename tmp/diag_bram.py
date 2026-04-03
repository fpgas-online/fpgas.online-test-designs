#!/usr/bin/env python3
"""Diagnostic: BRAM initialization test on Acorn/LiteFury.

Pure gateware (no CPU). Tests if BRAM init data survives the
openXC7 fasm2frames/xc7frames2bit pipeline.

Creates a small BRAM initialized with 0xDEADBEEF at address 0.
Reads the value and drives outputs:
  K2 (→ GPIO15) → alternating pattern from BRAM data bits (heartbeat from BRAM)
  J2 (→ GPIO14) → 1 if BRAM[0] == 0xDEADBEEF, 0 otherwise

If J2=1 and K2 toggles: BRAM init works correctly.
If J2=0 and K2 static: BRAM init is broken (data didn't survive bitstream).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import Pins, IOStandard, Misc
from litex_boards.platforms.sqrl_acorn import Platform
from litex.soc.cores.clock import S7PLL
from migen import *

import designs._shared.migen_compat  # noqa: F401
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO

SYS_CLK_FREQ = 50e6
BRAM_MAGIC = 0xDEADBEEF

_diag_io = [
    ("diag_heartbeat", 0, Pins("K2"), IOStandard("LVCMOS33"), Misc("SLEW=FAST")),
    ("diag_bram_ok", 0, Pins("J2"), IOStandard("LVCMOS33"), Misc("SLEW=FAST")),
]


class DiagBRAM(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain("sys")

        clk200 = platform.request("clk200")

        # PLL: 200 MHz → 50 MHz
        self.submodules.pll = pll = S7PLL()
        pll.vco_margin = 0.25
        self.comb += pll.reset.eq(0)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, SYS_CLK_FREQ)

        # BRAM: 16 words of 32 bits, initialized with known pattern
        init_data = [BRAM_MAGIC] + [0x12345678 + i for i in range(15)]
        mem = Memory(32, 16, init=init_data)
        rd_port = mem.get_port()
        self.specials += mem, rd_port

        # Read address 0 continuously
        self.comb += rd_port.adr.eq(0)

        # Check if BRAM[0] == BRAM_MAGIC
        bram_ok = Signal()
        self.comb += bram_ok.eq(rd_port.dat_r == BRAM_MAGIC)

        # Drive J2 with BRAM check result
        diag_ok = platform.request("diag_bram_ok")
        self.comb += diag_ok.eq(bram_ok)

        # Drive K2 with heartbeat XOR'd with BRAM data
        # If BRAM has data: K2 toggles (counter XOR BRAM bits)
        # If BRAM is zero: K2 just shows counter
        diag_hb = platform.request("diag_heartbeat")
        counter = Signal(25)
        self.sync += counter.eq(counter + 1)
        self.comb += diag_hb.eq(counter[24] ^ rd_port.dat_r[0])


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BRAM Init Diagnostic")
    parser.add_argument("--variant", default="cle-101",
                        choices=["cle-215+", "cle-215", "cle-101"])
    parser.add_argument("--toolchain", default="openxc7")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    platform.add_extension(_diag_io)

    if args.toolchain == "openxc7":
        fix_openxc7_device_name(platform)
        ensure_chipdb_symlink(platform)
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    module = DiagBRAM(platform)
    build_dir = str(Path(__file__).resolve().parent / "build" / "diag_bram")
    platform.build(module, build_dir=build_dir, run=args.build)


if __name__ == "__main__":
    main()
