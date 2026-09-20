"""UARTBone for a link that starts slow: long command timeout, dynamic baud rate, and a break that resets it all.

Three things LiteX's stock `uart_name="uartbone"` does not give:

- `timeout_s`: Stream2Wishbone abandons a command 100 ms after its first byte,
  which at 1200 baud is shorter than a two-word read. Its timer is sized as
  `100e-3 * clk_freq`, and that is the only use it makes of `clk_freq`, so a
  scaled `clk_freq` buys a longer timeout. The PHY still gets the real clock.
- The PHY's `tuning_word` CSR, so the host can raise the baud rate.
- A UART break (RX low for `break_s`) resets the PHY **and the bridge**, and
  puts the baud rate back to `reset_baud`. Resetting only the baud rate is not
  enough: a write header left behind by a session that died would swallow the
  next session's first bytes as its data and perform the write (found in
  review, 2026-09-20). The baud rate needs its own assignment because the
  `tuning_word` storage is not inside the bridge: LiteX's CSR bank adopts every
  CSRStorage as its own submodule, so a ResetInserter around the bridge never
  sees it (found by this module's simulation test).
"""

from litex.gen import *
from litex.soc.cores.uart import RS232PHY, UARTBone
from migen import *

from designs._shared.uart_break import UARTBreakDetector


def tuning_word(baudrate, clk_freq):
    """The RS232PHY phase-accumulator increment for `baudrate` (same formula as litex.soc.cores.uart)."""
    return int((baudrate / clk_freq) * 2**32)


class BreakResetUARTBone(LiteXModule):
    def __init__(self, pads, clk_freq, reset_baud, timeout_s=1.0, break_s=0.05, address_width=32):
        self.bridge = ResetInserter()(
            UARTBone(
                phy=RS232PHY(pads, clk_freq, reset_baud, with_dynamic_baudrate=True),
                clk_freq=clk_freq * timeout_s / 100e-3,
                address_width=address_width,
            )
        )
        self.wishbone = self.bridge.wishbone
        self.detector = UARTBreakDetector(clk_freq, break_s=break_s)
        self.comb += [
            self.detector.rx.eq(pads.rx),
            self.bridge.reset.eq(self.detector.detected),
        ]
        self.sync += If(
            self.detector.detected,
            self.bridge.phy._tuning_word.storage.eq(tuning_word(reset_baud, clk_freq)),
        )
