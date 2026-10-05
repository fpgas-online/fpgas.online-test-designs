"""Simulation of the pattern the TT FPGA's boot check leaves on the display (designs/tt-display, #139)."""

import importlib.util
import pathlib

import pytest

pytest.importorskip("migen")
pytest.importorskip("litex")

from migen import Signal, run_simulation

_spec = importlib.util.spec_from_file_location(
    "tt_display", pathlib.Path(__file__).parents[1] / "designs/tt-display/gateware/tt_display.py")  # fmt: skip
tt_display = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tt_display)

TICKS = 3  # clock cycles to a step: small, so a few seconds of pattern are a few hundred cycles
RING, STEP_HZ = tt_display.RING, tt_display.STEP_HZ


def _steps(n):
    """uo_out at each of the first `n` steps."""
    uo_out = Signal(8)
    dut = tt_display.Pattern(uo_out, TICKS)
    seen = []

    def bench():
        for _ in range(n):
            seen.append((yield uo_out))
            for _ in range(TICKS):
                yield

    run_simulation(dut, bench())
    return seen


def test_one_segment_runs_round_the_ring_and_the_middle_changes_each_lap():
    seen = _steps(4 * RING)
    assert [v & 0x3F for v in seen] == [1 << (i % RING) for i in range(4 * RING)]  # a, b, c, d, e, f, a, ...
    assert [(v >> 6) & 1 for v in seen] == [(i // RING) % 2 for i in range(4 * RING)]  # g: off a lap, on a lap


def test_the_dot_is_lit_for_the_first_half_of_each_second():
    seen = _steps(3 * STEP_HZ)
    assert [(v >> 7) & 1 for v in seen] == [1 if i % STEP_HZ < STEP_HZ // 2 else 0 for i in range(3 * STEP_HZ)]


def test_every_segment_is_used_and_the_display_never_stands_still():
    seen = _steps(2 * RING * STEP_HZ)
    lit = 0
    for v in seen:
        lit |= v
    assert lit == 0xFF  # all seven segments and the dot
    assert all(a != b for a, b in zip(seen, seen[1:]))  # every step changes what is shown
    assert tt_display.LFOSC_HZ // STEP_HZ == 1250  # an eighth of a second a step at the oscillator's 10 kHz


def test_the_design_takes_nothing_from_the_microcontroller_and_drives_only_uo_out():
    """It is left running across resets of the RP2350, whose clock and reset lines then mean nothing."""
    platform = tt_display.Platform(toolchain="icestorm")
    tt_display.Display(platform)
    taken = {resource[0] for resource, _signal in platform.constraint_manager.matched}
    assert taken == {"uo_out"}
