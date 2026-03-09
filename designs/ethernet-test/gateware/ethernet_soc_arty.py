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
  - MAC:      10:e2:d5:00:00:00 (LiteX default)

Note on open-source toolchain (openxc7 / yosys+nextpnr):
  The upstream digilent_arty target notes that DDR3 should be disabled and
  the clock frequency lowered when using the open-source toolchain.  This
  script therefore uses --sys-clk-freq=50e6 by default.

  The openxc7 toolchain requires these environment variables:
    CHIPDB                   - directory for chipdb .bin cache (may be empty)
    NEXTPNR_XILINX_PYTHON_DIR - path to nextpnr-xilinx python scripts
    PRJXRAY_DB_DIR           - path to prjxray-db database
"""

import importlib, pathlib, sys  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
importlib.import_module("_migen_compat")  # patch migen tracer for Python >= 3.11

from litex.soc.integration.builder import Builder
from litex_boards.platforms import digilent_arty
from litex_boards.targets.digilent_arty import BaseSoC

from _toolchain_fixups import clean_soc_kwargs, apply_yosys_nextpnr_workarounds


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=digilent_arty.Platform, description="Ethernet Test SoC for Arty A7")
    parser.add_target_argument("--variant",      default="a7-35",           help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=50e6,  type=float, help="System clock frequency.")
    parser.add_target_argument("--eth-ip",       default="192.168.1.50",    help="Ethernet IP address.")
    args = parser.parse_args()

    soc_kwargs = clean_soc_kwargs(parser)

    soc = BaseSoC(
        variant       = args.variant,
        toolchain     = args.toolchain,
        sys_clk_freq  = int(args.sys_clk_freq),
        with_ethernet = True,
        eth_ip        = args.eth_ip,
        **soc_kwargs,
    )

    apply_yosys_nextpnr_workarounds(soc)

    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = "build/arty"
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
