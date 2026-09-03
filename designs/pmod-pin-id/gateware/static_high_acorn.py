#!/usr/bin/env python3
"""Minimal Acorn diagnostic: drive K2, J2, J5, H5 statically HIGH.

No clock, no sync logic, no UART — just four combinational `pin.eq(1)` lines.
If the RPi reads all four pins as HIGH, then the FPGA output buffers and the
P2 cable are healthy. Any pin reading LOW indicates either an FPGA output
driver failure for that ball (unlikely) or a cable short to GND on that wire.

This isolates the "is the gateware logic running" question from the
"can the FPGA drive these pins" question.

Run:
    uv run python gateware/static_high_acorn.py --build
Then load:
    openFPGALoader -c libgpiod --pins 10:9:11:8 build/static_high/top.bit
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from litex_boards.platforms.sqrl_acorn import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO

_pin_id_io = [
    ("pin_id_0", 0, Pins("K2"), IOStandard("LVCMOS33")),
    ("pin_id_1", 0, Pins("J2"), IOStandard("LVCMOS33")),
    ("pin_id_2", 0, Pins("J5"), IOStandard("LVCMOS33")),
    ("pin_id_3", 0, Pins("H5"), IOStandard("LVCMOS33")),
]


class StaticHigh(Module):
    def __init__(self, platform):
        for i in range(4):
            pin = platform.request(f"pin_id_{i}")
            self.comb += pin.eq(1)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="cle-215+")
    parser.add_argument("--toolchain", default="openxc7")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    platform.add_extension(_pin_id_io)

    if args.toolchain == "openxc7":
        fix_openxc7_device_name(platform)
        ensure_chipdb_symlink(platform)

    module = StaticHigh(platform)

    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "static_high")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
