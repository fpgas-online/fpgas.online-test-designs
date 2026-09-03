#!/usr/bin/env python3
"""Pure GPIO loopback test for Sqrl Acorn CLE-215+ / NiteFury / LiteFury.

Uses the serial pins (J2 input, K2 output) as GPIO.
Output = ~Input (bitwise inversion on 1 bit).

RPi GPIO14 drives → FPGA J2 → inverted → FPGA K2 → RPi GPIO15 reads.

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex_boards.platforms.sqrl_acorn import Platform
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, flow_suffix
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO


class GPIOLoopback(Module):
    def __init__(self, platform):
        serial = platform.request("serial")
        # serial.rx = input (from RPi GPIO14 via P2 header)
        # serial.tx = output (to RPi GPIO15 via P2 header)
        self.comb += serial.tx.eq(~serial.rx)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="GPIO Loopback for Acorn/LiteFury")
    parser.add_argument("--variant", default="cle-215+", choices=["cle-215+", "cle-215", "cle-101"])
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
            / f"{board_dir('acorn', args.variant)}{flow_suffix(args.toolchain, args.synth_mode)}"
            / "gateware"
        )
        build_kwargs = {"build_dir": build_dir, "build_name": platform.name}
        if args.toolchain == "vivado":
            build_kwargs["synth_mode"] = args.synth_mode or "vivado"
        platform.build(module, **build_kwargs)


if __name__ == "__main__":
    main()
