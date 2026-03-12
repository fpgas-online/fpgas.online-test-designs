#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on TinyTapeout FPGA Demo Board (iCE40UP5K).

Builds a SoC with CPU + BIOS + UART + SPI Flash access. The BIOS prints
the SPI flash identification on boot.

TT FPGA SPI Flash: on dedicated iCE40 pins (CS_N=16, CLK=15, MOSI=14, MISO=17).
Clock: 50 MHz from RP2040 → 12 MHz system clock via PLL.
UART: RX=ui_in[3] (pin 21), TX=uo_out[4] (pin 45), via RP2040 USB bridge.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_tt.py --build

The bitstream is written to: designs/spi-flash-id/build/tt/gateware/ice40up5ksg48.bit
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from designs._shared.tt_fpga_platform import Platform
from designs._shared.tt_fpga_crg import TtFpgaCRG
from designs._shared.build_helpers import default_build_dir

kB = 1024


# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = Platform()

        # CRG --------------------------------------------------------------------------------------
        self.crg = TtFpgaCRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        # Use serial pins (UART via RP2040 USB bridge).
        kwargs["uart_name"] = "serial"
        # BIOS lives in EBR-based ROM (initialized via bitstream).
        # SPRAM is used for SRAM/main_ram only (cannot be initialized).
        kwargs["integrated_rom_size"]  = 12*kB
        kwargs["integrated_sram_size"] = 0
        # Use VexRiscv "minimal" variant: smallest footprint for iCE40.
        kwargs.setdefault("cpu_variant", "minimal")
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # Shrink BIOS to fit in iCE40 EBR: disable boot sequence and CRC.
        # (BIOS_NO_BUILD_TIME is set automatically when ident_version=False.)
        self.add_config("BIOS_NO_BOOT")
        self.add_config("BIOS_NO_CRC")

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
    parser = argparse.ArgumentParser(description="SPI Flash ID Test SoC for TT FPGA")
    parser.add_argument("--build",         action="store_true", help="Build bitstream.")
    parser.add_argument("--sys-clk-freq",  default=12e6, type=float, help="System clock frequency.")
    parser.add_argument("--output-dir",    default=None, help="Override build output directory.")
    args = parser.parse_args()

    sys_clk_freq = int(args.sys_clk_freq)

    soc = BaseSoC(
        sys_clk_freq = sys_clk_freq,
        cpu_variant  = "minimal",
        ident        = "fpgas-online SPI Flash Test SoC -- TT FPGA",
        uart_baudrate = 115200,
    )

    output_dir = args.output_dir or default_build_dir(__file__, "tt")
    builder = Builder(soc, output_dir=output_dir,
        bios_console = "lite",  # Minimal console to fit in iCE40 EBR.
        bios_lto     = True,    # Link-time optimization for smaller BIOS.
    )
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
