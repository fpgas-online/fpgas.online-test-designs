"""Unit tests for the UARTBone link helper (designs/acorn-pcie/host/uartbone_link.py).

A fake serial port stands in for the FPGA: it implements the UARTBone wire
protocol over a small memory, only answers at the baud rate the "FPGA" is
currently listening at, moves to a new rate when the tuning-word CSR is
written, and returns to 1200 on a break.
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
        self.breaks = 0
        self.opened_at = []

    def open(self, baud):
        self.opened_at.append(baud)
        return FakePort(self, baud)


class FakePort:
    def __init__(self, fpga, baud):
        self.fpga, self.baud = fpga, baud
        self.rx = bytearray()
        self.timeout = None

    def write(self, data):
        if self.baud != self.fpga.baud:
            return len(data)  # wrong rate: the FPGA sees noise and says nothing
        data = bytes(data)
        cmd, length, addr = data[0], data[1], int.from_bytes(data[2:6], "big") * 4
        if cmd == link.CMD_READ:
            for i in range(length):
                self.rx += self.fpga.mem.get(addr + 4 * i, 0).to_bytes(4, "big")
        elif cmd == link.CMD_WRITE:
            for i in range(length):
                value = int.from_bytes(data[6 + 4 * i : 10 + 4 * i], "big")
                self.fpga.mem[addr + 4 * i] = value
                if addr + 4 * i == link.TUNING_WORD_ADDR:
                    self.fpga.baud = link.baud_of(value)
        return len(data)

    def read(self, n):
        out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        return out

    def reset_input_buffer(self):
        self.rx.clear()

    def send_break(self, duration):
        assert duration >= 0.05, "the FPGA needs 50 ms of low to see a break"
        self.fpga.breaks += 1
        self.fpga.baud = link.RESET_BAUD

    def close(self):
        pass


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
    lk = link.UARTBoneLink(fpga.open)
    lk.connect(fast=False)
    sent = []
    real_write = lk.port.write
    lk.port.write = lambda d: (sent.append(bytes(d)), real_write(d))[1]
    words = lk.read(link.IDENT_ADDR, 10)
    assert "".join(map(chr, words)) == IDENT[:10]
    assert [req[1] for req in sent] == [4, 4, 2], "no reply may exceed 16 bytes (4 words)"


def test_connect_from_reset_ends_at_the_fast_rate():
    fpga = FakeFPGA(baud=link.RESET_BAUD)
    lk = link.UARTBoneLink(fpga.open)
    assert lk.connect() == link.FAST_BAUD
    assert fpga.baud == link.FAST_BAUD
    assert lk.ident() == IDENT


def test_connect_finds_an_fpga_left_at_the_fast_rate():
    fpga = FakeFPGA(baud=link.FAST_BAUD)
    lk = link.UARTBoneLink(fpga.open)
    assert lk.connect() == link.FAST_BAUD
    assert lk.ident() == IDENT


def test_connect_slow_only():
    fpga = FakeFPGA(baud=link.FAST_BAUD)
    lk = link.UARTBoneLink(fpga.open)
    assert lk.connect(fast=False) == link.RESET_BAUD
    assert fpga.baud == link.RESET_BAUD


def test_connect_raises_when_nothing_answers():
    fpga = FakeFPGA(ident="something else entirely")
    lk = link.UARTBoneLink(fpga.open, settle=lambda s: None)
    with pytest.raises(link.LinkError):
        lk.connect()
