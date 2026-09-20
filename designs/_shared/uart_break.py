"""UART break detector: one pulse when RX has been held low for `break_s` seconds.

Used by the Acorn PCIe SoC to drop its UARTBone link back to the 1200-baud
reset rate. A break is the one signal a host can send without knowing what
rate the far end is currently listening at, and the longest legitimate low
on the line (a zero byte at 1200 baud) is 7.5 ms, so 50 ms is unambiguous.
"""

from litex.gen import LiteXModule
from migen import If, Signal
from migen.genlib.cdc import MultiReg


class UARTBreakDetector(LiteXModule):
    """`detected` pulses for one cycle, once per break, when `rx` has been low for `break_s`.

    It re-arms only after `rx` goes high again, so a line that is stuck low
    (unplugged cable, a Pi pin left driving low) produces a single pulse and
    then nothing.
    """

    def __init__(self, clk_freq, break_s=0.05):
        self.rx = Signal(reset=1)
        self.detected = Signal()

        # # #

        cycles = int(clk_freq * break_s)
        rx = Signal(reset=1)
        self.specials += MultiReg(self.rx, rx, reset=1)

        count = Signal(max=cycles + 1)
        fired = Signal()
        self.sync += [
            self.detected.eq(0),
            If(
                rx,
                count.eq(0),
                fired.eq(0),
            )
            .Elif(
                count == cycles,
                If(~fired, self.detected.eq(1)),
                fired.eq(1),
            )
            .Else(
                count.eq(count + 1),
            ),
        ]
