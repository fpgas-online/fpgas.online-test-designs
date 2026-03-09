#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Kosagi NeTV2.

NeTV2 SPI Flash: Quad SPI, CS=T19.
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_netv2.py --toolchain openxc7 --build

The bitstream is written to: designs/spi-flash-id/build/netv2/gateware/netv2_spiflash_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_netv2 import Platform


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=Platform, description="SPI Flash ID Test SoC for NeTV2")
    target_group = parser.target_group
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    parser.set_defaults(
        ident          = "fpgas-online SPI Flash Test SoC -- NeTV2",
        uart_baudrate  = 115200,
        output_dir     = "designs/spi-flash-id/build/netv2",
    )
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    # Fix device string: NeTV2 platform uses "xc7a35t-fgg484-2" but the openxc7
    # toolchain (prjxray-db/bbaexport) expects "xc7a35tfgg484-2" (no hyphen
    # between the device family and package).
    platform.device = platform.device.replace("t-fgg", "tfgg")
    sys_clk_freq = int(args.sys_clk_freq)

    # Workaround: newer Yosys emits $scopeinfo cells that older nextpnr-xilinx
    # cannot place. Strip them after synthesis by using a custom Yosys template.
    platform.toolchain._yosys_template = [
        "verilog_defaults -push",
        "verilog_defaults -add -defer",
        "{read_files}",
        "verilog_defaults -pop",
        'attrmap -tocase keep -imap keep="true" keep=1 -imap keep="false" keep=0 -remove keep=0',
        "{yosys_cmds}",
        "synth_{target} {synth_opts} -top {build_name}",
        "delete t:$scopeinfo",
        "write_{write_fmt} {write_opts} {output_name}.{synth_fmt}",
    ]

    soc = SoCCore(
        platform       = platform,
        clk_freq       = sys_clk_freq,
        **parser.soc_argdict,
    )

    # Add SPI Flash with bitbang access for JEDEC ID reading -------------------
    from litex.soc.cores.spi_flash import S7SPIFlash
    soc.submodules.spiflash = S7SPIFlash(
        pads         = platform.request("spiflash"),
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_csr("spiflash")

    builder = Builder(soc, **parser.builder_argdict)
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
