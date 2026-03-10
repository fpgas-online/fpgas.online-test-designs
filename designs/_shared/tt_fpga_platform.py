"""LiteX platform definition for the TinyTapeout FPGA Demo Board.

The TT FPGA board consists of:
  - FPGA Breakout Board: iCE40UP5K + SPI flash
  - TinyTapeout Demo PCB: RP2040 controller, PMOD headers, 7-seg display

Pin mappings follow the fabricfoxv2 PCF (current default for TT ETR
demoboard v3+), sourced from TinyTapeout/tt-support-tools.

The RP2040 provides a clock signal to the FPGA and can act as a
USB-to-UART bridge for serial communication.

UART default: RX = ui_in[3] (pin 21), TX = uo_out[4] (pin 45).
SPI flash: dedicated iCE40 pins 14/15/16/17.
"""

from litex.build.generic_platform import *
from litex.build.lattice import LatticeiCE40Platform
from litex.build.lattice.programmer import IceStormProgrammer

# IOs (fabricfoxv2 pinout) -------------------------------------------------------------------------

_io = [
    # Clk / Rst
    ("clk_rp2040", 0, Pins("20"), IOStandard("LVCMOS33")),
    ("rst_n",      0, Pins("37"), IOStandard("LVCMOS33")),

    # RGB LED (active-low, accent LED on demo PCB)
    ("rgb_led", 0,
        Subsignal("r", Pins("39")),
        Subsignal("g", Pins("40")),
        Subsignal("b", Pins("41")),
        IOStandard("LVCMOS33"),
    ),

    # Serial (UART via TT I/O pins, bridged by RP2040)
    ("serial", 0,
        Subsignal("rx", Pins("21")),   # ui_in[3]
        Subsignal("tx", Pins("45")),   # uo_out[4]
        IOStandard("LVCMOS33"),
    ),

    # TinyTapeout user inputs (directly from DIP switches or RP2040)
    ("ui_in", 0, Pins("13 19 18 21 23 25 26 27"), IOStandard("LVCMOS33")),

    # TinyTapeout user outputs (directly to 7-seg display or RP2040)
    ("uo_out", 0, Pins("38 42 43 44 45 46 47 48"), IOStandard("LVCMOS33")),

    # TinyTapeout bidirectional I/O
    ("uio", 0, Pins("2 4 3 6 9 10 11 12"), IOStandard("LVCMOS33")),

    # SPI Flash (dedicated iCE40UP5K SPI pins, on FPGA breakout board)
    ("spiflash", 0,
        Subsignal("cs_n", Pins("16"), IOStandard("LVCMOS33")),
        Subsignal("clk",  Pins("15"), IOStandard("LVCMOS33")),
        Subsignal("miso", Pins("17"), IOStandard("LVCMOS33")),
        Subsignal("mosi", Pins("14"), IOStandard("LVCMOS33")),
    ),

    ("spiflash4x", 0,
        Subsignal("cs_n", Pins("16"), IOStandard("LVCMOS33")),
        Subsignal("clk",  Pins("15"), IOStandard("LVCMOS33")),
        Subsignal("dq",   Pins("14 17"), IOStandard("LVCMOS33")),
    ),
]

# Connectors ---------------------------------------------------------------------------------------

_connectors = [
    # PMOD headers on the TT demo PCB, exposed as TT signal groups.
    ("tt_input",  "13 19 18 21 23 25 26 27"),   # ui_in[0:7]
    ("tt_output", "38 42 43 44 45 46 47 48"),   # uo_out[0:7]
    ("tt_bidir",  "2 4 3 6 9 10 11 12"),        # uio[0:7]
]

# Platform -----------------------------------------------------------------------------------------

class Platform(LatticeiCE40Platform):
    default_clk_name   = "clk_rp2040"
    default_clk_period = 1e9 / 50e6  # 50 MHz from RP2040

    def __init__(self, toolchain="icestorm"):
        LatticeiCE40Platform.__init__(
            self, "ice40-up5k-sg48", _io, _connectors, toolchain=toolchain,
        )

    def create_programmer(self):
        return IceStormProgrammer()

    def do_finalize(self, fragment):
        LatticeiCE40Platform.do_finalize(self, fragment)
        self.add_period_constraint(
            self.lookup_request("clk_rp2040", loose=True), 1e9 / 50e6,
        )
