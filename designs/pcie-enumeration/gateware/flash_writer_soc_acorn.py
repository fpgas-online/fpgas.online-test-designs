#!/usr/bin/env python3
"""Minimal LiteX SoC for Acorn flash bootstrap via JTAG (no PCIe).

This is the bootstrap path: with the FPGA running this design (JTAG-loaded
into SRAM), the host can talk to the FPGA over the JTAG TAP via
`litex_server --jtag` and write a new bitstream into the on-board QSPI flash
using S7SPIFlash CSRs. After the write, an ICAP IPROG reload moves the FPGA
to the new bitstream in flash, with no JTAG involvement during the actual
reconfiguration.

Why no PCIe in this design: the welland-pi4 Acorn auto-reverts to the
flash-resident factory firmware whenever a JTAG-loaded LiteX bitstream
brings up a PCIe endpoint (almost certainly via a PERST→PROG_B circuit
fired by host PCIe link maintenance). A non-PCIe bitstream like spiOverJtag
stays loaded fine — so this design intentionally omits PCIe and uses
JTAGBone for the host control channel instead.

Cores included:
  * S7SPIFlash + GPIOOut(flash_cs_n) — write the new bitstream into QSPI
  * ICAP + add_reload() — trigger fundamental reconfig from flash
  * JTAGBone (default chain 1) — host wishbone-over-JTAG transport

Build:
    uv run python flash_writer_soc_acorn.py --variant cle-215+ --toolchain openxc7 --build

Then JTAG-load to SRAM:
    openFPGALoader --cable libgpiod --pins 10:9:11:8 build/acorn-flash-writer/gateware/sqrl_acorn.bit

Then from the host:
    litex_server --jtag --jtag-config /path/to/tap-config
    litex_term       # or wishbone-tool, or custom Python via litex.tools.litex_client

Variants: cle-215+ (XC7A200T-3), cle-215 (XC7A200T-2), cle-101 (XC7A100T-2).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.cores.gpio import GPIOOut
from litex.soc.cores.icap import ICAP
from litex.soc.cores.spi_flash import S7SPIFlash
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import sqrl_acorn
from migen import *

# IMPORTANT — before building this design, run
# `scripts/apply_litex_jtag_patch.py .venv/lib/python3.12/site-packages/litex/soc/cores/jtag.py`
# to install the LiteX xc7 JTAGPHY rx-wiring fix. The 2025.12 release in
# uv.lock has the broken FSM (signals declared but never wired to the
# output stream); upstream fixed it in 2026.04. Without the patch the
# host-to-target JTAGBone stream is silently dropped.

import designs._shared.migen_compat  # noqa: F401
from designs._shared.build_helpers import default_build_dir
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import patch_yosys_template


class _CRG(LiteXModule):
    """Minimal CRG: PLL generates sys_clk from the on-board 200 MHz differential clock."""

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")

        clk200 = platform.request("clk200")

        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


class FlashWriterSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7", sys_clk_freq=100e6, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)
        if toolchain == "openxc7":
            fix_openxc7_device_name(platform)

        # CRG -------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore — with JTAGBone, NO CPU (saves area, JTAGBone wishbone is enough) ----------
        # Use no CPU so we don't need a BIOS / ROM. The JTAGBone host can write directly
        # to the CSR/wishbone bus.
        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="Acorn flash writer SoC (JTAGBone + S7SPIFlash + ICAP)",
            ident_version=True,
            cpu_type=None,                # no CPU
            integrated_rom_size=0,
            integrated_main_ram_size=0x1000,  # tiny scratchpad
            with_jtagbone=True,           # JTAG ↔ wishbone bridge for host control
            with_uart=False,
            **kwargs,
        )

        # ICAP — IPROG warm reload ----------------------------------------------------------
        self.icap = ICAP()
        self.icap.add_reload()
        self.icap.add_timing_constraints(platform, sys_clk_freq, self.crg.cd_sys.clk)

        # SPI flash via S7SPIFlash bit-bang -------------------------------------------------
        self.flash_cs_n = GPIOOut(platform.request("flash_cs_n"))
        self.flash = S7SPIFlash(platform.request("flash"), sys_clk_freq, 25e6)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="cle-215+",
                        choices=["cle-215+", "cle-215", "cle-101"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    soc = FlashWriterSoC(variant=args.variant, toolchain=args.toolchain)

    if args.toolchain == "openxc7":
        ensure_chipdb_symlink(soc.platform)
    patch_yosys_template(soc)

    builder = Builder(soc, output_dir=default_build_dir(__file__, "acorn-flash-writer"))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
