"""Reusable UART TX pin identifier module.

Each instance drives a single FPGA output pin, continuously transmitting
a label string (e.g. "JA01\\r\\n") at a specified baud rate using 8N1 framing.

Usage:
    pin = platform.request("some_pin")
    self.submodules += UARTTxIdentifier(pin, "JA01\\r\\n", sys_clk_freq, baud=1200)

This module is board-agnostic. Board-specific scripts instantiate one per pin.

Two pins that end on the same wire (the Digilent Pmod HAT joins JA pins 2-4 and JB pins 2-4 on three Raspberry
Pi GPIOs) cannot both send all the time: they would collide. For those, `run` says when the instance may start
a label, and `sending` is high from a label's first start bit to its last stop bit: the board script drives the
pin only while `sending` (high impedance otherwise), and gives the two instances their turns. A label once
started is always finished, so the listener only ever sees whole labels.
"""

from migen import *


class UARTTxIdentifier(Module):
    """Continuously transmit a label string on a single pin at a fixed baud rate.

    Parameters
    ----------
    pin : Signal(1)
        Output pin to drive.
    label : str
        ASCII string to transmit repeatedly (should include "\\r\\n" terminator).
    sys_clk_freq : int
        System clock frequency in Hz.
    baud : int
        Baud rate (default 1200).
    run : Signal(1) or None
        When given: a new label is started only while it is high. None: always (the default).

    Attributes
    ----------
    sending : Signal(1)
        High from the first start bit of a label to the last stop bit of that label.
    """
    def __init__(self, pin, label, sys_clk_freq, baud=1200, run=None):
        assert len(label) > 0, "Label must be non-empty"
        self.sending = Signal()

        divisor = int(sys_clk_freq // baud)
        label_bytes = [ord(c) for c in label]
        num_chars = len(label_bytes)

        # Baud rate timer
        baud_counter = Signal(max=divisor + 1)
        baud_tick = Signal()
        self.sync += [
            If(baud_counter == divisor - 1,
                baud_counter.eq(0),
                baud_tick.eq(1),
            ).Else(
                baud_counter.eq(baud_counter + 1),
                baud_tick.eq(0),
            )
        ]

        # Character index into the label
        char_idx = Signal(max=num_chars)

        # TX shift register: start bit + 8 data bits + stop bit = 10 bits
        # Shift out LSB first. Idle high.
        shift_reg = Signal(10, reset=0x3FF)  # idle = all ones
        bit_count = Signal(max=11)  # 0 = idle, 1-10 = transmitting

        # Drive the pin from the LSB of the shift register when active,
        # otherwise idle high.
        self.comb += [
            If(bit_count != 0,
                pin.eq(shift_reg[0]),
            ).Else(
                pin.eq(1),
            )
        ]

        # Build a ROM of the label bytes
        cases = {i: shift_reg.eq(Cat(C(0, 1), C(b, 8), C(1, 1)))
                 for i, b in enumerate(label_bytes)}

        # A label is started only when allowed; its later characters always follow.
        may_load = Signal()
        self.comb += [
            may_load.eq((char_idx != 0) | (1 if run is None else run)),
            self.sending.eq((bit_count != 0) | (char_idx != 0)),
        ]

        self.sync += [
            If(baud_tick,
                If(bit_count == 0,
                    If(may_load,
                        # Load next character frame: [start=0, data[7:0], stop=1]
                        Case(char_idx, cases),
                        bit_count.eq(10),
                        If(char_idx == num_chars - 1,
                            char_idx.eq(0),
                        ).Else(
                            char_idx.eq(char_idx + 1),
                        )
                    )
                ).Else(
                    # Shift out next bit
                    shift_reg.eq(Cat(shift_reg[1:10], C(1, 1))),
                    bit_count.eq(bit_count - 1),
                )
            )
        ]
