"""7-series device DNA, read slowly and sampled mid-bit, with a manual mode for the host.

LiteX's `DNA` core clocks `DNA_PORT` from a divided flop at sys_clk/2 and captures
DOUT on the same edge that shifts it. On the first board it ran on (pi20's
XC7A100T, 100 MHz sys clock, 2026-09-20) it returned 0x01fd7f283fffc21a where JTAG
`FUSE_DNA` reads 0x0028e5c45e304854: no shift, reversal or inversion of one gives
the other. This reader runs the port at about 1 MHz and samples DOUT a full half
period after the edge that produced it, so routing delay cannot matter.

`manual` hands the three port inputs to the host so the primitive can be
bit-banged over either bridge. That is the ground truth to compare the automatic
value against, and costs three flops.

CSR layout keeps LiteX's name for the value (`dna_id`, 57 bits, MSB = first bit out).
"""

from litex.gen import *
from litex.soc.interconnect.csr import CSRField, CSRStatus, CSRStorage
from migen import *

NBITS = 57


class DNAReader(LiteXModule):
    def __init__(self, sys_clk_freq, port_clk_freq=1e6, with_primitive=True):
        self._id = CSRStatus(NBITS, description="Device DNA as shifted out of DNA_PORT, first bit in the MSB.")
        self._manual = CSRStorage(
            fields=[
                CSRField("enable", size=1, description="1: the fields below drive DNA_PORT instead of the reader."),
                CSRField("clk", size=1),
                CSRField("read", size=1),
                CSRField("shift", size=1),
            ]
        )
        self._dout = CSRStatus(1, description="DNA_PORT.DOUT right now.")

        # The port's pins, exposed so a simulation can stand in for the primitive.
        self.clk = Signal()
        self.read = Signal()
        self.shift = Signal()
        self.dout = Signal()
        self.done = Signal()

        # # #

        half = max(2, int(sys_clk_freq / port_clk_freq / 2))
        self.half_period = half
        tick = Signal(max=half)
        clk = Signal()
        bits = Signal(max=NBITS + 1)
        value = Signal(NBITS)
        loaded = Signal()

        last = tick == half - 1
        self.sync += [
            If(
                self.done,
                tick.eq(0),
            ).Else(
                tick.eq(Mux(last, 0, tick + 1)),
                If(
                    last,
                    clk.eq(~clk),
                    # Falling edge coming up: DOUT has been stable for a whole half period.
                    If(
                        clk,
                        If(
                            ~loaded,
                            loaded.eq(1),  # that was the READ clock; DOUT now holds the first bit
                        ),
                        value.eq(Cat(self.dout, value)),
                        bits.eq(bits + 1),
                        If(bits == NBITS - 1, self.done.eq(1)),
                    ),
                ),
            ),
        ]
        man = self._manual.fields
        self.comb += [
            self.clk.eq(Mux(man.enable, man.clk, clk)),
            self.read.eq(Mux(man.enable, man.read, ~loaded)),
            self.shift.eq(Mux(man.enable, man.shift, loaded)),
            self._id.status.eq(value),
            self._dout.status.eq(self.dout),
        ]
        if with_primitive:
            self.specials += Instance(
                "DNA_PORT",
                i_CLK=self.clk,
                i_READ=self.read,
                i_SHIFT=self.shift,
                i_DIN=0,
                o_DOUT=self.dout,
            )

    def add_timing_constraints(self, platform, sys_clk_freq, sys_clk):
        platform.add_period_constraint(self.clk, 2 * self.half_period * 1e9 / sys_clk_freq)
        platform.add_false_path_constraints(self.clk, sys_clk)
