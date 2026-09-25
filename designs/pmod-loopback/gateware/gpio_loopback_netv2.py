#!/usr/bin/env python3
"""Pure GPIO loopback test for Kosagi NeTV2.

Uses the serial pins (E13 input, E14 output) as GPIO.
Output = ~Input (bitwise inversion on 1 bit).

RPi GPIO14 drives → FPGA E13 → inverted → FPGA E14 → RPi GPIO15 reads.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex_boards.platforms.kosagi_netv2 import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, flow_suffix
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO


class GPIOLoopback(Module):
    def __init__(self, platform):
        serial = platform.request("serial")
        # serial.rx = input (from RPi GPIO14)
        # serial.tx = output (to RPi GPIO15)
        self.comb += serial.tx.eq(~serial.rx)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GPIO Loopback for NeTV2")
    parser.add_argument("--variant", default="a7-100", choices=["a7-35", "a7-100"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--synth-mode", default=None, choices=["vivado", "yosys"],
                        help="Vivado synthesis mode (only honoured with "
                             "--toolchain=vivado; default vivado. Use 'yosys' "
                             "for the Yosys→Vivado hybrid flow).")
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
        # Write to build/<board>-<variant>-<flow>/gateware/<platform>.bit
        # to match LiteX Builder's layout used by the other designs.
        build_dir = str(
            Path(__file__).resolve().parent.parent
            / "build"
            / f"{board_dir('netv2', args.variant)}{flow_suffix(args.toolchain, args.synth_mode)}"
            / "gateware"
        )
        build_kwargs = {"build_dir": build_dir, "build_name": platform.name}
        if args.toolchain == "vivado":
            build_kwargs["synth_mode"] = args.synth_mode or "vivado"
        platform.build(module, **build_kwargs)


if __name__ == "__main__":
    main()
