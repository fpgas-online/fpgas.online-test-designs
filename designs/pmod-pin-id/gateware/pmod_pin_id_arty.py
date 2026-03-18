#!/usr/bin/env python3
"""PMOD pin identification design for Digilent Arty A7.

Each of the 32 PMOD data pins continuously transmits its FPGA pin name
(e.g. "G13\\r\\n") as 1200-baud 8N1 UART. Connect any RPi GPIO to
any PMOD pin and decode the name to determine the cable mapping.

Pin names are extracted from the LiteX platform's connector definitions,
so the output matches the FPGA package ball names exactly.

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from litex_boards.platforms.digilent_arty import Platform
from migen import *
from pmod_pin_id import UARTTxIdentifier

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO

# Connector names to scan (all PMOD connectors on the Arty).
CONNECTORS = ["pmoda", "pmodb", "pmodc", "pmodd"]

BAUD_RATE = 1200
SYS_CLK_FREQ = 100e6


def build_pin_list(platform):
    """Build list of (resource_pin, label) using FPGA pin names from platform.

    Extracts pin names from the platform's connector table so the
    transmitted label is the actual FPGA ball name (e.g. "G13").
    """
    pins = []
    for connector_name in CONNECTORS:
        connector_pins = platform.constraint_manager.connector_manager.connector_table[connector_name]
        for idx in range(len(connector_pins)):
            resource_pin = f"{connector_name}:{idx}"
            fpga_pin = connector_pins[idx]
            label = f"{fpga_pin}\r\n"
            pins.append((resource_pin, label))
    return pins


def build_io_extensions(pin_list):
    """Build IO extensions: one single-bit output per pin."""
    return [
        (f"pin_id_{i}", 0, Pins(resource_pin), IOStandard("LVCMOS33"))
        for i, (resource_pin, _label) in enumerate(pin_list)
    ]


class PMODPinIdentifier(Module):
    def __init__(self, platform, pin_list):
        for i, (_resource_pin, label) in enumerate(pin_list):
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

    pin_list = build_pin_list(platform)
    platform.add_extension(build_io_extensions(pin_list))

    # Print the pin list for reference during build.
    print(f"PMOD Pin ID: {len(pin_list)} pins")
    for resource_pin, label in pin_list:
        print(f"  {resource_pin:10s} -> {label.strip()!r}")

    module = PMODPinIdentifier(platform, pin_list)

    # Apply yosys workaround for openxc7
    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "arty")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
