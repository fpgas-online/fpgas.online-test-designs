#!/usr/bin/env python3
"""Pure GPIO loopback test for Kosagi NeTV2.

Uses the serial pins (E13 input, E14 output) as GPIO.
Output = ~Input (bitwise inversion on 1 bit).

RPi GPIO14 drives → FPGA E13 → inverted → FPGA E14 → RPi GPIO15 reads.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *
from litex_boards.platforms.kosagi_netv2 import Platform

from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO
from designs._shared.platform_fixups import fix_openxc7_device_name, ensure_chipdb_symlink


class GPIOLoopback(Module):
    def __init__(self, platform):
        serial = platform.request("serial")
        # serial.rx = input (from RPi GPIO14)
        # serial.tx = output (to RPi GPIO15)
        self.comb += serial.tx.eq(~serial.rx)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPIO Loopback for NeTV2")
    parser.add_argument("--variant", default="a7-35", choices=["a7-35", "a7-100"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)

    if args.toolchain == "openxc7":
        fix_openxc7_device_name(platform)
        ensure_chipdb_symlink(platform)

    module = GPIOLoopback(platform)

    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "netv2")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
