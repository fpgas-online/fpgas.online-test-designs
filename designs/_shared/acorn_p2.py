"""The Acorn's P2 header as the fleet wires it, and the serial/GPIO switch on its two serial pins.

P2 carries four FPGA balls to the host (docs/wiring/acorn/wiring.toml is the source of truth;
tests/test_acorn_p2_pins.py fails if this file or any Acorn design disagrees with it):

| P2 pin | Ball | Use                       | Host pin (Pi 5 HAT and Compute Blade) |
|--------|------|---------------------------|---------------------------------------|
| 2      | J2   | serial RX, FPGA input     | GPIO14 (TXD)                          |
| 3      | K2   | serial TX, FPGA output    | GPIO15 (RXD)                          |
| 4      | J5   | spare GPIO                | GPIO3                                 |
| 5      | H5   | spare GPIO                | GPIO4                                 |

Every Acorn design gets its platform from `fleet_platform()`, so its `serial` resource comes from
here, not from whatever litex-boards happens to define.

`P2SerialSwitch` lets a host borrow J2 and K2 as GPIOs, so every P2 pin can be checked in both
directions. Out of reset the pins are the serial link; see the class for the switching rules.
"""

from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.build.io import SDRTristate
from litex.gen import LiteXModule
from litex.soc.interconnect.csr import CSRField, CSRStatus, CSRStorage
from migen import Cat, If, Mux, Record, Signal

SERIAL_TX = "K2"  # FPGA output -> host GPIO15 (RXD)
SERIAL_RX = "J2"  # FPGA input  <- host GPIO14 (TXD)
SPARE_GPIO = ("J5", "H5")  # bit 0, bit 1 of p2_gpio

# J2 and K2 as bits of P2SerialSwitch's oe/out/in registers, in P2 pin order like p2_gpio.
SWITCH_BITS = {SERIAL_RX: 0, SERIAL_TX: 1}

# How long the pins stay GPIOs after the last write to `mode`, unless the host sets another value.
SWITCH_TIMEOUT_MS = 5000


def serial_io():
    """The fleet's P2 serial pins as a platform extension (the same electrical settings as litex-boards')."""
    return [
        (
            "serial",
            0,
            Subsignal("tx", Pins(SERIAL_TX)),
            Subsignal("rx", Pins(SERIAL_RX)),
            Misc("SLEW=FAST"),
            IOStandard("LVCMOS33"),
        ),
    ]


def spare_gpio_io():
    """J5 and H5 as one 2-bit resource, `p2_gpio`: bit 0 = J5 -> host GPIO3, bit 1 = H5 -> host GPIO4."""
    return [("p2_gpio", 0, Pins(" ".join(SPARE_GPIO)), IOStandard("LVCMOS33"))]


def use_fleet_serial(platform):
    """Replace the platform's `serial` resource with the fleet's P2 wiring."""
    cm = platform.constraint_manager
    cm.available = [r for r in cm.available if r[0] != "serial"]
    platform.add_extension(serial_io())


def fleet_platform(variant, toolchain):
    """litex-boards' Acorn platform with the fleet's P2 serial pins."""
    from litex_boards.platforms import sqrl_acorn

    platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)
    use_fleet_serial(platform)
    return platform


class P2SerialSwitch(LiteXModule):
    """J2/K2 as the serial link (the reset state) or as two host-controlled GPIOs.

    `uart_pads` is what the UART core gets instead of the real pads. CSRs (bit 0 = J2, bit 1 = K2):

    - `mode`: `gpio` 0 = serial link (reset), 1 = GPIOs.
    - `oe`, `out`: as GPIOTristate's; they act only in GPIO mode. With `oe` 0 the pin is an input.
    - `in`: both balls as the FPGA sees them, in either mode (in serial mode: J2 = what the host sends,
      K2 = the FPGA's own TX).
    - `timeout`: milliseconds. In GPIO mode the switch goes back to serial by itself this long after
      the last write to `mode`; 0 = never. A host that switched over the serial link itself, and so
      cut its own link, gets it back without a power cycle.

    While in GPIO mode the UART core sees an idle line and `link_reset` is held high. Wired to the
    UARTBone's reset, that drops any half-received command and returns the link to its reset baud
    rate, so on return the host finds the link exactly as after a break: reopen at the reset rate.
    A host switching back should first return its own pins to serial (GPIO14 driving idle high), or
    the UART sees whatever it was driving as a start bit.
    """

    def __init__(self, pads, sys_clk_freq, timeout_ms=SWITCH_TIMEOUT_MS):
        self.uart_pads = Record([("tx", 1), ("rx", 1)])
        self.link_reset = Signal()

        self._mode = CSRStorage(
            fields=[CSRField("gpio", size=1, description="0: J2/K2 are the serial link. 1: they are GPIOs.")],
            write_from_dev=True,
        )
        self._oe = CSRStorage(2, description="Output enables in GPIO mode: bit 0 = J2, bit 1 = K2.")
        self._in = CSRStatus(2, description="J2 (bit 0) and K2 (bit 1) as the FPGA sees them.")
        self._out = CSRStorage(2, description="Output values in GPIO mode: bit 0 = J2, bit 1 = K2.")
        self._timeout = CSRStorage(
            32, reset=timeout_ms, description="Return to serial this many ms after the last write to mode; 0: never."
        )

        # # #

        gpio = self._mode.fields.gpio
        # Each ball as a tristate: o/oe from here, i from the pad. Without `pads` (simulation) they
        # are left for the caller to drive and watch.
        self.rx_pin = Record([("o", 1), ("oe", 1), ("i", 1)])  # J2
        self.tx_pin = Record([("o", 1), ("oe", 1), ("i", 1)])  # K2
        self.rx_pin.i.reset = 1
        if pads is not None:
            self.specials += [
                SDRTristate(pads.rx, self.rx_pin.o, self.rx_pin.oe, self.rx_pin.i),
                SDRTristate(pads.tx, self.tx_pin.o, self.tx_pin.oe, self.tx_pin.i),
            ]
        self.comb += [
            # J2: the UART's RX (an input), or a GPIO.
            self.rx_pin.o.eq(self._out.storage[0]),
            self.rx_pin.oe.eq(gpio & self._oe.storage[0]),
            self.uart_pads.rx.eq(Mux(gpio, 1, self.rx_pin.i)),
            # K2: the UART's TX (always driven), or a GPIO.
            self.tx_pin.o.eq(Mux(gpio, self._out.storage[1], self.uart_pads.tx)),
            self.tx_pin.oe.eq(~gpio | self._oe.storage[1]),
            self._in.status.eq(Cat(self.rx_pin.i, self.tx_pin.i)),
            self.link_reset.eq(gpio),
        ]

        # Return to serial `timeout` ms after the last write to `mode`.
        tick_cycles = int(sys_clk_freq // 1000)
        prescaler = Signal(max=tick_cycles)
        remaining = Signal(32)
        self.sync += (
            If(
                self._mode.re,
                remaining.eq(self._timeout.storage),
                prescaler.eq(tick_cycles - 1),
            )
            .Elif(
                prescaler == 0,
                prescaler.eq(tick_cycles - 1),
                If(remaining != 0, remaining.eq(remaining - 1)),
            )
            .Else(
                prescaler.eq(prescaler - 1),
            )
        )
        self.comb += [
            self._mode.we.eq(gpio & (self._timeout.storage != 0) & (remaining == 0) & ~self._mode.re),
            self._mode.dat_w.eq(0),
        ]
