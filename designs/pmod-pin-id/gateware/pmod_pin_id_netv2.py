#!/usr/bin/env python3
"""Pin identification design for Kosagi NeTV2.

The NeTV2 connects to the RPi via GPIO header (not PMOD HAT). Only
the serial pins (E13 RX, E14 TX) are exposed to the RPi. Each pin
continuously transmits its FPGA ball name (e.g. "E14\\r\\n") as
1200-baud 8N1 UART.

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from litex_boards.platforms.kosagi_netv2 import Platform
from migen import *
from pmod_pin_id import UARTTxIdentifier

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO


# NeTV2 GPIO header pins connected to RPi (hardcoded, not from connector table).
# These are the serial pins used for UART communication with the RPi.
_pin_id_io = [
    ("pin_id_0", 0, Pins("E14"), IOStandard("LVCMOS33")),  # serial TX → RPi GPIO15
    ("pin_id_1", 0, Pins("E13"), IOStandard("LVCMOS33")),  # serial RX → RPi GPIO14
]

PIN_LIST = [
    ("E14", "E14\r\n"),  # serial TX
    ("E13", "E13\r\n"),  # serial RX
]

BAUD_RATE = 1200
SYS_CLK_FREQ = 50e6


class PinIdentifier(Module):
    def __init__(self, platform):
        for i, (_fpga_pin, label) in enumerate(PIN_LIST):
            pin = platform.request(f"pin_id_{i}")
            tx = UARTTxIdentifier(pin, label, int(SYS_CLK_FREQ), baud=BAUD_RATE)
            self.submodules += tx


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pin Identification for NeTV2")
    parser.add_argument("--variant", default="a7-100", choices=["a7-35", "a7-100"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)

    if args.toolchain == "openxc7":
        fix_openxc7_device_name(platform)
        ensure_chipdb_symlink(platform)

    platform.add_extension(_pin_id_io)

    # Print the pin mapping for reference
    print(f"Pin ID: {len(PIN_LIST)} pins")
    for fpga_pin, label in PIN_LIST:
        print(f"  {fpga_pin:6s} -> {label.strip()!r}")

    module = PinIdentifier(platform)

    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "netv2")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
