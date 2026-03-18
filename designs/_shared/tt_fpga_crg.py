"""Clock Reset Generator for TinyTapeout FPGA Demo Board (iCE40UP5K).

Derives a 12 MHz system clock from the 50 MHz RP2040-provided clock
via the iCE40 PLL.  Includes power-on reset synchronisation.
"""

from litex.gen import *
from litex.soc.cores.clock import iCE40PLL
from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer


class TtFpgaCRG(LiteXModule):
    """Minimal CRG for TT FPGA: 50 MHz input → 12 MHz sys clock."""

    def __init__(self, platform, sys_clk_freq):
        assert sys_clk_freq == 12e6
        self.rst    = Signal()
        self.cd_sys = ClockDomain()
        self.cd_por = ClockDomain()

        # Clk/Rst
        clk50 = platform.request("clk_rp2040")
        platform.add_period_constraint(clk50, 1e9 / 50e6)

        # Power On Reset
        por_count = Signal(16, reset=2**16 - 1)
        por_done  = Signal()
        self.comb += self.cd_por.clk.eq(ClockSignal())
        self.comb += por_done.eq(por_count == 0)
        self.sync.por += If(~por_done, por_count.eq(por_count - 1))

        # PLL: 50 MHz → 12 MHz
        self.pll = pll = iCE40PLL()
        pll.clko_freq_range = (12e6, 275e9)  # Widen range for iCE40.
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, 12e6, with_reset=False)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~por_done | ~pll.locked)
