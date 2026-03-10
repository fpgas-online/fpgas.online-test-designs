#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Fomu EVT (Lattice iCE40UP5K).

Builds a minimal SoC with CPU + BIOS + UART over GPIO serial pins
(RX=pin 21, TX=pin 13).  The Fomu's upstream LiteX target defaults to
USB ACM; we override to use standard pin-based serial instead.

The iCE40UP5K has no block RAM large enough for a BIOS, so we use the
128 KB UP5K SPRAM (split as 64 KB SRAM + 64 KB main RAM), matching the
upstream kosagi_fomu target's memory layout.

Build command (from repo root):
    uv run python designs/uart/gateware/uart_soc_fomu.py --build

The bitstream is written to:
    designs/uart/build/fomu/gateware/kosagi_fomu_evt.bit
"""

import argparse
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.gen import *

from litex_boards.platforms import kosagi_fomu_evt

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.cores.clock import iCE40PLL
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from designs._shared.build_helpers import default_build_dir

kB = 1024


# CRG (Clock Reset Generator) ---------------------------------------------------------------------

class _CRG(LiteXModule):
    """Minimal CRG for Fomu EVT: derives 12 MHz sys clock from the 48 MHz oscillator via PLL.

    Unlike the upstream Fomu CRG we omit the USB clock domains since we
    use GPIO-based serial UART instead of USB ACM.
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
        pll.clko_freq_range = (12e6, 275e9)  # Widen range per upstream workaround.
        pll.register_clkin(clk48, 48e6)
        pll.create_clkout(self.cd_sys, 12e6, with_reset=False)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~por_done | ~pll.locked)


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = kosagi_fomu_evt.Platform()

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        # Use GPIO serial pins instead of USB ACM.
        kwargs["uart_name"] = "serial"
        # Disable integrated SRAM/ROM -- iCE40 block RAM is too small; use SPRAM instead.
        kwargs["integrated_sram_size"] = 0
        kwargs["integrated_rom_size"]  = 0
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # 128 KB SPRAM (64 KB SRAM + 64 KB main RAM) ------------------------------------------
        self.spram = Up5kSPRAM(size=128*kB)
        self.bus.add_slave("psram", self.spram.bus, SoCRegion(size=128*kB))
        self.bus.add_region("sram", SoCRegion(
            origin = self.bus.regions["psram"].origin + 0*kB,
            size   = 64*kB,
            linker = True)
        )
        if not self.integrated_main_ram_size:
            self.bus.add_region("main_ram", SoCRegion(
                origin = self.bus.regions["psram"].origin + 64*kB,
                size   = 64*kB,
                linker = True)
            )


# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="UART Test SoC for Fomu EVT")
    parser.add_argument("--build", action="store_true", help="Build bitstream.")
    args = parser.parse_args()

    soc = BaseSoC(
        sys_clk_freq           = int(12e6),
        ident                  = "fpgas-online UART Test SoC -- Fomu EVT",
        ident_version          = True,
        uart_baudrate          = 115200,
        integrated_main_ram_size = 0,  # Provided by SPRAM above.
    )

    output_dir = default_build_dir(__file__, "fomu")
    builder = Builder(soc, output_dir=output_dir)
    if args.build:
        builder.build()


if __name__ == "__main__":
    main()
