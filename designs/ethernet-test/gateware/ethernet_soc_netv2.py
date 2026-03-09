#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_netv2.py
"""LiteX SoC with LiteEth (RMII) for NeTV2 Ethernet testing.

The NeTV2 has an independent RMII 100Base-T Ethernet PHY with:
  - RMII reference clock on pin D17 (50 MHz)
  - Separate RJ45 jack (not shared with the RPi's Ethernet)

This builds a standard LiteX SoC using the kosagi_netv2 target with
--with-ethernet enabled.

Note on yosys+nextpnr toolchain:
  DDR3 should be disabled and the clock frequency lowered when using the
  open-source toolchain.  This script therefore uses
  --integrated-main-ram-size=8192 and --sys-clk-freq=50e6 by default.
"""

import importlib, pathlib, sys  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
importlib.import_module("_migen_compat")  # patch migen tracer for Python >= 3.11

from litex.soc.integration.builder import Builder
from litex_boards.platforms import kosagi_netv2
from litex_boards.targets.kosagi_netv2 import BaseSoC


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="Ethernet Test SoC for NeTV2")
    parser.add_target_argument("--variant",      default="a7-35",           help="Board variant (a7-35 or a7-100).")
    parser.add_target_argument("--sys-clk-freq", default=50e6,  type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    # Note: ident/ident_version are hard-coded by the upstream BaseSoC and
    # cannot be overridden via kwargs without causing a duplicate-keyword error.
    soc_kwargs.pop("ident", None)
    soc_kwargs.pop("ident_version", None)
    soc_kwargs["uart_baudrate"] = 115200

    soc = BaseSoC(
        variant       = args.variant,
        sys_clk_freq  = int(args.sys_clk_freq),
        with_ethernet = True,
        **soc_kwargs,
    )

    # Newer yosys emits $scopeinfo cells that older nextpnr-xilinx cannot place.
    # Provide a custom yosys template with a "delete t:$scopeinfo" step between
    # synth and write to strip them before the JSON netlist is emitted.
    from litex.build.yosys_wrapper import YosysWrapper
    patched = []
    for line in YosysWrapper._default_template:
        if line.startswith("write_"):
            patched.append("delete t:$scopeinfo")
        patched.append(line)
    soc.platform.toolchain._yosys_template = patched

    builder_kwargs = parser.builder_argdict
    builder_kwargs["output_dir"] = "build/netv2"
    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
