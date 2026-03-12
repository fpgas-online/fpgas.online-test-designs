#!/usr/bin/env python3
"""
LiteX SoC target for UART test on Fomu EVT (Lattice iCE40UP5K).

Builds a minimal SoC with CPU + BIOS + UART over GPIO serial pins
(RX=pin 21, TX=pin 13).  The Fomu's upstream LiteX target defaults to
USB ACM; we override to use standard pin-based serial instead.

Memory layout:
  - Boot ROM: iCE40 EBR (block RAM), initialized via bitstream with BIOS.
  - SRAM + main RAM: 128 KB UP5K SPRAM (64 KB + 64 KB).

SPRAM cannot be initialized via bitstream, so a small block-RAM ROM is
required for the CPU to boot.  The iCE40UP5K has 30 EBR blocks (15 KB
total); we use ~12 KB for ROM, leaving the rest for peripheral FIFOs.

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

from litex_boards.platforms import kosagi_fomu_evt

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from designs._shared.build_helpers import default_build_dir
from designs._shared.fomu_crg import FomuCRG

kB = 1024


# BaseSoC -----------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = kosagi_fomu_evt.Platform()

        # CRG ----------------------------------------------------------------------------------
        self.crg = FomuCRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        # Use GPIO serial pins instead of USB ACM.
        kwargs["uart_name"] = "serial"
        # BIOS lives in EBR-based ROM (initialized via bitstream).
        # SPRAM is used for SRAM/main_ram only (cannot be initialized).
        kwargs["integrated_rom_size"]  = 15*kB
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
    parser = argparse.ArgumentParser(description="UART Test SoC for Fomu EVT")
    parser.add_argument("--build", action="store_true", help="Build bitstream.")
    args = parser.parse_args()

    ident = "fpgas-online UART Test SoC -- Fomu EVT"

    soc = BaseSoC(
        sys_clk_freq           = int(12e6),
        ident                  = ident,
        uart_baudrate          = 115200,
        integrated_main_ram_size = 0,  # Provided by SPRAM above.
    )

    output_dir = default_build_dir(__file__, "fomu")
    # Skip BIOS compilation — LiteX BIOS (~24 KB) does not fit in iCE40 EBR (15 KB).
    # Instead, install minimal custom firmware (< 200 bytes) after SoC finalization.
    builder = Builder(soc, output_dir=output_dir, compile_software=False)

    from designs._shared.ice40_firmware import install_uart_firmware
    install_uart_firmware(soc, ident)

    builder.build(run=args.build)


if __name__ == "__main__":
    main()
