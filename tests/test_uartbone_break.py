"""Simulation: a UART break must leave the bridge at the reset baud rate AND with no half-received command."""

from litex.soc.interconnect import wishbone
from migen import Module, Record, run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.uartbone_break import BreakResetUARTBone, tuning_word

CLK = 48_000
BAUD = 1200
BIT = CLK // BAUD  # 40 cycles
BREAK_S = 0.05
TIMEOUT_S = 1.0


class _DUT(Module):
    def __init__(self):
        self.pads = Record([("rx", 1), ("tx", 1)])
        self.pads.rx.reset = 1
        self.submodules.link = BreakResetUARTBone(
            self.pads, CLK, BAUD, timeout_s=TIMEOUT_S, break_s=BREAK_S, address_width=32
        )
        bus = wishbone.Interface(data_width=32, adr_width=32)
        self.submodules.sram = wishbone.SRAM(64, init=[0x11111111 * (i + 1) & 0xFFFFFFFF for i in range(16)], bus=bus)
        self.comb += self.link.wishbone.connect(bus)


def _send(dut, data, bit=BIT):
    for byte in data:
        for level in [0] + [(byte >> i) & 1 for i in range(8)] + [1]:
            yield dut.pads.rx.eq(level)
            for _ in range(bit):
                yield


def _idle(dut, seconds, level=1):
    yield dut.pads.rx.eq(level)
    for _ in range(int(CLK * seconds)):
        yield


def _receive(dut, nbytes, within_s, bit=BIT):
    """Sample TX like a UART would; returns the bytes seen before the deadline."""
    out, waited, deadline = [], 0, int(CLK * within_s)
    while len(out) < nbytes and waited < deadline:
        if (yield dut.pads.tx) == 0:
            for _ in range(bit + bit // 2):
                yield
            value = 0
            for i in range(8):
                value |= (yield dut.pads.tx) << i
                for _ in range(bit):
                    yield
            out.append(value)
            waited += 10 * bit
        else:
            yield
            waited += 1
    return out


def _read_cmd(word_addr, words=1):
    return [0x02, words, *word_addr.to_bytes(4, "big")]


def _mem(dut, index):
    return (yield dut.sram.mem[index])


def test_a_read_works_at_the_reset_baud_rate():
    dut, got = _DUT(), {}

    def bench():
        yield from _idle(dut, 0.01)
        yield from _send(dut, _read_cmd(2))
        got["reply"] = yield from _receive(dut, 4, within_s=0.2)

    run_simulation(dut, bench())
    assert got["reply"] == [0x33, 0x33, 0x33, 0x33]


def test_a_break_forgets_a_half_received_write():
    """The bug this module exists for: stale write header + break + probe must not perform a write."""
    dut, got = _DUT(), {}

    def bench():
        yield from _idle(dut, 0.01)
        yield from _send(dut, [0x01, 0x01, 0x00, 0x00, 0x00, 0x05])  # write 1 word to word 5 ... and then die
        yield from _idle(dut, 0.2)
        yield from _idle(dut, 0.1, level=0)  # break
        yield from _idle(dut, 0.05)
        yield from _send(dut, _read_cmd(2))  # the next session's first probe
        got["reply"] = yield from _receive(dut, 4, within_s=0.2)
        got["word5"] = yield from _mem(dut, 5)

    run_simulation(dut, bench())
    assert got["word5"] == 0x66666666, "the probe's bytes were taken as the stale write's data"
    assert got["reply"] == [0x33, 0x33, 0x33, 0x33]


def test_a_break_returns_the_baud_rate_to_its_reset_value():
    dut, got = _DUT(), {}
    storage = dut.link.bridge.phy._tuning_word.storage

    def bench():
        yield from _idle(dut, 0.01)
        yield storage.eq(tuning_word(9600, CLK))  # stands in for the CSR bank's write
        yield
        got["raised"] = yield storage
        yield from _idle(dut, 0.1, level=0)
        yield from _idle(dut, 0.01)
        got["after"] = yield storage
        yield from _send(dut, _read_cmd(3))
        got["reply"] = yield from _receive(dut, 4, within_s=0.2)

    run_simulation(dut, bench())
    assert got["raised"] == tuning_word(9600, CLK)
    assert got["after"] == tuning_word(BAUD, CLK)
    assert got["reply"] == [0x44, 0x44, 0x44, 0x44]


def test_without_a_break_a_stale_command_times_out_after_timeout_s():
    dut, got = _DUT(), {}

    def bench():
        yield from _idle(dut, 0.01)
        yield from _send(dut, [0x01, 0x01, 0x00, 0x00, 0x00, 0x05])
        yield from _idle(dut, TIMEOUT_S + 0.1)
        yield from _send(dut, _read_cmd(2))
        got["reply"] = yield from _receive(dut, 4, within_s=0.2)
        got["word5"] = yield from _mem(dut, 5)

    run_simulation(dut, bench())
    assert got["word5"] == 0x66666666
    assert got["reply"] == [0x33, 0x33, 0x33, 0x33]
