#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Fomu EVT (Lattice iCE40UP5K).

Builds a SoC with CPU + BIOS + UART + SPI Flash access. The BIOS prints
the SPI flash identification on boot. Additionally, custom firmware can
be loaded to explicitly read the JEDEC ID via command 0x9F.

Fomu EVT SPI Flash: AT25SF161 (16 Mbit), Quad SPI.
  CS_N=pin 16, CLK=pin 15, MOSI=pin 14, MISO=pin 17, WP=pin 18, HOLD=pin 19.
Clock: 48 MHz external (pin 44), 12 MHz system clock via PLL.
UART: Serial RX=pin 21, TX=pin 13 (LVCMOS33).

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_fomu.py --build

The bitstream is written to: designs/spi-flash-id/build/fomu/gateware/fomu_spiflash_test.bit
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.gen import *

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.cores.clock import iCE40PLL
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_fomu_evt import Platform

from designs._shared.build_helpers import default_build_dir

kB = 1024

# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    """Clock Reset Generator for Fomu EVT.

    Takes the 48 MHz external clock and derives a 12 MHz system clock
    via the iCE40 PLL. Includes power-on reset synchronisation.
    """
    def __init__(self, platform, sys_clk_freq):
        assert sys_clk_freq == 12e6
        self.rst    = Signal()
        self.cd_sys = ClockDomain()
        self.cd_por = ClockDomain()

        # # #

        # Clk/Rst
        clk48 = platform.request("clk48")
        platform.add_period_constraint(clk48, 1e9/48e6)

        # Power On Reset
        por_count = Signal(16, reset=2**16-1)
        por_done  = Signal()
        self.comb += self.cd_por.clk.eq(ClockSignal())
        self.comb += por_done.eq(por_count == 0)
        self.sync.por += If(~por_done, por_count.eq(por_count - 1))

        # PLL: 48 MHz -> 12 MHz
        self.pll = pll = iCE40PLL()
        pll.clko_freq_range = (12e6, 275e9)  # Widen range for iCE40.
        pll.register_clkin(clk48, 48e6)
        pll.create_clkout(self.cd_sys, 12e6, with_reset=False)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~por_done | ~pll.locked)


# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = Platform()

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        # Use hardware UART on serial pins (not USB ACM).
        kwargs["uart_name"] = "serial"
        # Disable Integrated ROM/SRAM — iCE40 UP5K uses dedicated SPRAM.
        kwargs["integrated_sram_size"] = 0
        kwargs["integrated_rom_size"]  = 0
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # 128KB SPRAM (used as 64kB SRAM / 64kB main RAM) -----------------------------------------
        self.spram = Up5kSPRAM(size=128*kB)
        self.bus.add_slave("psram", self.spram.bus, SoCRegion(size=128*kB))
        self.bus.add_region("sram", SoCRegion(
            origin = self.bus.regions["psram"].origin + 0*kB,
            size   = 64*kB,
            linker = True,
        ))
        if not self.integrated_main_ram_size:
            self.bus.add_region("main_ram", SoCRegion(
                origin = self.bus.regions["psram"].origin + 64*kB,
                size   = 64*kB,
                linker = True,
            ))

        # SPI Flash (LiteSPI) ---------------------------------------------------------------------
        from litespi.modules import AT25SF161
        from litespi.opcodes import SpiNorFlashOpCodes as Codes

        self.add_spi_flash(mode="4x", module=AT25SF161(Codes.READ_1_1_1), with_master=False)


def main():
    parser = argparse.ArgumentParser(description="SPI Flash ID Test SoC for Fomu EVT")
    parser.add_argument("--build",         action="store_true", help="Build bitstream.")
    parser.add_argument("--sys-clk-freq",  default=12e6, type=float, help="System clock frequency.")
    parser.add_argument("--output-dir",    default=None, help="Override build output directory.")
    args = parser.parse_args()

    sys_clk_freq = int(args.sys_clk_freq)

    soc = BaseSoC(
        sys_clk_freq = sys_clk_freq,
        ident        = "fpgas-online SPI Flash Test SoC -- Fomu EVT",
        uart_baudrate = 115200,
    )

    output_dir = args.output_dir or default_build_dir(__file__, "fomu")
    builder = Builder(soc, output_dir=output_dir)
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
