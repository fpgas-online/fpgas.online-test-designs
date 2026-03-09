#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Kosagi NeTV2.

NeTV2 SPI Flash: Quad SPI, CS=T19.
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_netv2.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/spi-flash-id/build/netv2/gateware/netv2_spiflash_test.bit
"""

from litex.soc.integration.soc_core import SoCCore, soc_core_args, soc_core_argdict
from litex.soc.integration.builder import Builder, builder_args, builder_argdict

from litex_boards.platforms.kosagi_netv2 import Platform


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="SPI Flash ID Test SoC for NeTV2")
    target_group = parser.add_argument_group(title="Target options")
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--toolchain",     default="yosys+nextpnr", help="FPGA toolchain.")
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    builder_args(parser)
    soc_core_args(parser)
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = platform,
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online SPI Flash Test SoC — NeTV2",
        ident_version  = True,
        uart_baudrate  = 115200,
        **soc_core_argdict(args),
    )

    # Add SPI Flash with bitbang access for JEDEC ID reading -------------------
    from litex.soc.cores.spi_flash import S7SPIFlash
    soc.submodules.spiflash = S7SPIFlash(
        pads         = platform.request("spiflash"),
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_csr("spiflash")

    builder = Builder(soc, output_dir="designs/spi-flash-id/build/netv2", **builder_argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
