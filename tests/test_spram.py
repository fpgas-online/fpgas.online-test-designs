"""The TT FPGA's SPRAM test (#343). Its firmware (designs/_shared/ice40_firmware.py, generate_spram_firmware) is
run on a small RV32I interpreter against a model of the SoC's UART and SPRAM: a good SPRAM passes, and each kind of
fault it is there to find fails it, at the right word: a data bit stuck at 1 or at 0, the two 64 KB banks on one
address (LiteX's bank select, byte address bit 16), a byte store that writes the whole word, and each byte lane's
write mask stuck off or on. Its host script (designs/spram/host/test_spram.py) is run against a fake
serial port that answers as the firmware does."""

import importlib.util
import pathlib
import sys

import pytest

from designs._shared.ice40_firmware import SPRAM_BANK, generate_spram_firmware, spram_pattern

UART = 0xF000_1800
SPRAM = 0x1000_0000
IDENT = "fpgas-online SPRAM Test SoC -- TT FPGA"
STEPS = 4_000_000


class Machine:
    """An RV32I hart with the firmware in ROM at 0, the UART's CSRs at UART and `size` bytes of SPRAM at SPRAM."""

    def __init__(self, size, rx=b"T", stuck=None, alias_bit=None, no_byte_mask=False, lane_mask=None):
        self.size = size
        self.rom = b"".join(w.to_bytes(4, "little") for w in generate_spram_firmware(UART, SPRAM, size, IDENT))
        self.ram = bytearray(size)
        self.rx = list(rx)
        self.out = bytearray()
        self.x = [0] * 32
        self.pc = 0
        self.stuck = stuck  # (byte offset of the word, bit, value): that bit reads as value
        self.alias_bit = alias_bit  # this address bit does not reach the SPRAM: two addresses, one word
        self.no_byte_mask = no_byte_mask  # a byte store writes the whole word (its other bytes as 0)
        # (lane, "off" or "on"): that byte lane's write mask is stuck. Off: a byte store to it writes nothing. On:
        # a byte store to any lane writes that lane too (with the stored byte, which the CPU puts on every lane)
        self.lane_mask = lane_mask

    def _cell(self, addr):
        off = addr - SPRAM
        if self.alias_bit is not None:
            off &= ~(1 << self.alias_bit)
        return off

    def load(self, addr, n):
        if addr < len(self.rom):
            return int.from_bytes(self.rom[addr : addr + n], "little")
        if SPRAM <= addr < SPRAM + self.size:
            off = self._cell(addr)
            word = int.from_bytes(self.ram[off & ~3 : (off & ~3) + 4], "little")
            if self.stuck and self.stuck[0] == off & ~3:
                _, bit, value = self.stuck
                word = word | (1 << bit) if value else word & ~(1 << bit)
            return (word >> (8 * (off & 3))) & ((1 << (8 * n)) - 1)
        if addr == UART + 0:  # RXTX
            return self.rx[0] if self.rx else 0
        if addr == UART + 4:  # TXFULL
            return 0
        if addr == UART + 8:  # RXEMPTY
            return 0 if self.rx else 1
        raise AssertionError(f"load from 0x{addr:08x} at pc 0x{self.pc:x}")

    def store(self, addr, value, n):
        if SPRAM <= addr < SPRAM + self.size:
            off = self._cell(addr)
            if n == 1 and self.no_byte_mask:
                self.ram[off & ~3 : (off & ~3) + 4] = (value << (8 * (off & 3))).to_bytes(4, "little")
            elif n == 1 and self.lane_mask:
                lane, how = self.lane_mask
                if not (how == "off" and off & 3 == lane):
                    self.ram[off] = value & 0xFF
                if how == "on":
                    self.ram[(off & ~3) + lane] = value & 0xFF
            else:
                self.ram[off : off + n] = (value & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
        elif addr == UART + 0:
            self.out.append(value & 0xFF)
        elif addr == UART + 16:  # EV_PENDING: bit 1 pops the RX FIFO
            if value & 2 and self.rx:
                self.rx.pop(0)
        else:
            raise AssertionError(f"store to 0x{addr:08x} at pc 0x{self.pc:x}")

    def step(self):
        ins = self.load(self.pc, 4)
        op, rd, f3 = ins & 0x7F, (ins >> 7) & 0x1F, (ins >> 12) & 7
        rs1, rs2, f7 = self.x[(ins >> 15) & 0x1F], self.x[(ins >> 20) & 0x1F], ins >> 25
        imm_i = (ins >> 20) - (1 << 12 if ins >> 31 else 0)
        nxt = self.pc + 4
        val = None
        if op == 0b0110111:  # lui
            val = ins & 0xFFFFF000
        elif op == 0b0010111:  # auipc
            val = self.pc + (ins & 0xFFFFF000)
        elif op == 0b1101111:  # jal
            imm = (
                ((ins >> 31) << 20)
                | (((ins >> 12) & 0xFF) << 12)
                | (((ins >> 20) & 1) << 11)
                | (((ins >> 21) & 0x3FF) << 1)
            )
            val, nxt = nxt, self.pc + imm - (1 << 21 if imm >> 20 else 0)
        elif op == 0b1100111:  # jalr
            val, nxt = nxt, (rs1 + imm_i) & ~1
        elif op == 0b1100011:  # beq, bne
            imm = (
                ((ins >> 31) << 12) | (((ins >> 7) & 1) << 11) | (((ins >> 25) & 0x3F) << 5) | (((ins >> 8) & 0xF) << 1)
            )
            imm -= 1 << 13 if imm >> 12 else 0
            assert f3 in (0, 1), f"branch funct3 {f3}"
            if (rs1 == rs2) == (f3 == 0):
                nxt = self.pc + imm
        elif op == 0b0000011:  # lw, lbu
            assert f3 in (0b010, 0b100), f"load funct3 {f3}"
            val = self.load((rs1 + imm_i) & 0xFFFFFFFF, 4 if f3 == 0b010 else 1)
        elif op == 0b0100011:  # sw, sb
            imm = ((ins >> 25) << 5) | ((ins >> 7) & 0x1F)
            imm -= 1 << 12 if imm >> 11 else 0
            assert f3 in (0b010, 0b000), f"store funct3 {f3}"
            self.store((rs1 + imm) & 0xFFFFFFFF, rs2, 4 if f3 == 0b010 else 1)
        elif op == 0b0010011:  # addi, xori, ori, andi, slli, srli
            sh = (ins >> 20) & 0x1F
            val = {0: rs1 + imm_i, 4: rs1 ^ imm_i, 6: rs1 | imm_i, 7: rs1 & imm_i, 1: rs1 << sh, 5: rs1 >> sh}[f3]
            assert f3 != 5 or f7 == 0, "srai"
        elif op == 0b0110011:  # add, sub, sll, xor, or, and
            val = {(0, 0): rs1 + rs2, (0, 0x20): rs1 - rs2, (1, 0): rs1 << (rs2 & 0x1F), (4, 0): rs1 ^ rs2,
                   (6, 0): rs1 | rs2, (7, 0): rs1 & rs2}[(f3, f7)]  # fmt: skip
        else:
            raise AssertionError(f"opcode 0b{op:07b} at pc 0x{self.pc:x}")
        if val is not None and rd:
            self.x[rd] = val & 0xFFFFFFFF
        self.pc = nxt & 0xFFFFFFFF

    def run_until(self, text, steps=STEPS):
        """Run until the UART has said `text` and then a line end; returns all it said."""
        for _ in range(steps):
            self.step()
            said = self.out.decode("ascii")
            if text in said and said.endswith("\r\n") and said.rfind(text) < said.rfind("\r\n"):
                return said
        raise AssertionError(f"not said within {steps} steps: {text!r}; said {self.out.decode('ascii')!r}")


def _verdict(said):
    return [line for line in said.split("\r\n") if line.startswith("SPRAM_TEST:")]


def test_the_pattern_holds_each_words_address_and_every_bit_both_ways():
    words = [spram_pattern(off) for off in range(0, 128 * 1024, 4)]
    assert len(set(words)) == len(words)  # every word its own value
    for bit in range(32):
        ones = sum((w >> bit) & 1 for w in words)
        assert 0 < ones < len(words), bit  # each bit 0 somewhere and 1 somewhere
    assert all(spram_pattern(off, inverted=True) == w ^ 0xFFFFFFFF for off, w in zip(range(0, 1 << 17, 4), words))


def test_a_good_spram_passes_and_the_firmware_waits_to_be_asked():
    m = Machine(128 * 1024, rx=b"")
    for _ in range(1_000_000):  # banner, ident, ready; then it waits, testing nothing
        m.step()
    said = m.out.decode("ascii")
    assert said == f"\r\nLiteX custom firmware\r\n{IDENT}\r\nSPRAM_READY\r\n" and not any(m.ram)
    m.rx = list(b"T")
    assert _verdict(m.run_until("SPRAM_TEST:")) == ["SPRAM_TEST: PASS"]
    # the whole SPRAM was written: the last pass left the inverse pattern but for the byte-lane words
    lanes = {SPRAM_BANK * k for k in range(2)}
    for off in range(0, 128 * 1024, 4096):
        if off not in lanes:
            assert int.from_bytes(m.ram[off : off + 4], "little") == spram_pattern(off, inverted=True)


def test_each_byte_asks_for_another_whole_test():
    m = Machine(SPRAM_BANK, rx=b"T")
    m.run_until("SPRAM_TEST: PASS")
    m.out.clear()
    m.rx = list(b"x")
    assert _verdict(m.run_until("SPRAM_TEST:")) == ["SPRAM_TEST: PASS"]


@pytest.mark.parametrize("value", [1, 0])
def test_a_stuck_data_bit_fails_at_its_word(value):
    off = SPRAM_BANK + 0x124  # in the second bank
    bit = next(b for b in range(32) if (spram_pattern(off) >> b & 1) != value)  # the first pattern finds it
    m = Machine(2 * SPRAM_BANK, stuck=(off, bit, value))
    want = spram_pattern(off)
    read = want | 1 << bit if value else want & ~(1 << bit)
    assert _verdict(m.run_until("SPRAM_TEST:")) == [
        f"SPRAM_TEST: FAIL at 0x{SPRAM + off:08X} read 0x{read:08X} expected 0x{want:08X}"]  # fmt: skip


def test_a_stuck_bit_the_first_pattern_already_sets_is_found_by_the_inverse():
    off = 0x40
    bit = next(b for b in range(32) if spram_pattern(off) >> b & 1)
    m = Machine(SPRAM_BANK, stuck=(off, bit, 1))
    want = spram_pattern(off, inverted=True)
    assert _verdict(m.run_until("SPRAM_TEST:")) == [
        f"SPRAM_TEST: FAIL at 0x{SPRAM + off:08X} read 0x{want | 1 << bit:08X} expected 0x{want:08X}"]  # fmt: skip


def test_the_two_banks_answering_one_address_fail_at_the_first_word():
    m = Machine(2 * SPRAM_BANK, alias_bit=16)  # LiteX's bank select lost: the second bank's writes land in the first
    assert _verdict(m.run_until("SPRAM_TEST:")) == [
        f"SPRAM_TEST: FAIL at 0x{SPRAM:08X} read 0x{spram_pattern(SPRAM_BANK):08X} "
        f"expected 0x{spram_pattern(0):08X}"]  # fmt: skip


def test_a_byte_store_that_writes_the_whole_word_fails_on_the_byte_lanes():
    m = Machine(SPRAM_BANK, no_byte_mask=True)
    assert _verdict(m.run_until("SPRAM_TEST:")) == [
        f"SPRAM_TEST: FAIL at 0x{SPRAM:08X} read 0x00000000 expected 0xFFFFFF00"]  # fmt: skip


@pytest.mark.parametrize("lane", range(4))
@pytest.mark.parametrize("how", ["off", "on"])
def test_each_lanes_write_mask_stuck_off_or_on_fails(lane, how):
    """The masks are the chip's: a stuck one is found at the first word the lane check writes."""
    m = Machine(SPRAM_BANK, lane_mask=(lane, how))
    full = 0xFFFFFFFF
    if how == "off":  # the store to that lane does not land
        tried, read = lane, full
    else:  # a store to another lane lands in that one too
        tried = 0 if lane else 1
        read = full & ~(0xFF << 8 * tried) & ~(0xFF << 8 * lane)
    want = full & ~(0xFF << 8 * tried)
    assert _verdict(m.run_until("SPRAM_TEST:")) == [
        f"SPRAM_TEST: FAIL at 0x{SPRAM:08X} read 0x{read:08X} expected 0x{want:08X}"]  # fmt: skip


@pytest.mark.parametrize("size", [0, SPRAM_BANK // 2, SPRAM_BANK + 4])
def test_a_size_that_is_not_whole_banks_is_refused(size):
    with pytest.raises(AssertionError):
        generate_spram_firmware(UART, SPRAM, size, IDENT)


# -- the host script -------------------------------------------------------------------------------------------

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "designs" / "spram" / "host" / "test_spram.py"
_spec = importlib.util.spec_from_file_location("test_spram_host", _SCRIPT)
host = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(host)


class FakePort:
    """A serial port to the design: each byte written is answered with the lines in `answers`, in turn."""

    def __init__(self, answers):
        self.answers, self.pending, self.written = list(answers), [], b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def reset_input_buffer(self):
        self.pending = []

    def write(self, data):
        self.written += data
        if self.answers:
            self.pending += [line.encode() + b"\r\n" for line in self.answers.pop(0)]

    def readline(self):
        return self.pending.pop(0) if self.pending else b""


def _run(monkeypatch, capsys, answers):
    port = FakePort(answers)
    monkeypatch.setattr(host.serial, "Serial", lambda *a, **kw: port)
    monkeypatch.setattr(host, "ASK_EVERY_S", 0.05)
    monkeypatch.setattr(sys, "argv", ["test_spram.py", "--port", "/dev/pts/3"])
    rc = host.main()
    return rc, capsys.readouterr().out.splitlines(), port


def test_the_host_script_passes_on_the_designs_pass(monkeypatch, capsys):
    rc, out, port = _run(monkeypatch, capsys, [["SPRAM_TEST: PASS"]])
    assert rc == 0 and port.written == b"T"
    assert out[-1] == "SPRAM: all 128 KB written and read back twice, each byte lane's write mask checked"


def test_the_host_script_fails_with_the_designs_words(monkeypatch, capsys):
    fail = "FAIL at 0x10008000 read 0x00000000 expected 0x00004000"
    rc, out, _ = _run(monkeypatch, capsys, [["LiteX custom firmware", f"SPRAM_TEST: {fail}"]])
    assert rc == 1 and out[-1] == f"SPRAM: {fail}"


def test_the_host_script_asks_again_while_the_design_starts_and_says_when_it_never_answers(monkeypatch, capsys):
    rc, out, port = _run(monkeypatch, capsys, [[], ["SPRAM_READY"], ["SPRAM_TEST: PASS"]])
    assert rc == 0 and port.written == b"TTT"
    rc, out, port = _run(monkeypatch, capsys, [])
    assert rc == 2 and port.written == b"T" * host.ASKS
    assert out[-1].startswith("SPRAM: no answer from the SPRAM test design in") and "nothing was tested" in out[-1]


def test_a_port_that_cannot_be_opened_is_nothing_tested_not_a_fail(monkeypatch, capsys):
    def refuse(*a, **kw):
        raise host.serial.SerialException("[Errno 2] could not open port /dev/pts/3")

    monkeypatch.setattr(host.serial, "Serial", refuse)
    monkeypatch.setattr(sys, "argv", ["test_spram.py", "--port", "/dev/pts/3"])
    assert host.main() == 2
    assert capsys.readouterr().out.splitlines()[-1].startswith("SPRAM: could not open /dev/pts/3: ")
