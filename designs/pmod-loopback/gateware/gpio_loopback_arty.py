#!/usr/bin/env python3
"""Pure GPIO loopback test for Digilent Arty A7.

PMOD A (8 pins) = input from RPi PMOD HAT
PMOD B (8 pins) = output to RPi PMOD HAT
Output = ~Input (bitwise inversion)

No CPU, no UART, no firmware. The RPi drives PMOD A pins via the
PMOD HAT and reads PMOD B pins to verify the connection.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from migen import *
from litex.build.generic_platform import Pins, IOStandard
from litex_boards.platforms.digilent_arty import Platform

from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO


# Pin extension: use PMOD A as input, PMOD B as output.
_loopback_io = [
    ("loopback_in", 0,
        Pins("pmoda:0 pmoda:1 pmoda:2 pmoda:3 pmoda:4 pmoda:5 pmoda:6 pmoda:7"),
        IOStandard("LVCMOS33")),
    ("loopback_out", 0,
        Pins("pmodb:0 pmodb:1 pmodb:2 pmodb:3 pmodb:4 pmodb:5 pmodb:6 pmodb:7"),
        IOStandard("LVCMOS33")),
]


class GPIOLoopback(Module):
    def __init__(self, platform):
        inp = platform.request("loopback_in")
        out = platform.request("loopback_out")
        self.comb += out.eq(~inp)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPIO Loopback for Arty A7")
    parser.add_argument("--variant", default="a7-35", choices=["a7-35", "a7-100"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    platform.add_extension(_loopback_io)

    module = GPIOLoopback(platform)

    # Apply yosys workaround for openxc7
    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "arty")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
