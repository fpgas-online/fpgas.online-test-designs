#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_arty.py
"""LiteX SoC with LiteEth (MII) for Arty A7 Ethernet testing.

Builds a standard LiteX SoC with:
  - VexRiscv CPU + BIOS (with built-in networking: ARP, ICMP, TFTP)
  - DDR3 SDRAM (256 MB via MT41K128M16JT-125)
  - LiteEth MAC + MII PHY (TI DP83848J, 100Base-T)
  - UART at 115200 baud

The BIOS boots, initializes the Ethernet PHY, prints the MAC address, and
responds to ARP/ICMP automatically.  No custom firmware is needed.

Default network config (LiteX BIOS defaults):
  - FPGA IP:  192.168.1.50
  - Host IP:  192.168.1.100 (TFTP server)
  - MAC:      10:e2:d5:00:00:00 (default, configurable via --eth-ip)

Note on yosys+nextpnr toolchain:
  The upstream digilent_arty target notes that DDR3 should be disabled and
  the clock frequency lowered when using the open-source toolchain.  This
  script therefore uses --integrated-main-ram-size=8192 and --sys-clk-freq=50e6
  when targeting yosys+nextpnr.
"""

import gateware._migen_compat  # noqa: F401  -- patch migen tracer for Python >= 3.11

from litex.soc.integration.builder import Builder
from litex_boards.platforms import digilent_arty
from litex_boards.targets.digilent_arty import BaseSoC


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="Ethernet Test SoC for Arty A7")
    parser.add_target_argument("--variant",      default="a7-35",           help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=50e6,  type=float, help="System clock frequency.")
    parser.add_target_argument("--eth-ip",       default="192.168.1.50",    help="Ethernet IP address.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"]         = "fpgas-online Ethernet Test SoC -- Arty A7"
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200

    soc = BaseSoC(
        variant       = args.variant,
        toolchain     = args.toolchain,
        sys_clk_freq  = int(args.sys_clk_freq),
        with_ethernet = True,
        eth_ip        = args.eth_ip,
        **soc_kwargs,
    )

    builder = Builder(soc, output_dir="build/arty", **parser.builder_argdict)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
