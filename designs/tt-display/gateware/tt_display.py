#!/usr/bin/env python3
"""A moving pattern for the TinyTapeout FPGA Demo Board's seven-segment display.

The boot check leaves this design in the FPGA when it is done, so the board shows something alive on
its camera until a visitor loads a design of their own (issue #139). It is not a test: nothing reads it.

It needs nothing from the demo board's microcontroller once it is loaded: its clock is the iCE40's own
low-frequency oscillator (SB_LFOSC, 10 kHz), and it does not look at `clk`, `rst_n` or `ui_in`, whose
levels after the microcontroller is reset are not known. It drives `uo_out` only (the display: bits 0 to 6
are segments a to g, bit 7 is the dot); every other pin stays an input, so it never drives against the
microcontroller. `ui_in` and `uio` are held as inputs with the iCE40's pull-up off: the boot check reads the
demo board's DIP switches on `ui_in` under this design, with a pull-down (#166).

The pattern, in steps of an eighth of a second: one segment runs round the outer ring (a, b, c, d, e, f);
the middle segment (g) changes at each lap; the dot blinks once a second. All eight segments are used.

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

# Add repo root so designs._shared is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, flow_suffix
from designs._shared.tt_fpga_platform import Platform

LFOSC_HZ = 10_000  # SB_LFOSC, nominal
STEP_HZ = 8  # ring steps a second
RING = 6  # segments a to f


class Pattern(Module):
    """`uo_out` from a step counter: `ticks_per_step` clock cycles to a step."""

    def __init__(self, uo_out, ticks_per_step):
        tick = Signal(max=ticks_per_step)
        self.ring = ring = Signal(max=RING)  # which outer segment is lit
        self.middle = middle = Signal()  # segment g: changes at each lap
        self.steps = steps = Signal(max=STEP_HZ)  # steps into the current second
        self.dot = dot = Signal()  # lit for the first half of each second
        step = Signal()
        self.comb += step.eq(tick == ticks_per_step - 1)
        self.sync += [
            tick.eq(tick + 1),
            If(step,
                tick.eq(0),
                ring.eq(ring + 1),
                If(ring == RING - 1, ring.eq(0), middle.eq(~middle)),
                steps.eq(steps + 1),
                If(steps == STEP_HZ - 1, steps.eq(0)),
            ),
        ]  # fmt: skip
        self.comb += [
            dot.eq(steps < STEP_HZ // 2),
            uo_out.eq(Cat(*[ring == i for i in range(RING)], middle, dot)),
        ]


class Display(Module):
    def __init__(self, platform):
        clk = Signal()
        # The iCE40UP5K's own 10 kHz oscillator: always on, no pin, nothing from the microcontroller.
        self.specials += Instance("SB_LFOSC", i_CLKLFEN=1, i_CLKLFPU=1, o_CLKLF=clk)
        self.clock_domains.cd_sys = ClockDomain("sys", reset_less=True)
        self.comb += self.cd_sys.clk.eq(clk)
        self.submodules.pattern = Pattern(platform.request("uo_out"), LFOSC_HZ // STEP_HZ)
        # ui_in and uio: plain inputs with the iCE40's pull-up off (#166). A pin a design does not use keeps the
        # iCE40's weak pull-up (the bitstream leaves its REN bit clear), and on these lines that pull-up would
        # stand against the pull-down the check's DIP switch read relies on (dip_switches.py). Nothing reads them.
        for name in ("ui_in", "uio"):
            pads = platform.request(name)
            for i in range(len(pads)):
                self.specials += Instance("SB_IO", p_PIN_TYPE=C(0b000001, 6), p_PULLUP=C(0, 1),
                                          io_PACKAGE_PIN=pads[i], o_D_IN_0=Signal())  # fmt: skip


def main():
    import argparse

    parser = argparse.ArgumentParser(description="A moving display pattern for the TT FPGA Demo Board")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(toolchain="icestorm")
    module = Display(platform)
    platform.add_period_constraint(module.cd_sys.clk, 1e9 / LFOSC_HZ)
    if args.build:
        # build/tt-fpga-yosys-nextpnr/gateware/<platform>.bin, the layout of the other designs.
        board = board_dir("tt", "fpga") + flow_suffix("icestorm")
        build_dir = str(Path(__file__).resolve().parent.parent / "build" / board / "gateware")
        platform.build(module, build_dir=build_dir, build_name=platform.name)


if __name__ == "__main__":
    main()
