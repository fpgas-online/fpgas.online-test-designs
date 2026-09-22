"""Simulation tests for the UART break detector (designs/_shared/uart_break.py)."""

from migen import run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.uart_break import UARTBreakDetector

CLK_FREQ = 10_000  # a slow simulated clock keeps the cycle counts small
BREAK_S = 0.05  # 50 ms -> 500 cycles
CYCLES = int(CLK_FREQ * BREAK_S)


def _run(stimulus):
    """Drive `rx` from a list of (level, cycles) and return the cycles on which `detected` was high."""
    dut = UARTBreakDetector(clk_freq=CLK_FREQ, break_s=BREAK_S)
    hits = []

    def bench():
        cycle = 0
        for level, n in stimulus:
            yield dut.rx.eq(level)
            for _ in range(n):
                yield
                if (yield dut.detected):
                    hits.append(cycle)
                cycle += 1

    run_simulation(dut, bench())
    return hits


def test_idle_line_never_fires():
    assert _run([(1, 3 * CYCLES)]) == []


def test_a_zero_byte_at_1200_baud_does_not_fire():
    # Start bit + 8 zero data bits = 9 bit times low = 7.5 ms, well short of 50 ms.
    low = int(CLK_FREQ * 9 / 1200)
    assert low < CYCLES
    assert _run([(1, 20), (0, low), (1, 20)] * 5) == []


def test_a_low_just_short_of_the_threshold_does_not_fire():
    assert _run([(1, 20), (0, CYCLES - 10), (1, 50)]) == []


def test_a_break_fires_exactly_once_however_long_it_lasts():
    hits = _run([(1, 20), (0, 4 * CYCLES), (1, 50)])
    assert len(hits) == 1
    # Not before the threshold; a few cycles of synchroniser latency after it.
    assert CYCLES <= hits[0] - 20 <= CYCLES + 8


def test_it_rearms_after_the_line_returns_high():
    hits = _run([(1, 20), (0, 2 * CYCLES), (1, 50), (0, 2 * CYCLES), (1, 50)])
    assert len(hits) == 2


def test_a_glitch_high_restarts_the_count():
    # Two lows that only add up to a break must not count as one.
    assert _run([(1, 20), (0, CYCLES - 50), (1, 5), (0, CYCLES - 50), (1, 50)]) == []
