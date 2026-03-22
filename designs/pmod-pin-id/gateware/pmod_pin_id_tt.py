#!/usr/bin/env python3
"""PMOD pin identification design for TinyTapeout FPGA Demo Board.

Each of the 24 PMOD data pins (tt_input + tt_output + tt_bidir)
continuously transmits its FPGA pin number (e.g. "13\\r\\n") as
1200-baud 8N1 UART. Connect any RPi GPIO to any PMOD pin and decode
the name to determine the cable mapping.

Pin names are extracted from the LiteX platform's connector definitions,
so the output matches the iCE40 package pin numbers exactly.

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from migen import *
from pmod_pin_id import UARTTxIdentifier

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.tt_fpga_platform import Platform


# Use connector names (not _io resource names) to avoid conflicts
# with the pre-defined ui_in/uo_out/uio bus resources.
CONNECTORS = ["tt_input", "tt_output", "tt_bidir"]

BAUD_RATE = 1200
SYS_CLK_FREQ = 50e6


def build_pin_list(platform):
    """Build list of (resource_pin, label) using FPGA pin names from platform.

    Extracts pin names from the platform's connector table so the
    transmitted label is the actual iCE40 package pin number (e.g. "13").
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
    parser = argparse.ArgumentParser(description="PMOD Pin Identification for TT FPGA Demo Board")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(toolchain="icestorm")

    pin_list = build_pin_list(platform)
    platform.add_extension(build_io_extensions(pin_list))

    # Print the pin mapping for reference
    print(f"PMOD Pin ID: {len(pin_list)} pins")
    for resource_pin, label in pin_list:
        print(f"  {resource_pin:14s} -> {label.strip()!r}")

    module = PMODPinIdentifier(platform, pin_list)

    if args.build:
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / "tt")
        platform.build(module, build_dir=build_dir)


if __name__ == "__main__":
    main()
