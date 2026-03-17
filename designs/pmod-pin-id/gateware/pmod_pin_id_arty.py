#!/usr/bin/env python3
"""PMOD pin identification design for Digilent Arty A7.

Each of the 32 PMOD data pins continuously transmits its own name
(e.g. "JA01\\r\\n") as 1200-baud 8N1 UART. Connect any RPi GPIO to
any PMOD pin and decode the name to determine the cable mapping.

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *
from litex.build.generic_platform import Pins, IOStandard, Subsignal
from litex_boards.platforms.digilent_arty import Platform

from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO
from pmod_pin_id import UARTTxIdentifier

# PMOD connector names and their physical pin-to-index mapping.
# LiteX indices 0-3 = physical pins 1-4 (top row)
# LiteX indices 4-7 = physical pins 7-10 (bottom row)
INDEX_TO_PHYSICAL = {0: 1, 1: 2, 2: 3, 3: 4, 4: 7, 5: 8, 6: 9, 7: 10}

# Arty PMOD connectors (matching board silkscreen)
PMOD_CONNECTORS = ["JA", "JB", "JC", "JD"]
PMOD_RESOURCES = ["pmoda", "pmodb", "pmodc", "pmodd"]

BAUD_RATE = 1200
SYS_CLK_FREQ = 100e6


def build_pin_list():
    """Build list of (resource_pin, label) for all 32 PMOD data pins."""
    pins = []
    for connector, resource in zip(PMOD_CONNECTORS, PMOD_RESOURCES):
        for idx, phys in INDEX_TO_PHYSICAL.items():
            resource_pin = f"{resource}:{idx}"
            label = f"{connector}{phys:02d}\r\n"
            pins.append((resource_pin, label))
    return pins


# Build IO extensions: one single-bit output per PMOD pin.
_pin_list = build_pin_list()
_pin_id_io = [
    (f"pin_id_{i}", 0, Pins(resource_pin), IOStandard("LVCMOS33"))
    for i, (resource_pin, _label) in enumerate(_pin_list)
]


class PMODPinIdentifier(Module):
    def __init__(self, platform):
        for i, (_resource_pin, label) in enumerate(_pin_list):
            pin = platform.request(f"pin_id_{i}")
            tx = UARTTxIdentifier(pin, label, int(SYS_CLK_FREQ), baud=BAUD_RATE)
            self.submodules += tx


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PMOD Pin Identification for Arty A7")
    parser.add_argument("--variant", default="a7-35", choices=["a7-35", "a7-100"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    platform.add_extension(_pin_id_io)

    module = PMODPinIdentifier(platform)

    # Apply yosys workaround for openxc7
    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "arty")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
