"""Simulation tests for the PCIe DMA <-> LiteDRAM bridge (designs/_shared/pcie_dram_bridge.py).

The bridge sits at the far end of LitePCIe's DMA streams. Two behavioural models stand in for what is either
side of it: a host that pushes/pulls 64-bit words with random stalls, and a LiteDRAM native port pair backed by
a dict, which accepts commands, write data and read data with random stalls and in order, as the controller does.
"""

import random

import pytest

pytest.importorskip("litedram")

from litedram.common import LiteDRAMNativePort
from migen import Memory, Signal, run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.pcie_dram_bridge import MODE_FROM_DRAM, MODE_TO_DRAM, PCIeDRAMBridge

AW, DW = 24, 64


def _dut():
    return PCIeDRAMBridge(LiteDRAMNativePort("write", AW, DW), LiteDRAMNativePort("read", AW, DW))


class Bench:
    def __init__(self, dut, seed, stall=0.4):
        self.dut, self.rand, self.stall = dut, random.Random(seed), stall
        self.mem, self.pulled, self.stop = {}, [], False
        self.write_order, self.read_order = [], []

    def _go(self):
        return self.rand.random() >= self.stall

    def dram_port(self, port):
        """cmd -> (wdata | rdata), each with its own random stalls, data in command order."""
        writes, reads = [], []
        cmd_ready = wdata_ready = rdata_valid = 0
        while not self.stop:
            if cmd_ready and (yield port.cmd.valid):
                addr = yield port.cmd.addr
                if (yield port.cmd.we):
                    writes.append(addr)
                else:
                    reads.append(addr)
                    self.read_order.append(addr)
            if wdata_ready and (yield port.wdata.valid):
                addr = writes.pop(0)
                assert (yield port.wdata.we) == 0xFF
                self.mem[addr] = yield port.wdata.data
                self.write_order.append(addr)
            if rdata_valid and (yield port.rdata.ready):
                reads.pop(0)
            cmd_ready, wdata_ready = int(self._go()), int(bool(writes) and self._go())
            rdata_valid = int(bool(reads) and self._go())
            yield port.cmd.ready.eq(cmd_ready)
            yield port.wdata.ready.eq(wdata_ready)
            yield port.rdata.valid.eq(rdata_valid)
            if rdata_valid:
                yield port.rdata.data.eq(self.mem.get(reads[0], 0xDEAD_0000_0000_0000 | reads[0]))
            yield

    def host_push(self, words):
        """The host's DMA reader: words arriving from Pi memory."""
        words, valid = list(words), 0
        while not self.stop:
            if valid and (yield self.dut.sink.ready):
                words.pop(0)
            valid = int(bool(words) and self._go())
            yield self.dut.sink.valid.eq(valid)
            if valid:
                yield self.dut.sink.data.eq(words[0])
            yield
        self.unsent = words

    def host_pull(self):
        """The host's DMA writer: words leaving for Pi memory."""
        ready = 0
        while not self.stop:
            if ready and (yield self.dut.source.valid):
                self.pulled.append((yield self.dut.source.data))
            ready = int(self._go())
            yield self.dut.source.ready.eq(ready)
            yield

    def transfer(self, mode, base, length, timeout=20000):
        dut = self.dut
        yield dut._base.storage.eq(base)
        yield dut._length.storage.eq(length)
        yield dut._mode.storage.eq(mode)
        yield dut._start.re.eq(1)
        yield
        yield dut._start.re.eq(0)
        yield
        for _ in range(timeout):
            if (yield dut._done.status):
                return
            yield
        raise AssertionError(f"no done after {timeout} cycles (count={(yield dut._count.status)})")

    def run(self, main, push=()):
        def wrapped():
            yield from main
            for _ in range(40):  # anything the bridge does after done would show here
                yield
            self.stop = True

        # migen's simulator lowers every memory port's read side, and falls over on the write-only port (dat_r is
        # None) in the DMA writer's FIFO. A read signal nobody looks at is enough to get past it.
        fragment = self.dut.get_fragment()
        for memory in (m for m in fragment.specials if isinstance(m, Memory)):
            for port in memory.ports:
                if port.dat_r is None:
                    port.dat_r = Signal(memory.width)
        generators = [
            wrapped(),
            self.dram_port(self.dut.write_port),
            self.dram_port(self.dut.read_port),
            self.host_push(push),
            self.host_pull(),
        ]
        run_simulation(fragment, generators)


def _words(n, seed=1):
    r = random.Random(seed)
    return [r.getrandbits(64) for _ in range(n)]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_to_dram_writes_exactly_length_words_from_base_in_order(seed):
    bench, words = Bench(_dut(), seed), _words(40)
    bench.run(bench.transfer(MODE_TO_DRAM, base=0x1000, length=32), push=words)
    assert bench.mem == {0x1000 + i: w for i, w in enumerate(words[:32])}
    assert bench.write_order == list(range(0x1000, 0x1020))
    assert bench.unsent == words[32:]  # done means stop: the bridge does not eat the next transfer's data
    assert bench.pulled == []


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_from_dram_sends_exactly_length_words_from_base_in_order(seed):
    bench = Bench(_dut(), seed)
    bench.mem = {0x2000 + i: w for i, w in enumerate(_words(64, seed=9))}
    bench.run(bench.transfer(MODE_FROM_DRAM, base=0x2008, length=24))
    assert bench.pulled == _words(64, seed=9)[8:32]
    assert bench.read_order == list(range(0x2008, 0x2020))  # a request too many would be left over for the next run


def test_two_reads_in_a_row_each_return_only_their_own_block():
    bench = Bench(_dut(), seed=10)
    bench.mem = dict(enumerate(_words(64, seed=11)))

    def main():
        yield from bench.transfer(MODE_FROM_DRAM, base=0, length=5)
        yield from bench.transfer(MODE_FROM_DRAM, base=40, length=5)

    bench.run(main())
    assert bench.pulled == _words(64, seed=11)[0:5] + _words(64, seed=11)[40:45]


def test_done_in_to_dram_mode_means_the_data_has_reached_the_dram_port():
    bench, words = Bench(_dut(), seed=4, stall=0.8), _words(8)
    seen = {}

    def main():
        yield from bench.transfer(MODE_TO_DRAM, base=0, length=8)
        seen["at_done"] = dict(bench.mem)

    bench.run(main(), push=words)
    assert seen["at_done"] == dict(enumerate(words))


def test_round_trip_through_the_same_bridge_and_a_second_run_after_done():
    bench, words = Bench(_dut(), seed=5), _words(16)

    def main():
        yield from bench.transfer(MODE_TO_DRAM, base=0x40, length=16)
        yield from bench.transfer(MODE_FROM_DRAM, base=0x40, length=16)

    bench.run(main(), push=words)
    assert bench.pulled == words


def test_idle_bridge_takes_nothing_and_sends_nothing():
    bench = Bench(_dut(), seed=6)

    def main():
        for _ in range(200):
            yield
        assert (yield bench.dut._done.status) == 0

    bench.run(main(), push=_words(4))
    assert bench.unsent == _words(4)
    assert bench.pulled == [] and bench.mem == {}


def test_zero_length_is_done_at_once_and_moves_nothing():
    bench = Bench(_dut(), seed=7)
    bench.run(bench.transfer(MODE_TO_DRAM, base=0, length=0, timeout=10), push=_words(4))
    assert bench.mem == {} and bench.unsent == _words(4)


def test_count_reports_progress():
    bench = Bench(_dut(), seed=8)
    seen = {}

    def main():
        yield from bench.transfer(MODE_TO_DRAM, base=0, length=12)
        seen["count"] = yield bench.dut._count.status

    bench.run(main(), push=_words(12))
    assert seen["count"] == 12
