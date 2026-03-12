#!/usr/bin/env python3
"""Pure GPIO loopback test for Digilent Arty A7.

Uses a single PMOD connector (JA / pmoda) for both input and output.
A 6-pin PMOD cable connects the RPi PMOD HAT JA bottom row to the
Arty PMOD A bottom row (pins 7-10 only; pins 1-4 are not connected):

  - Bottom row pins 7-8  (pmoda:4-5) = input from RPi PMOD HAT
  - Bottom row pins 9-10 (pmoda:6-7) = output to RPi PMOD HAT

Output = ~Input (2-bit bitwise inversion)

No CPU, no UART, no firmware. The RPi drives JA pins 7-8 via the
PMOD HAT and reads JA pins 9-10 to verify the connection.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *
from litex.build.generic_platform import Pins, IOStandard
from litex_boards.platforms.digilent_arty import Platform

from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO


# Pin extension: bottom row of PMOD A, split into input and output halves.
# A 6-pin PMOD cable connects only the bottom row (pins 7-10).
#   pmoda:4 (pin 7) and pmoda:5 (pin 8)  = input  (RPi drives)
#   pmoda:6 (pin 9) and pmoda:7 (pin 10) = output (RPi reads)
_loopback_io = [
    ("loopback_in", 0,
        Pins("pmoda:4 pmoda:5"),
        IOStandard("LVCMOS33")),
    ("loopback_out", 0,
        Pins("pmoda:6 pmoda:7"),
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
