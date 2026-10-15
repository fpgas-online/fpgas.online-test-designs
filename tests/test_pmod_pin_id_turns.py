"""Simulation of the pin-ID senders that take turns on a shared wire (designs/pmod-pin-id, #142)."""

import importlib.util
import pathlib
import sys

import pytest

pytest.importorskip("migen")
pytest.importorskip("litex")

from migen import Signal, run_simulation

GATEWARE = pathlib.Path(__file__).parents[1] / "designs/pmod-pin-id/gateware"
sys.path.insert(0, str(GATEWARE))  # pmod_pin_id_tt.py imports its sibling pmod_pin_id by name


def _load(name):
    spec = importlib.util.spec_from_file_location(name, GATEWARE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pin_id = _load("pmod_pin_id")
tt = _load("pmod_pin_id_tt")

DIV = 4  # clock cycles to a bit


def _bytes(levels):
    """The 8N1 bytes in a list of per-bit line levels (idle high)."""
    out, i = [], 0
    while i + 10 <= len(levels):
        if levels[i] == 0:
            out.append(sum(levels[i + 1 + k] << k for k in range(8)))
            assert levels[i + 9] == 1, "stop bit"
            i += 10
        else:
            i += 1
    return bytes(out)


def _run(label, run_pattern, bits):
    """Drive `run` from `run_pattern` (bit number -> level); per bit: what the pad shows (None: high impedance)."""
    pin, run = Signal(), Signal()
    dut = pin_id.UARTTxIdentifier(pin, label, DIV * 1200, baud=1200, run=run)
    pad = []

    def bench():
        for bit in range(bits):
            yield run.eq(run_pattern(bit))
            for cycle in range(DIV):
                yield
                if cycle == DIV // 2:
                    pad.append((yield pin) if (yield dut.sending) else None)

    run_simulation(dut, bench())
    return pad


def test_without_run_a_sender_sends_all_the_time_as_before():
    pin = Signal()
    dut = pin_id.UARTTxIdentifier(pin, "13\r\n", DIV * 1200, baud=1200)
    levels = []

    def bench():
        for _ in range(140):
            for cycle in range(DIV):
                yield
                if cycle == DIV // 2:
                    levels.append((yield pin))

    run_simulation(dut, bench())
    assert b"13\r\n13\r\n13\r\n" in _bytes(levels)


def test_a_sender_starts_labels_only_in_its_turn_and_always_finishes_the_one_it_started():
    pad = _run("19\r\n", lambda bit: 100 <= bit < 190, 400)
    assert all(level is None for level in pad[:100])  # not its turn yet: high impedance
    driven = [i for i, level in enumerate(pad) if level is not None]
    assert 100 <= driven[0] <= 102  # it starts when its turn does
    assert driven[-1] >= 190  # the label under way when the turn ended was finished
    assert driven[-1] < 190 + 45  # and nothing was started after it (a label is 4 characters, 44 bits)
    heard = _bytes([1 if level is None else level for level in pad])  # the Pi's pull-up holds a released wire high
    assert heard and heard == b"19\r\n" * (len(heard) // 4)  # whole labels only, however the turn ended
    assert all(level is None for level in pad[driven[-1] + 1 :])  # released for the other sender


def test_the_two_groups_never_have_their_turn_together_and_the_gap_outlasts_a_label():
    dut = tt.Turns(ticks_per_ms=2, turn_ms=8, gap_ms=3)
    seen = []

    def bench():
        for _ in range(2 * 2 * (8 + 3) * 3):
            yield
            seen.append(((yield dut.run[0]), (yield dut.run[1])))

    run_simulation(dut, bench())
    assert (1, 1) not in seen and {(1, 0), (0, 1), (0, 0)} == set(seen)
    text = "".join("A" if a else "B" if b else "-" for a, b in seen)
    assert "A" * 16 + "-" * 6 + "B" * 16 + "-" * 6 + "A" * 16 in text  # 8 ms, 3 ms, 8 ms, 3 ms at 2 cycles a ms
    # in the real design: a label is at most 4 characters of 11 bit times at 1200 baud, and the gap is longer
    assert tt.GAP_S > 4 * 11 / tt.BAUD_RATE and tt.CYCLE_S == 1.0


def test_only_the_six_wires_that_share_a_pi_gpio_take_turns_and_the_two_ends_of_a_wire_are_in_different_groups():
    platform = tt.Platform(toolchain="icestorm")
    pins = tt.build_pin_list(platform)
    assert len(pins) == 24
    turns = {resource: tt.turn_of(resource) for resource, _label in pins}
    shared = {f"tt_input:{i}": 0 for i in (1, 2, 3)} | {f"tt_bidir:{i}": 1 for i in (1, 2, 3)}
    assert {r: g for r, g in turns.items() if g is not None} == shared
    labels = dict(pins)
    # the pin numbers the host expects on GPIO10, 9 and 11 (identify_pmod_pins.BOARDS["tt"])
    assert [labels[f"tt_input:{i}"].strip() for i in (1, 2, 3)] == ["19", "18", "21"]
    assert [labels[f"tt_bidir:{i}"].strip() for i in (1, 2, 3)] == ["4", "3", "6"]
