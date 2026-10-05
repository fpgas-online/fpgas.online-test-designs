"""Simulation: the Acorn's J2/K2 serial/GPIO switch is the serial link until a host says otherwise, and goes back."""

import pytest

pytest.importorskip("litex")
pytest.importorskip("migen")

from litex.soc.interconnect import csr_bus
from migen import Module, run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.acorn_p2 import SWITCH_BITS, P2SerialSwitch

CLK = 10_000  # 10 sys cycles per ms
J2, K2 = SWITCH_BITS["J2"], SWITCH_BITS["K2"]


class _DUT(Module):
    """The switch behind a real CSR bank, as in the SoC: write_from_dev only works there."""

    def __init__(self):
        self.submodules.sw = P2SerialSwitch(None, CLK)
        self.submodules.banks = csr_bus.CSRBankArray(self, lambda name, memory: 0, data_width=32)
        self.bus = csr_bus.Interface(data_width=32)
        self.submodules.interconnect = csr_bus.Interconnect(self.bus, self.banks.get_buses())
        ((_, csrs, _, bank),) = self.banks.banks
        assert len(bank.simple_csrs) == len(csrs), "every register is one 32-bit word"
        self.regs = {c.name: i for i, c in enumerate(csrs)}

    def write(self, reg, value):
        yield from self.bus.write(self.regs[reg], value)
        yield  # the storage updates one cycle after the bus write

    def read(self, reg):
        yield self.bus.adr.eq(self.regs[reg])
        yield
        yield  # the bank registers dat_r
        return (yield self.bus.dat_r)


def _cycles(n):
    for _ in range(n):
        yield


def _pins(sw):
    return {
        "j2_oe": (yield sw.rx_pin.oe),
        "j2_o": (yield sw.rx_pin.o),
        "k2_oe": (yield sw.tx_pin.oe),
        "k2_o": (yield sw.tx_pin.o),
        "uart_rx": (yield sw.uart_pads.rx),
        "link_reset": (yield sw.link_reset),
    }


def test_bits_follow_p2_pin_order():
    assert (J2, K2) == (0, 1)


def test_out_of_reset_the_pins_are_the_serial_link():
    dut, seen = _DUT(), []

    def bench():
        sw = dut.sw
        yield from _cycles(2)
        for tx, rx in ((0, 1), (1, 0), (1, 1)):
            yield sw.uart_pads.tx.eq(tx)
            yield sw.rx_pin.i.eq(rx)
            yield
            seen.append(((yield from _pins(sw)), (yield from dut.read("in"))))

    run_simulation(dut, bench())
    for (pins, status), (tx, rx) in zip(seen, ((0, 1), (1, 0), (1, 1)), strict=True):
        assert pins == {"j2_oe": 0, "j2_o": 0, "k2_oe": 1, "k2_o": tx, "uart_rx": rx, "link_reset": 0}
        assert status & (1 << J2) == rx << J2


def test_gpio_mode_gives_the_host_both_pins_and_holds_the_link_in_reset():
    dut, got = _DUT(), {}

    def bench():
        sw = dut.sw
        yield from dut.write("timeout", 0)
        yield from dut.write("mode", 1)
        yield sw.rx_pin.i.eq(0)  # the host drives J2 low: the UART must not see it
        yield
        got["inputs"] = yield from _pins(sw)
        yield from dut.write("oe", (1 << J2) | (1 << K2))
        yield from dut.write("out", 1 << K2)
        yield sw.uart_pads.tx.eq(0)  # the UART's TX no longer reaches K2
        yield sw.tx_pin.i.eq(1)
        yield
        got["outputs"] = yield from _pins(sw)
        got["in"] = yield from dut.read("in")

    run_simulation(dut, bench())
    assert got["inputs"] == {"j2_oe": 0, "j2_o": 0, "k2_oe": 0, "k2_o": 0, "uart_rx": 1, "link_reset": 1}
    assert got["outputs"] == {"j2_oe": 1, "j2_o": 0, "k2_oe": 1, "k2_o": 1, "uart_rx": 1, "link_reset": 1}
    assert got["in"] == (1 << K2)


def test_gpio_mode_ends_by_itself_after_the_timeout():
    dut, modes = _DUT(), []

    def bench():
        sw = dut.sw
        yield from dut.write("timeout", 3)  # 3 ms = 30 cycles
        yield from dut.write("mode", 1)
        for _ in range(60):
            modes.append((yield sw._mode.storage))  # one sample per cycle; a bus read takes three
            yield
        modes.append((yield sw.link_reset))

    run_simulation(dut, bench())
    assert modes[:25] == [1] * 25, "reverted early"
    assert modes[40:] == [0] * 21, "never reverted (or link still held in reset)"


def test_rewriting_mode_restarts_the_timeout():
    dut, modes = _DUT(), []

    def bench():
        sw = dut.sw
        yield from dut.write("timeout", 3)
        yield from dut.write("mode", 1)
        yield from _cycles(20)
        yield from dut.write("mode", 1)
        for _ in range(25):
            modes.append((yield sw._mode.storage))
            yield

    run_simulation(dut, bench())
    assert modes == [1] * 25


def test_timeout_zero_keeps_gpio_mode_until_the_host_switches_back():
    dut, modes = _DUT(), []

    def bench():
        sw = dut.sw
        yield from dut.write("timeout", 0)
        yield from dut.write("mode", 1)
        yield from _cycles(200)
        modes.append((yield from dut.read("mode")))
        yield from dut.write("mode", 0)
        yield
        modes.append((yield from dut.read("mode")))
        modes.append((yield sw.link_reset))

    run_simulation(dut, bench())
    assert modes == [1, 0, 0]


def test_registers_and_the_default_timeout():
    dut, got = _DUT(), {}

    def bench():
        got["timeout"] = yield from dut.read("timeout")
        got["mode"] = yield from dut.read("mode")

    run_simulation(dut, bench())
    assert list(dut.regs) == ["mode", "oe", "in", "out", "timeout"]
    assert got == {"timeout": 5000, "mode": 0}
