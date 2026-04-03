#!/usr/bin/env python3
"""Diagnostic: PLL lock + heartbeat on Acorn/LiteFury.

Pure gateware (no CPU). Outputs:
  K2 (→ GPIO15) → heartbeat from sys_clk (toggles every ~0.34s at 50 MHz)
  J2 (→ GPIO14) → PLL LOCKED signal (active HIGH when PLL has locked)

If K2 toggles at ~1.5 Hz: PLL locked, sys_clk runs at 50 MHz.
If J2 is HIGH: PLL reports locked.
If both stay static: PLL doesn't lock or clock input not working.

Also outputs on user LEDs (if visible):
  LED0 = PLL LOCKED
  LED1 = heartbeat
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex_boards.platforms.sqrl_acorn import Platform
from litex.soc.cores.clock import S7PLL
from migen import *

import designs._shared.migen_compat  # noqa: F401
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO

SYS_CLK_FREQ = 50e6

# Define K2 and J2 as explicit outputs (not using the "serial" resource
# which defines rx as input).
_diag_io = [
    ("diag_heartbeat", 0, Pins("K2"), IOStandard("LVCMOS33"), Misc("SLEW=FAST")),
    ("diag_pll_locked", 0, Pins("J2"), IOStandard("LVCMOS33"), Misc("SLEW=FAST")),
]


class DiagPLL(Module):
    def __init__(self, platform):
        # Clock domain
        self.clock_domains.cd_sys = ClockDomain("sys")

        # Request clock
        clk200 = platform.request("clk200")

        # PLL: 200 MHz differential → 50 MHz sys_clk
        self.submodules.pll = pll = S7PLL()
        pll.vco_margin = 0.25  # Keep VCO ≤ 1200 MHz (away from 1600 limit)
        self.comb += pll.reset.eq(0)  # Never assert PLL reset
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, SYS_CLK_FREQ)

        # Output PLL LOCKED on J2 (→ GPIO14)
        diag_locked = platform.request("diag_pll_locked")
        self.comb += diag_locked.eq(pll.locked)

        # Heartbeat counter on K2 (→ GPIO15)
        # At 50 MHz, bit 24 toggles every 2^24 / 50e6 ≈ 0.34s → ~1.5 Hz
        diag_hb = platform.request("diag_heartbeat")
        counter = Signal(25)
        self.sync += counter.eq(counter + 1)
        self.comb += diag_hb.eq(counter[24])

        # Also drive LEDs (might not be visible on Compute Blade but good practice)
        try:
            led0 = platform.request("user_led", 0)
            self.comb += led0.eq(pll.locked)
        except Exception:
            pass
        try:
            led1 = platform.request("user_led", 1)
            self.comb += led1.eq(counter[24])
        except Exception:
            pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PLL Diagnostic for Acorn/LiteFury")
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

    module = DiagPLL(platform)

    build_dir = str(Path(__file__).resolve().parent / "build" / "diag_pll")
    platform.build(module, build_dir=build_dir, run=args.build)


if __name__ == "__main__":
    main()
