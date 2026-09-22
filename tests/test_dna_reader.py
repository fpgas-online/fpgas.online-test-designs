"""Simulation tests for the slow DNA reader (designs/_shared/dna_reader.py), against a model of DNA_PORT."""

from migen import run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.dna_reader import NBITS, DNAReader

DNA = 0x0123456789ABCDE & (2**NBITS - 1) | (1 << (NBITS - 1))  # MSB set, so a lost first bit shows


def _run(dut, cycles):
    """Clock `dut` with a behavioural DNA_PORT on its pins; return (final id, shortest clk phase seen)."""
    state = {"sr": 0, "prev": 0, "phase": 0, "shortest": None, "id": None}

    def bench():
        for _ in range(cycles):
            clk = yield dut.clk
            if clk and not state["prev"]:  # rising edge: READ loads, else SHIFT moves one bit towards DOUT
                if (yield dut.read):
                    state["sr"] = DNA
                elif (yield dut.shift):
                    state["sr"] = (state["sr"] << 1) & (2**NBITS - 1)
            if clk != state["prev"]:
                if state["phase"] and (state["shortest"] is None or state["phase"] < state["shortest"]):
                    state["shortest"] = state["phase"]
                state["phase"] = 0
            state["phase"] += 1
            state["prev"] = clk
            yield dut.dout.eq(state["sr"] >> (NBITS - 1))
            yield
        state["id"] = yield dut._id.status
        state["done"] = yield dut.done

    run_simulation(dut, bench())
    return state


def test_it_reads_all_57_bits_msb_first():
    dut = DNAReader(sys_clk_freq=16e6, port_clk_freq=1e6, with_primitive=False)
    state = _run(dut, cycles=2 * dut.half_period * (NBITS + 4))
    assert state["done"] == 1
    assert state["id"] == DNA


def test_every_clock_phase_lasts_a_full_half_period():
    dut = DNAReader(sys_clk_freq=16e6, port_clk_freq=1e6, with_primitive=False)
    state = _run(dut, cycles=2 * dut.half_period * (NBITS + 4))
    assert dut.half_period == 8
    assert state["shortest"] >= dut.half_period


def test_the_value_stays_put_once_read():
    dut = DNAReader(sys_clk_freq=16e6, port_clk_freq=1e6, with_primitive=False)
    state = _run(dut, cycles=2 * dut.half_period * (3 * NBITS))
    assert state["id"] == DNA


def test_at_100_mhz_the_port_clock_is_about_1_mhz():
    assert DNAReader(sys_clk_freq=100e6, with_primitive=False).half_period == 50
