"""The iCE40UP5K's 128 KB of SPRAM as one 32-bit Wishbone slave, with the bank chosen by the address within it.

LiteX's own Up5kSPRAM (litex/soc/cores/ram/lattice_ice40.py) compares one address bit too many for its bank select
(`bus.adr[14:14 + log2(banks) + 1] == bank`), and the slave sees the CPU's whole word address, not the address within
its region. So in a SoC that puts the SPRAM anywhere the next bit up is 1 (the TT FPGA's SoC has it at 0x00020000:
word address bit 15 set), no bank ever matches: no write is enabled and every read is 0. The TT FPGA's SPRAM test
found that on the board (fpgas.online-test-designs #343, 16 Oct 2026: "FAIL at 0x00020004 read 0x00000000 expected
0x40008001"). Here the bank is the address bits just above the 16K words of one SPRAM, and nothing above them: the
region must be aligned to its size (check_aligned), as LiteX allocates it.

As LiteX's (32 bits wide): each 32-bit word is two SB_SPRAM256KA (16K x 16 bits) side by side, bytes 0 and 1 in the
first and 2 and 3 in the second, each byte with its two nibbles of the chip's write mask (MASKWREN); a 128 KB SPRAM
is two such banks of 64 KB.
"""

from litex.gen import LiteXModule
from litex.soc.interconnect import wishbone
from migen import *

kB = 1024
WORDS = 16 * 1024  # of one SB_SPRAM256KA: 16K x 16 bits
BANK = 64 * kB  # two of them side by side, as 32-bit words


def sb_spram256ka(module, address, datain, maskwren, wren, dataout):
    """Add one of the iCE40's SPRAM primitives to `module`. (A test passes a simulation model in its place.)"""
    module.specials += Instance(
        "SB_SPRAM256KA",
        i_CLOCK=ClockSignal("sys"),
        i_STANDBY=0b0,
        i_SLEEP=0b0,
        i_POWEROFF=0b1,
        i_ADDRESS=address,
        i_DATAIN=datain,
        i_MASKWREN=maskwren,
        i_WREN=wren,
        i_CHIPSELECT=0b1,
        o_DATAOUT=dataout,
    )


def bank_bits(size):
    """How many word-address bits above one SPRAM's 14 choose the bank: log2 of the number of 64 KB banks."""
    banks = size // BANK
    assert size in (BANK, 2 * BANK), f"the UP5K has 64 KB or 128 KB of SPRAM as 32-bit words, not {size}"
    return banks.bit_length() - 1


def check_aligned(origin, size):
    """The bank is read from the address's own bits, so the region must start on a multiple of its size."""
    if origin % size:
        raise ValueError(
            f"the SPRAM region at 0x{origin:08x} is not aligned to its size 0x{size:x}: its banks would "
            "be chosen wrongly"
        )


class Up5kSPRAM(LiteXModule):
    def __init__(self, size=128 * kB, primitive=sb_spram256ka):
        self.bus = wishbone.Interface(data_width=32, address_width=32, addressing="word")
        nbits = bank_bits(size)

        # # #

        for bank in range(2**nbits):
            selected = Signal(name=f"bank{bank}")
            if nbits:
                self.comb += selected.eq(self.bus.adr[14 : 14 + nbits] == bank)
            else:
                self.comb += selected.eq(1)
            for half in range(2):
                datain = Signal(16)
                dataout = Signal(16)
                maskwren = Signal(4)
                wren = Signal()
                self.comb += [
                    datain.eq(self.bus.dat_w[16 * half : 16 * (half + 1)]),
                    wren.eq(selected & self.bus.we & self.bus.stb & self.bus.cyc),
                    If(selected, self.bus.dat_r[16 * half : 16 * (half + 1)].eq(dataout)),
                    # MASKWREN is per nibble: two nibbles for each byte select
                    maskwren.eq(Cat(*(self.bus.sel[2 * half + b] for b in (0, 0, 1, 1)))),
                ]
                primitive(self, self.bus.adr[:14], datain, maskwren, wren, dataout)

        self.sync += self.bus.ack.eq(self.bus.stb & self.bus.cyc & ~self.bus.ack)
