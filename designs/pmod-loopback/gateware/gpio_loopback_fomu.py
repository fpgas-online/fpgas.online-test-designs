#!/usr/bin/env python3
"""Pure GPIO loopback test for Fomu EVT.

Half-PMOD A (4 pins) = input
Half-PMOD B (4 pins) = output
Output = ~Input (bitwise inversion)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from litex_boards.platforms.kosagi_fomu_evt import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, flow_suffix

_loopback_io = [
    ("loopback_in", 0,
        Pins("pmoda_n:0 pmoda_n:1 pmoda_n:2 pmoda_n:3"),
        IOStandard("LVCMOS33")),
    ("loopback_out", 0,
        Pins("pmodb_n:0 pmodb_n:1 pmodb_n:2 pmodb_n:3"),
        IOStandard("LVCMOS33")),
]


class GPIOLoopback(Module):
    def __init__(self, platform):
        inp = platform.request("loopback_in")
        out = platform.request("loopback_out")
        self.comb += out.eq(~inp)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPIO Loopback for Fomu EVT")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(toolchain="icestorm")
    platform.add_extension(_loopback_io)

    module = GPIOLoopback(platform)

    if args.build:
        # Write to build/fomu-evt-yosys-nextpnr/gateware/kosagi_fomu_evt.bin
        # to match LiteX Builder's layout used by the other designs.
        board = board_dir("fomu", "evt") + flow_suffix("icestorm")
        build_dir = str(
            Path(__file__).resolve().parent.parent / "build" / board / "gateware"
        )
        platform.build(module, build_dir=build_dir, build_name=platform.name)


if __name__ == "__main__":
    main()
