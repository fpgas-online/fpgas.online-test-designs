#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SPI Flash access. The BIOS prints
the SPI flash identification on boot. Additionally, custom firmware can
be loaded to explicitly read the JEDEC ID via command 0x9F.

Arty A7 SPI Flash: Quad SPI, CS=L13.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/spi-flash-id/build/arty/gateware/arty_spiflash_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.digilent_arty import Platform


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="SPI Flash ID Test SoC for Arty A7")
    target_group = parser.add_argument_group(title="Target options")
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--toolchain",     default="yosys+nextpnr", help="FPGA toolchain.")
    target_group.add_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    builder_args = Builder.add_arguments(parser)
    soc_args = SoCCore.add_arguments(parser)
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = platform,
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online SPI Flash Test SoC — Arty A7",
        ident_version  = True,
        uart_baudrate  = 115200,
        **SoCCore.argdict(args),
    )

    # Add SPI Flash with bitbang access for JEDEC ID reading -------------------
    from litex.soc.cores.spi_flash import SpiFlash
    soc.submodules.spiflash = SpiFlash(
        platform.request("spiflash4x"),
        dummy=11,
        div=2,
        endianness="little",
    )
    soc.add_csr("spiflash")

    builder = Builder(soc, output_dir="designs/spi-flash-id/build/arty", **Builder.argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
