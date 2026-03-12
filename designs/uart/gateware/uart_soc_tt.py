#!/usr/bin/env python3
"""
LiteX SoC target for UART test on TinyTapeout FPGA Demo Board (iCE40UP5K).

Builds a minimal SoC with CPU + BIOS + UART.  The TT FPGA board's
RP2040 acts as a USB-to-UART bridge:
  UART RX = ui_in[3] (pin 21), TX = uo_out[4] (pin 45).

Memory layout:
  - Boot ROM: iCE40 EBR (block RAM), initialized via bitstream with BIOS.
  - SRAM + main RAM: 128 KB UP5K SPRAM (64 KB + 64 KB).

SPRAM cannot be initialized via bitstream, so a small block-RAM ROM is
required for the CPU to boot.  The iCE40UP5K has 30 EBR blocks (15 KB
total); we use ~12 KB for ROM, leaving the rest for peripheral FIFOs.

Clock: 50 MHz from RP2040 → 12 MHz system clock via PLL.

Build command (from repo root):
    uv run python designs/uart/gateware/uart_soc_tt.py --build

The bitstream is written to:
    designs/uart/build/tt/gateware/tt_fpga_platform.bin
"""

import argparse
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from designs._shared.tt_fpga_platform import Platform
from designs._shared.tt_fpga_crg import TtFpgaCRG
from designs._shared.build_helpers import default_build_dir, patch_builder_gc_sections

kB = 1024


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = Platform()

        # CRG ----------------------------------------------------------------------------------
        self.crg = TtFpgaCRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        # Use serial pins (UART via RP2040 USB bridge).
        kwargs["uart_name"] = "serial"
        # BIOS lives in EBR-based ROM (initialized via bitstream).
        # SPRAM is used for SRAM/main_ram only (cannot be initialized).
        kwargs["integrated_rom_size"]  = 12*kB
        kwargs["integrated_sram_size"] = 0
        # Use VexRiscv "minimal" variant: smallest footprint for iCE40.
        kwargs.setdefault("cpu_variant", "minimal")
        SoCCore.__init__(self, platform, sys_clk_freq, **kwargs)

        # Shrink BIOS to fit in iCE40 EBR (~15 KB max).
        # Disable banner, boot sequence, CRC, and memtest to minimize ROM usage.
        # BIOS still prints init header + "Done (No Console)" over UART.
        # (BIOS_NO_BUILD_TIME is set automatically when ident_version=False.)
        self.add_config("BIOS_NO_PROMPT")
        self.add_config("BIOS_NO_BOOT")
        self.add_config("BIOS_NO_CRC")
        self.add_config("MAIN_RAM_INIT")

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
    parser = argparse.ArgumentParser(description="UART Test SoC for TT FPGA")
    parser.add_argument("--build", action="store_true", help="Build bitstream.")
    args = parser.parse_args()

    soc = BaseSoC(
        sys_clk_freq           = int(12e6),
        ident                  = "fpgas-online UART Test SoC -- TT FPGA",
        uart_baudrate          = 115200,
        integrated_main_ram_size = 0,  # Provided by SPRAM above.
    )

    output_dir = default_build_dir(__file__, "tt")
    builder = Builder(soc, output_dir=output_dir,
        bios_console = "disable",  # No interactive console; LTO removes all cmd code.
        bios_lto     = True,       # Link-time optimization for smaller BIOS.
    )
    patch_builder_gc_sections(builder)
    if args.build:
        builder.build()


if __name__ == "__main__":
    main()
