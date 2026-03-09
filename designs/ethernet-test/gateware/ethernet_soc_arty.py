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
"""

import argparse

from litex.soc.integration.builder import Builder

from litex_boards.targets.digilent_arty import BaseSoC


def main():
    parser = argparse.ArgumentParser(description="Ethernet Test SoC for Arty A7")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream")
    parser.add_argument("--eth-ip",     default="192.168.1.50",  help="FPGA IP address")
    parser.add_argument("--remote-ip",  default="192.168.1.100", help="Host/TFTP IP address")
    args = parser.parse_args()

    # BaseSoC from litex-boards already supports --with-ethernet and --with-sdram.
    # We instantiate it directly with the flags we need.
    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=100e6,
        with_ethernet=True,
        with_sdram=True,
        uart_baudrate=115200,
        ident="Ethernet Test SoC (Arty A7)",
        ident_version=True,
    )

    builder = Builder(soc, output_dir="build/arty")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
