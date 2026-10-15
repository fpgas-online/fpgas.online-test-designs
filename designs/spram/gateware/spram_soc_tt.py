#!/usr/bin/env python3
"""
LiteX SoC target for the SPRAM test on the TinyTapeout FPGA Demo Board (iCE40UP5K), #343.

The SoC is the UART test's (designs/uart/gateware/uart_soc_tt.py: CPU, 1 KB boot ROM in block RAM, UART over the
RP2350 bridge, the SPRAM as one 128 KB bus region: two 64 KB banks of two side-by-side SPRAMs) with other firmware
in its ROM: generate_spram_firmware (designs/_shared/ice40_firmware.py). That firmware keeps every value in
registers, so nothing but the test touches the SPRAM. On each byte it receives it writes and reads back the whole
SPRAM twice (a pattern holding each word's address, then its inverse) and checks each byte lane's write mask, and
says "SPRAM_TEST: PASS" or where it failed. The host side is designs/spram/host/test_spram.py.

Build command (from repo root):
    uv run python designs/spram/gateware/spram_soc_tt.py --build

The bitstream is written to:
    designs/spram/build/tt-fpga-yosys-nextpnr/gateware/tt_fpga_platform.bin
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.soc.integration.builder import Builder

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, default_build_dir, flow_suffix
from designs._shared.ice40_firmware import install_spram_firmware
from designs.uart.gateware.uart_soc_tt import BaseSoC


def main():
    parser = argparse.ArgumentParser(description="SPRAM Test SoC for TT FPGA")
    parser.add_argument("--build", action="store_true", help="Build bitstream.")
    args = parser.parse_args()

    ident = "fpgas-online SPRAM Test SoC -- TT FPGA"

    soc = BaseSoC(
        sys_clk_freq=int(12e6),
        ident=ident,
        uart_baudrate=115200,
        integrated_main_ram_size=0,  # The SPRAM is the region under test.
    )

    output_dir = default_build_dir(__file__, board_dir("tt", "fpga") + flow_suffix("icestorm"))
    # No LiteX BIOS (it does not fit the iCE40's block RAM, and it would use the SPRAM): the test firmware only.
    builder = Builder(soc, output_dir=output_dir, compile_software=False)
    install_spram_firmware(soc, ident)
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
