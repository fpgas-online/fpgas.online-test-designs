"""Unit tests for the UARTBone link helper (designs/acorn-pcie/host/uartbone_link.py).

A fake serial port stands in for the FPGA: it implements the UARTBone wire
protocol over a small memory, only answers at the baud rate the "FPGA" is
currently listening at, moves to a new rate when the tuning-word CSR is
written, and on a break of at least 50 ms returns to 1200 and forgets any
half-received command. Time is faked: `settle()` advances a clock, and the fake
measures how long the break condition was held against that clock.

The failure modes have their own switches (`silent`, `ignore_tuning_write`,
`stale_bytes`) because a fake that always answers tests none of the recovery code.
"""

import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "host" / "uartbone_link.py"
_spec = importlib.util.spec_from_file_location("uartbone_link", _PATH)
link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(link)

IDENT = "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-20"


class FakeFPGA:
    def __init__(self, baud=link.RESET_BAUD, ident=IDENT):
        self.baud = baud
        self.mem = {link.IDENT_ADDR + 4 * i: ord(c) for i, c in enumerate(ident + "\0")}
        self.now = 0.0
        self.breaks = []  # how long each break was held
        self.opened_at = []
        self.silent = False  # nothing is listening
        self.ignore_tuning_write = False  # the baud-rate change is lost
        self.stale_bytes = 0  # a dead session left the bridge waiting for this many more bytes

    def open(self, baud):
        self.opened_at.append(baud)
        return FakePort(self, baud)

    def settle(self, seconds):
        self.now += seconds


class FakePort:
    def __init__(self, fpga, baud):
        self.fpga, self.baud = fpga, baud
        self.rx = bytearray()
        self.timeout = None
        self._break_since = None

    @property
    def break_condition(self):
        return self._break_since is not None

    @break_condition.setter
    def break_condition(self, on):
        if on:
            self._break_since = self.fpga.now
            return
        held, self._break_since = self.fpga.now - self._break_since, None
        self.fpga.breaks.append(held)
        if held >= 0.05:  # UART_BREAK_S in the gateware
            self.fpga.baud = link.RESET_BAUD
            self.fpga.stale_bytes = 0

    def write(self, data):
        data = bytes(data)
        if self.fpga.silent or self.baud != self.fpga.baud:
            return len(data)  # wrong rate: the FPGA sees noise and says nothing
        if self.fpga.stale_bytes:
            eaten = min(self.fpga.stale_bytes, len(data))
            self.fpga.stale_bytes -= eaten
            self.fpga.mem["corrupted"] = True
            data = data[eaten:]
            if len(data) < 6:
                return eaten + len(data)
        cmd, length, addr = data[0], data[1], int.from_bytes(data[2:6], "big") * 4
        if cmd == link.CMD_READ:
            for i in range(length):
                self.rx += self.fpga.mem.get(addr + 4 * i, 0).to_bytes(4, "big")
        elif cmd == link.CMD_WRITE:
            for i in range(length):
                value = int.from_bytes(data[6 + 4 * i : 10 + 4 * i], "big")
                self.fpga.mem[addr + 4 * i] = value
                if addr + 4 * i == link.TUNING_WORD_ADDR and not self.fpga.ignore_tuning_write:
                    self.fpga.baud = link.baud_of(value)
        return len(data)

    def read(self, n):
        out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        return out  # b"" when there is nothing: that is how a pyserial timeout looks

    def reset_input_buffer(self):
        self.rx.clear()

    def close(self):
        pass


def _link(fpga):
    return link.UARTBoneLink(fpga.open, settle=fpga.settle)


def test_tuning_word_matches_the_gateware_constant():
    # UART_FAST_TUNING_WORD in the generated soc.h for a 100 MHz sys clock.
    assert link.tuning_word(921600) == 39582418
    assert link.baud_of(link.tuning_word(921600)) == 921600
    assert link.baud_of(link.tuning_word(1200)) == 1200


def test_read_request_is_the_litex_wire_format():
    assert link.read_request(0xF0001800, 1) == bytes([0x02, 0x01, 0x3C, 0x00, 0x06, 0x00])


def test_write_request_is_the_litex_wire_format():
    expected = bytes([0x01, 0x01, 0x3C, 0x00, 0x06, 0x00]) + (39582418).to_bytes(4, "big")
    assert link.write_request(0xF0001800, [39582418]) == expected


def test_reads_are_split_to_fit_the_pi_uart_fifo():
    fpga = FakeFPGA()
    lk = _link(fpga)
    lk.connect(fast=False)
    sent = []
    real_write = lk.port.write
    lk.port.write = lambda d: (sent.append(bytes(d)), real_write(d))[1]
    words = lk.read(link.IDENT_ADDR, 10)
    assert "".join(map(chr, words)) == IDENT[:10]
    assert [req[1] for req in sent] == [4, 4, 2], "no reply may exceed 16 bytes (4 words)"


def test_connect_from_reset_ends_at_the_fast_rate():
    fpga = FakeFPGA(baud=link.RESET_BAUD)
    lk = _link(fpga)
    assert lk.connect() == link.FAST_BAUD
    assert fpga.baud == link.FAST_BAUD
    assert lk.ident() == IDENT


def test_connect_finds_an_fpga_left_at_the_fast_rate():
    fpga = FakeFPGA(baud=link.FAST_BAUD)
    lk = _link(fpga)
    assert lk.connect() == link.FAST_BAUD
    assert lk.ident() == IDENT


def test_connect_slow_only():
    fpga = FakeFPGA(baud=link.FAST_BAUD)
    lk = _link(fpga)
    assert lk.connect(fast=False) == link.RESET_BAUD
    assert fpga.baud == link.RESET_BAUD


def test_the_break_is_held_long_enough_for_the_detector_and_no_longer_than_it_says():
    fpga = FakeFPGA()
    _link(fpga).connect(fast=False)
    assert fpga.breaks == [pytest.approx(link.BREAK_S)]
    assert link.BREAK_S >= 2 * 0.05


def test_connect_works_first_time_after_a_session_died_mid_write():
    fpga = FakeFPGA(baud=link.FAST_BAUD)
    fpga.stale_bytes = 4  # a write header arrived, its data never did
    lk = _link(fpga)
    assert lk.connect() == link.FAST_BAUD
    assert "corrupted" not in fpga.mem, "the probe was swallowed as the dead session's write data"


def test_connect_raises_when_nothing_answers():
    fpga = FakeFPGA()
    fpga.silent = True
    with pytest.raises(link.LinkError, match=r"no fpgas\.online SoC answered"):
        _link(fpga).connect()


def test_connect_raises_on_the_wrong_design():
    fpga = FakeFPGA(ident="something else entirely")
    with pytest.raises(link.LinkError, match=r"no fpgas\.online SoC answered"):
        _link(fpga).connect()


def test_a_lost_baud_rate_change_is_reported_and_leaves_the_link_usable():
    fpga = FakeFPGA()
    fpga.ignore_tuning_write = True
    lk = _link(fpga)
    with pytest.raises(link.LinkError, match="not at 921600"):
        lk.connect()
    assert len(fpga.breaks) == 2, "the failed fast probe must end with a break"
    assert lk.baud == link.RESET_BAUD and fpga.baud == link.RESET_BAUD
    assert lk.ident() == IDENT, "still talking at the reset rate"


def test_a_read_that_times_out_resets_the_link_before_raising():
    fpga = FakeFPGA()
    lk = _link(fpga)
    lk.connect()
    fpga.silent = True
    with pytest.raises(link.LinkError, match="timeout"):
        lk.read(link.IDENT_ADDR)
    fpga.silent = False
    assert len(fpga.breaks) == 2
    assert fpga.baud == link.RESET_BAUD and lk.baud == link.RESET_BAUD
    assert lk.connect() == link.FAST_BAUD
