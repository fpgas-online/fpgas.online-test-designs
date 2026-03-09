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

from _toolchain_fixups import clean_soc_kwargs, apply_yosys_nextpnr_workarounds


def main():
    from litex.build.parser import LiteXArgumentParser
    parser = LiteXArgumentParser(platform=kosagi_netv2.Platform, description="Ethernet Test SoC for NeTV2")
    parser.add_target_argument("--variant", default="a7-35",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)")
    parser.add_target_argument("--sys-clk-freq", default=50e6,  type=float, help="System clock frequency.")
    args = parser.parse_args()

    soc_kwargs = clean_soc_kwargs(parser)

    # The upstream NeTV2 BaseSoC doesn't pass toolchain to Platform, so we
    # monkey-patch the Platform default to match the requested toolchain.
    _orig_init = kosagi_netv2.Platform.__init__
    _toolchain = args.toolchain
    _variant = args.variant
    def _patched_platform_init(self, variant="a7-35", toolchain="vivado"):
        _orig_init(self, variant=_variant, toolchain=_toolchain)
    kosagi_netv2.Platform.__init__ = _patched_platform_init

    soc = BaseSoC(
        sys_clk_freq  = int(args.sys_clk_freq),
        with_ethernet = True,
        **soc_kwargs,
    )

    # Restore original init
    kosagi_netv2.Platform.__init__ = _orig_init

    # The NeTV2 platform defines its device as "xc7a35t-fgg484-2" but the
    # openxc7 toolchain and prjxray-db expect "xc7a35tfgg484-2" (no dash
    # between device family and package).  Patch the platform device string.
    if "-" in soc.platform.device:
        # xc7a35t-fgg484-2 -> xc7a35tfgg484-2
        parts = soc.platform.device.split("-")
        if len(parts) == 3:
            soc.platform.device = parts[0] + parts[1] + "-" + parts[2]

    apply_yosys_nextpnr_workarounds(soc)

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
