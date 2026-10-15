"""The UP5K SPRAM slave (designs/_shared/up5k_spram.py) in simulation, with a model of SB_SPRAM256KA, at the address
the TT FPGA's SoC gives it: 0x00020000, word address 0x8000, where LiteX's own Up5kSPRAM chose no bank at all, so
nothing was written and every word read 0 (the SPRAM test on the board, #343, 16 Oct 2026)."""

import pytest
from migen import Memory, Replicate, run_simulation

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.up5k_spram import BANK, WORDS, Up5kSPRAM, bank_bits, check_aligned

BASE = 0x0002_0000  # the TT FPGA SoC's psram region (its build's csr.csv)


def spram_model(module, address, datain, maskwren, wren, dataout):
    """SB_SPRAM256KA as the iCE40 technology library describes it: 16K x 16 bits, written on the clock where WREN
    and that nibble's MASKWREN are high, DATAOUT registered from the address of the clock before."""
    mem = Memory(16, WORDS)
    port = mem.get_port(write_capable=True, we_granularity=4)
    module.specials += mem, port
    module.comb += [
        port.adr.eq(address),
        port.dat_w.eq(datain),
        port.we.eq(Replicate(wren, 4) & maskwren),
        dataout.eq(port.dat_r),
    ]


def _access(dut, byte_addr, data=None, sel=0b1111):
    """One Wishbone cycle from the CPU's side: the whole word address, as LiteX's interconnect passes it."""
    bus = dut.bus
    yield bus.adr.eq(byte_addr >> 2)
    yield bus.we.eq(data is not None)
    yield bus.dat_w.eq(data or 0)
    yield bus.sel.eq(sel)
    yield bus.cyc.eq(1)
    yield bus.stb.eq(1)
    yield
    while not (yield bus.ack):
        yield
    value = yield bus.dat_r
    yield bus.cyc.eq(0)
    yield bus.stb.eq(0)
    yield
    return value


def _run(steps):
    """Run `steps` ((byte address, data or None, sel)) on a 128 KB SPRAM at BASE; the values read."""
    dut = Up5kSPRAM(size=2 * BANK, primitive=spram_model)
    read = []

    def bench():
        for addr, data, sel in steps:
            value = yield from _access(dut, addr, data, sel)
            if data is None:
                read.append(value)

    run_simulation(dut, bench())
    return read


def test_both_banks_hold_their_own_words_at_the_soc_address():
    words = {
        BASE + 4: 0x40008001,
        BASE + BANK - 4: 0x0BADF00D,
        BASE + BANK: 0x12345678,
        BASE + 2 * BANK - 4: 0xCAFEF00D,
    }
    steps = [(a, v, 0b1111) for a, v in words.items()] + [(a, None, 0b1111) for a in words]
    assert _run(steps) == list(words.values())


def test_each_byte_lane_writes_only_its_byte_in_both_banks():
    cases = [(BASE + bank * BANK + 0x40, lane) for bank in range(2) for lane in range(4)]
    steps = [s for a, lane in cases for s in ((a, 0xFFFFFFFF, 0b1111), (a, 0, 1 << lane), (a, None, 0b1111))]
    assert _run(steps) == [0xFFFFFFFF & ~(0xFF << 8 * lane) for _, lane in cases]


def test_the_bank_is_the_one_address_bit_above_a_spram():
    # 14 bits address the 16K words of one SPRAM; a 128 KB region has one more bit, its bank, and no other
    assert bank_bits(2 * BANK) == 1 and bank_bits(BANK) == 0
    with pytest.raises(AssertionError):
        bank_bits(3 * BANK)


def test_a_region_not_aligned_to_its_size_is_refused():
    check_aligned(BASE, 2 * BANK)
    check_aligned(0x1000_0000, 2 * BANK)
    with pytest.raises(ValueError, match="not aligned"):
        check_aligned(BASE + BANK, 2 * BANK)
