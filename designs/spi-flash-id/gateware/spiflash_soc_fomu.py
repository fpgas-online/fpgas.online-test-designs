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

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

from migen import *

from litex.soc.cores.ram import Up5kSPRAM
from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_fomu_evt import Platform

from designs._shared.build_helpers import default_build_dir
from designs._shared.fomu_crg import FomuCRG

kB = 1024


# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(12e6), **kwargs):
        platform = Platform()

        # CRG --------------------------------------------------------------------------------------
        self.crg = FomuCRG(platform, sys_clk_freq)

        # SoCCore ----------------------------------------------------------------------------------
        # Use hardware UART on serial pins (not USB ACM).
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
        # BIOS still prints init header + SPI flash info + "Done (No Console)".
        # (BIOS_NO_BUILD_TIME is set automatically when ident_version=False.)
        self.add_config("BIOS_NO_PROMPT")
        self.add_config("BIOS_NO_BOOT")
        self.add_config("BIOS_NO_CRC")
        self.add_config("MAIN_RAM_INIT")

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
    ident = "fpgas-online SPI Flash Test SoC -- Fomu EVT"

    soc = BaseSoC(
        sys_clk_freq = sys_clk_freq,
        cpu_variant  = "minimal",
        ident        = ident,
        uart_baudrate = 115200,
    )

    output_dir = args.output_dir or default_build_dir(__file__, "fomu")
    # Skip BIOS compilation — LiteX BIOS (~24 KB) does not fit in iCE40 EBR (15 KB).
    # TODO: Replace with SPI Flash firmware that reads JEDEC ID once implemented.
    builder = Builder(soc, output_dir=output_dir, compile_software=False)

    from designs._shared.ice40_firmware import install_uart_firmware
    install_uart_firmware(soc, ident)

    builder.build(run=args.build)


if __name__ == "__main__":
    main()
