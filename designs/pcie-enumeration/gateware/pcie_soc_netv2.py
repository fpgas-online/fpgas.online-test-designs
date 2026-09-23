#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for NeTV2 PCIe enumeration testing.

Builds a LiteX SoC targeting the NeTV2 board (Xilinx 7-Series) with:
  - VexRiscv CPU + BIOS + UART (115200 baud)
  - DDR3 SDRAM (512 MB) via Xilinx A7DDRPHY
  - LitePCIe endpoint (PCIe Gen2 x1, BAR0 for Wishbone bridge access)
    Vendor ID 0x10EE (Xilinx), Device ID 0x7011.

Three toolchain flows are supported (Phase 3 of the plan):

    Pure Vivado (proprietary):
        --toolchain vivado --synth-mode vivado
        Uses Vivado's proprietary pcie_7x IP from the Xilinx catalog.
    Yosys→Vivado (hybrid — open-source synth, proprietary P&R):
        --toolchain vivado --synth-mode yosys
        Uses the open-source pcie_7x core (github.com/regymm/pcie_7x).
    Yosys→nextpnr (fully open-source):
        --toolchain openxc7
        Uses the open-source pcie_7x core.

The FPGA must be programmed via JTAG (OpenOCD) BEFORE the RPi5 scans
the PCIe bus.  After programming, the host triggers a bus rescan.

NeTV2 PCIe pinout:
  - CLK: F10 (P) / E10 (N)
  - RST_N: E18
  - Lane 0: RX D11/C11, TX D5/C5

Build command:
    uv run python designs/pcie-enumeration/gateware/pcie_soc_netv2.py \\
        --variant a7-35 --toolchain <openxc7|vivado> \\
        [--synth-mode <vivado|yosys>] --build
"""

import glob
import os
import pathlib
import sys

# Add repo root to sys.path so shared modules can be imported.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litedram.modules import MT41K256M16
from litedram.phy import s7ddrphy
from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
from litepcie.frontend.wishbone import LitePCIeWishboneBridge
from litepcie.phy.s7pciephy import S7PCIEPHY
from litex.gen import *
from litex.soc.cores.clock import S7IDELAYCTRL, S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import kosagi_netv2
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer for Python >= 3.11
from designs._shared.build_helpers import board_dir, default_build_dir, flow_suffix
from designs._shared.pin_check import check_build
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.s7pcie_clocking import feed_pclk_mux_from_mmcm
from designs._shared.yosys_workarounds import apply_nodram_workaround, patch_yosys_template

# Path to the open-source pcie_7x Verilog sources (git submodule).
PCIE_7X_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pcie_7x", "src")

# GTP channel behind the pcie_x1 pins (D11/C11, D5/C5), from Vivado's package-pin map. The numbering
# depends on the part, so it is per variant.
PCIE_X1_GT_LOC = {"a7-35": "GTPE2_CHANNEL_X0Y1", "a7-100": "GTPE2_CHANNEL_X0Y5"}

# The GTP's TXOUTCLK pin, which every PCIe clock derives from (Tcl, braces doubled for LiteX's format()).
_TXOUTCLK = (
    "[get_pins -of_objects [get_cells -hierarchical -filter {{REF_NAME == GTPE2_CHANNEL}}]"
    " -filter {{REF_PIN_NAME == TXOUTCLK}}]"
)

# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """CRG for NeTV2 with DDR3 clock domains."""

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")
        self.cd_sys4x = ClockDomain("sys4x")
        self.cd_sys4x_dqs = ClockDomain("sys4x_dqs")
        self.cd_idelay = ClockDomain("idelay")

        # Clk.
        clk50 = platform.request("clk50")

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        pll.create_clkout(self.cd_sys4x, 4 * sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4 * sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay, 200e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)

        # IdelayCtrl.
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)


# SoC ----------------------------------------------------------------------------------------------


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="openxc7",
                 uses_opensource_pcie=True, sys_clk_freq=50e6, **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        if toolchain in ("openxc7", "yosys+nextpnr"):
            fix_openxc7_device_name(platform)
            # S7PCIEPHY.add_sources() appends Vivado-specific TCL commands to
            # these toolchain attributes.  Provide empty lists for openxc7.
            for attr in ("pre_synthesis_commands", "pre_placement_commands"):
                if not hasattr(platform.toolchain, attr):
                    setattr(platform.toolchain, attr, [])

        if uses_opensource_pcie:
            # Add pcie_7x open-source Verilog sources — provides the pcie_s7
            # module that S7PCIEPHY instantiates, replacing Vivado's
            # proprietary pcie_7x IP. Used by the openxc7/yosys+nextpnr flow
            # and the Yosys→Vivado hybrid flow.
            for vfile in sorted(glob.glob(os.path.join(PCIE_7X_SRC, "*.v"))):
                platform.add_source(vfile)
        # else: pure Vivado — S7PCIEPHY (instantiated below) will emit
        # Vivado TCL into platform.toolchain.pre_synthesis_commands that
        # instantiates the proprietary pcie_7x core from the Xilinx IP
        # catalog. Adding the open-source sources here would create
        # duplicate module definitions at synth_design time.

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="PCIe Enumeration Test SoC (NeTV2)",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=0x10000,  # 64 KB BIOS ROM
            **kwargs,
        )

        # DDR3 SDRAM ---------------------------------------------------------------------------
        self.ddrphy = s7ddrphy.A7DDRPHY(
            platform.request("ddram"),
            memtype="DDR3",
            nphases=4,
            sys_clk_freq=sys_clk_freq,
        )
        self.add_sdram(
            "sdram",
            phy=self.ddrphy,
            module=MT41K256M16(sys_clk_freq, "1:4"),
            l2_cache_size=8192,
        )

        # PCIe Gen2 x1 endpoint ---------------------------------------------------------------
        self.pcie_phy = S7PCIEPHY(
            platform,
            platform.request("pcie_x1"),
            data_width=64,
            bar0_size=0x20000,  # 128 KB BAR0
        )
        if uses_opensource_pcie:
            # pcie_s7 comes from the pcie_7x sources above, so the PHY must not emit its Xilinx IP
            # Tcl: create_ip/synth_ip, and reset_property LOC on the IP's cell names, which match
            # nothing in the open-source core and stop Vivado in the yosys-vivado flow.
            self.pcie_phy.external_hard_ip = True
            if toolchain == "vivado":
                # The Xilinx IP's own XDC declares TXOUTCLK; the open-source core has none. Declared first:
                # every PCIe clock, the PIPECLK mux's below included, is derived from it.
                platform.toolchain.pre_placement_commands.append(
                    "create_clock -name pcie_txoutclk -period 10.000 " + _TXOUTCLK
                )
                # Keep the core's PIPE logic in its transceiver's clock region. Left to itself the placer pulled
                # it ~180 columns away, and the RXVALID -> rxvalid_cnt reset path at 250 MHz (one LUT, but a
                # long route out of the GTP) closed on one run and missed by up to 0.33 ns on the next (Acorn
                # CLE-215+). In the region it had +1.29 ns. The GTP's LOC is known after link, from its pins.
                platform.toolchain.pre_placement_commands += [
                    "create_pblock pcie_pipe",
                    "add_cells_to_pblock [get_pblocks pcie_pipe] [get_cells -hierarchical -filter"
                    " {{NAME =~ */pipe_wrapper_i/* && IS_PRIMITIVE && REF_NAME !~ GTPE2*"
                    " && REF_NAME != GND && REF_NAME != VCC}}]",
                    "resize_pblock [get_pblocks pcie_pipe] -add CLOCKREGION_[get_clock_regions -of_objects"
                    " [get_sites -of_objects [get_cells -hierarchical -filter {{REF_NAME == GTPE2_CHANNEL}}]]]",
                ]
        elif toolchain == "vivado":
            # The IP's own XDC LOCs its lane-0 transceiver to GTPE2_CHANNEL_X0Y7, and a cell LOC beats a
            # port LOC without an error, so the lane ends up on another lane's pins and never links (#25).
            self.pcie_phy.add_gt_loc_constraints([PCIE_X1_GT_LOC[variant]])
        # One global buffer on PIPECLK, as on USERCLK, or the hard block's Max Skew check fails. The PHY's
        # clocking is the same whichever core sits behind it.
        feed_pclk_mux_from_mmcm(self.pcie_phy)

        self.pcie_endpoint = LitePCIeEndpoint(
            self.pcie_phy,
            max_pending_requests=4,
        )

        self.pcie_bridge = LitePCIeWishboneBridge(
            self.pcie_endpoint,
            base_address=self.bus.regions["main_ram"].origin,
        )
        self.bus.add_master(master=self.pcie_bridge.wishbone)

        self.pcie_msi = LitePCIeMSI(width=1)
        self.comb += self.pcie_msi.irqs.eq(0)
        self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)

        # PCIe clock constraints
        if toolchain == "vivado":
            # The PHY's clocks come out of its MMCM, fed by the GTP's TXOUTCLK, and Vivado derives them;
            # a create_clock on the BUFG output would replace the generated clock with a new primary one
            # and lose the MMCM's insertion delay (4.3 ns of USERCLK/USERCLK2 skew in the hard block).
            # sys and pcie meet only in the PHY's AsyncFIFOs and MultiRegs. Said after link: at synthesis
            # the PCIe clocks don't exist yet (the IP is a black box, or TXOUTCLK is not yet declared).
            platform.toolchain.pre_placement_commands.append(
                "set_clock_groups -asynchronous"
                " -group [get_clocks -include_generated_clocks {{clk50}}]"
                " -group [get_clocks -include_generated_clocks -of_objects " + _TXOUTCLK + "]"
            )
        else:
            # nextpnr has no clocks to derive through the GTP: give the pcie domain its period.
            platform.add_period_constraint(
                self.pcie_phy.cd_pcie.clk,
                1e9 / 62.5e6,
            )


# Build --------------------------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PCIe Enumeration Test SoC for NeTV2",
    )
    parser.add_argument(
        "--variant",
        default="a7-35",
        choices=["a7-35", "a7-100"],
        help="NeTV2 FPGA variant: a7-35 (developer) or a7-100 (production)",
    )
    parser.add_argument(
        "--toolchain",
        default="openxc7",
        choices=["openxc7", "yosys+nextpnr", "vivado"],
        help="Synthesis + P&R toolchain. See Phase 3 of the plan.",
    )
    parser.add_argument(
        "--synth-mode",
        default=None,
        choices=["vivado", "yosys"],
        help="Vivado synthesis mode (only honoured with --toolchain=vivado; "
             "default vivado. Use 'yosys' for the Yosys→Vivado hybrid flow).",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build bitstream",
    )
    args = parser.parse_args()

    # Flows that run Yosys for synthesis inject the open-source pcie_7x
    # Verilog sources; pure Vivado uses its proprietary pcie_7x IP from
    # the catalog instead.
    uses_opensource_pcie = (
        args.toolchain in ("openxc7", "yosys+nextpnr")
        or (args.toolchain == "vivado" and args.synth_mode == "yosys")
    )

    soc = PCIeEnumerationSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        uses_opensource_pcie=uses_opensource_pcie,
    )

    if args.toolchain in ("openxc7", "yosys+nextpnr"):
        ensure_chipdb_symlink(soc.platform)
    # patch_yosys_template is a no-op on pure Vivado (no _yosys_template
    # attr); safe to call unconditionally since Phase 3a.
    patch_yosys_template(soc)
    # The openXC7 image's Yosys (0.62) maps the 8 KiB L2 cache's data memory to 256 RAM256X1S, which its
    # nextpnr-xilinx cannot pack (#30); -nodram puts it in block RAM, as for ddr-memory and ethernet-test on
    # this board. The Vivado flows never pass _synth_opts to Yosys, so it changes only openxc7.
    apply_nodram_workaround(soc)

    board_name = board_dir("netv2", args.variant) + flow_suffix(args.toolchain, args.synth_mode)
    builder = Builder(soc, output_dir=default_build_dir(__file__, board_name))

    if args.toolchain == "vivado":
        builder.build(run=args.build, synth_mode=args.synth_mode or "vivado")
        if args.build:
            check_build(builder.gateware_dir, soc.platform.name)
    else:
        builder.build(run=args.build)


if __name__ == "__main__":
    main()
