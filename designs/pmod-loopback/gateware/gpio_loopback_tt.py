#!/usr/bin/env python3
"""Pure GPIO loopback test for TinyTapeout FPGA Demo Board.

ui_in[0:7]  (8 pins) = input from RPi PMOD HAT
uo_out[0:7] (8 pins) = output to RPi PMOD HAT
Output = ~Input (bitwise inversion)

No CPU, no UART, no firmware. The RPi drives ui_in pins via the
PMOD HAT and reads uo_out pins to verify the connection.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.tt_fpga_platform import Platform


class GPIOLoopback(Module):
    def __init__(self, platform):
        inp = platform.request("ui_in")
        out = platform.request("uo_out")
        self.comb += out.eq(~inp)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPIO Loopback for TT FPGA")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(toolchain="icestorm")

    module = GPIOLoopback(platform)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "tt")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
