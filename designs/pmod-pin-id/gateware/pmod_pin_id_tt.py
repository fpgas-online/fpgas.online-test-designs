#!/usr/bin/env python3
"""PMOD pin identification design for TinyTapeout FPGA Demo Board.

Each of the 24 PMOD data pins (tt_input + tt_output + tt_bidir)
continuously transmits its FPGA pin number (e.g. "13\\r\\n") as
1200-baud 8N1 UART. Connect any RPi GPIO to any PMOD pin and decode
the name to determine the cable mapping.

Pin names are extracted from the LiteX platform's connector definitions,
so the output matches the iCE40 package pin numbers exactly.

Six of the 24 take turns (#142). The Digilent Pmod HAT joins its JA pins 2-4 and JB pins 2-4 on the same three
Raspberry Pi GPIOs (10, 9, 11), and the fleet cables ui_in to JA and uio to JB: so ui_in[1..3] and uio[1..3]
end on the same three wires at the Pi, and two senders there at once collide. ui_in[1..3] send for TURN_S
while uio[1..3] are high impedance, then nobody for GAP_S, then the reverse: the Pi hears both pin numbers on
each of the three GPIOs, one after the other, and every one of the 24 wires is tested on its own. The other
18 pins send all the time, as before.

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
from designs._shared.build_helpers import board_dir, flow_suffix
from designs._shared.platform_fixups import require_timing
from designs._shared.tt_fpga_platform import Platform

# Use connector names (not _io resource names) to avoid conflicts
# with the pre-defined ui_in/uo_out/uio bus resources.
CONNECTORS = ["tt_input", "tt_output", "tt_bidir"]

BAUD_RATE = 1200
SYS_CLK_FREQ = 50e6

# The pins that share a wire at the Pi, by (connector, index): which group's turn they send in.
SHARED = {("tt_input", i): 0 for i in (1, 2, 3)} | {("tt_bidir", i): 1 for i in (1, 2, 3)}
# A turn is about a dozen labels ("19\r\n" is 4 characters, 37 ms at 1200 baud with the idle bit between
# characters). The gap is longer than a label, so the group whose turn ended has finished its last label, and
# released its pins, before the other group starts.
TURN_S = 0.4
GAP_S = 0.1
CYCLE_S = 2 * (TURN_S + GAP_S)


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


def turn_of(resource_pin):
    """The group (0 or 1) whose turn a shared pin sends in; None for a pin with a wire of its own."""
    connector, index = resource_pin.split(":")
    return SHARED.get((connector, int(index)))


class Turns(Module):
    """`run[g]` is high while it is group g's turn: g 0 for `turn_ms`, nobody for `gap_ms`, g 1 for `turn_ms`,
    nobody for `gap_ms`, and round again. Time is counted in milliseconds of `ticks_per_ms` clock cycles (a short
    counter and registered outputs: one long counter compared at the 50 MHz clock missed timing on the iCE40)."""

    def __init__(self, ticks_per_ms, turn_ms, gap_ms):
        self.run = [Signal(), Signal()]
        period = 2 * (turn_ms + gap_ms)
        tick = Signal(max=ticks_per_ms)
        self.ms = ms = Signal(max=period)
        each_ms = Signal()
        self.sync += [
            each_ms.eq(tick == ticks_per_ms - 2),
            If(each_ms, tick.eq(0)).Else(tick.eq(tick + 1)),
            If(each_ms, If(ms == period - 1, ms.eq(0)).Else(ms.eq(ms + 1))),
            self.run[0].eq(ms < turn_ms),
            self.run[1].eq((ms >= turn_ms + gap_ms) & (ms < 2 * turn_ms + gap_ms)),
        ]


def build_io_extensions(pin_list):
    """Build IO extensions: one single-bit output per pin."""
    return [
        (f"pin_id_{i}", 0, Pins(resource_pin), IOStandard("LVCMOS33"))
        for i, (resource_pin, _label) in enumerate(pin_list)
    ]


class PMODPinIdentifier(Module):
    def __init__(self, platform, pin_list):
        # iCE40 needs an explicit clock domain — connect clk_rp2040 directly to sync.
        clk = platform.request("clk_rp2040")
        self.clock_domains.cd_sys = ClockDomain("sys")
        self.comb += self.cd_sys.clk.eq(clk)

        self.submodules.turns = turns = Turns(int(SYS_CLK_FREQ // 1000), int(TURN_S * 1000), int(GAP_S * 1000))
        for i, (resource_pin, label) in enumerate(pin_list):
            pin = platform.request(f"pin_id_{i}")
            group = turn_of(resource_pin)
            if group is None:
                self.submodules += UARTTxIdentifier(pin, label, int(SYS_CLK_FREQ), baud=BAUD_RATE)
                continue
            # A shared wire: driven only while this pin sends a label, in its group's turn.
            pad = TSTriple()
            self.specials += pad.get_tristate(pin)
            tx = UARTTxIdentifier(pad.o, label, int(SYS_CLK_FREQ), baud=BAUD_RATE, run=turns.run[group])
            self.submodules += tx
            self.comb += pad.oe.eq(tx.sending)


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

    require_timing(platform, {})  # runs on the board clock, which the platform constrains
    if args.build:
        # Write to build/tt-fpga-yosys-nextpnr/gateware/<platform>.bin to
        # match LiteX Builder's layout used by the other designs.
        board = board_dir("tt", "fpga") + flow_suffix("icestorm")
        build_dir = str(
            Path(__file__).resolve().parent.parent / "build" / board / "gateware"
        )
        platform.build(module, build_dir=build_dir, build_name=platform.name)


if __name__ == "__main__":
    main()
