#!/usr/bin/env python3
"""LiteX SoC with LitePCIe endpoint for Acorn/LiteFury PCIe enumeration testing.

Builds a SoC with CPU + BIOS + UART + PCIe Gen2 x1 endpoint targeting
the Acorn CLE-215+ / CLE-215 / LiteFury board family. Three toolchain
flows are supported (see Phase 3 of the plan for the rationale):

    Pure Vivado (proprietary):
        --toolchain vivado --synth-mode vivado
        Uses Vivado's proprietary pcie_7x IP from the Xilinx catalog.
    Yosys→Vivado (hybrid — open-source synth, proprietary P&R):
        --toolchain vivado --synth-mode yosys
        Uses the open-source pcie_7x core (github.com/regymm/pcie_7x).
    Yosys→nextpnr (fully open-source):
        --toolchain openxc7
        Uses the open-source pcie_7x core.

The host (RPi5 via mPCIe HAT) provides a single PCIe Gen2 x1 lane.
After programming the FPGA (SRAM only!) and triggering a bus rescan,
the host should see the FPGA as a PCIe device (10ee:7022).

SAFETY: The Acorn has NO JTAG or UART directly connected.  The flash
contains a factory bitstream that enables PCIe programming.  NEVER use
--write-flash — only volatile SRAM loads.

Build command:
    uv run python designs/pcie-enumeration/gateware/pcie_soc_acorn.py \\
        --toolchain <openxc7|vivado> [--synth-mode <vivado|yosys>] --build

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)
"""

import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
from litepcie.frontend.wishbone import LitePCIeWishboneBridge
from litepcie.phy.s7pciephy import S7PCIEPHY
from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.gen import *
from litex.soc.cores.clock import S7PLL
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import sqrl_acorn
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, default_build_dir, flow_suffix
from designs._shared.pin_check import check_build
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.s7pcie_clocking import feed_pclk_mux_from_mmcm
from designs._shared.yosys_workarounds import patch_yosys_template

# Path to the open-source pcie_7x Verilog sources (git submodule).
PCIE_7X_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pcie_7x", "src")

# GTP channel behind the pcie_x1 pins (B10/A10, B6/A6, M.2 lane 0), from Vivado's package-pin map: the
# same on all three variants' parts. RHS Research's LiteFury constraints give the same mapping.
PCIE_X1_GT_LOC = {"cle-101": "GTPE2_CHANNEL_X0Y6", "cle-215": "GTPE2_CHANNEL_X0Y6", "cle-215+": "GTPE2_CHANNEL_X0Y6"}

# PCIe x1 resource — uses lane 0 from the Acorn's x4 edge connector.
# The RPi 5 mPCIe HAT provides a single Gen2 x1 lane.
_pcie_x1_io = [
    ("pcie_x1", 0,
        Subsignal("rst_n", Pins("J1"), IOStandard("LVCMOS33"), Misc("PULLUP=TRUE")),
        Subsignal("clk_p", Pins("F6")),
        Subsignal("clk_n", Pins("E6")),
        Subsignal("rx_p", Pins("B10")),
        Subsignal("rx_n", Pins("A10")),
        Subsignal("tx_p", Pins("B6")),
        Subsignal("tx_n", Pins("A6")),
    ),
]


# The GTP's TXOUTCLK pin, which every PCIe clock derives from (Tcl, braces doubled for LiteX's format()).
_TXOUTCLK = (
    "[get_pins -of_objects [get_cells -hierarchical -filter {{REF_NAME == GTPE2_CHANNEL}}]"
    " -filter {{REF_PIN_NAME == TXOUTCLK}}]"
)

# CRG (Clock Reset Generator) ---------------------------------------------------------------------


class _CRG(LiteXModule):
    """Minimal CRG for Acorn: generates sys clock from the 200 MHz on-board oscillator."""

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")

        # Clk.
        clk200 = platform.request("clk200")

        # PLL.
        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# SoC ----------------------------------------------------------------------------------------------


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="cle-215+", toolchain="openxc7",
                 uses_opensource_pcie=True, sys_clk_freq=100e6, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)

        if toolchain in ("openxc7", "yosys+nextpnr"):
            fix_openxc7_device_name(platform)
            # S7PCIEPHY.add_sources() appends Vivado-specific TCL commands to
            # these toolchain attributes.  The openxc7 (yosys+nextpnr) toolchain
            # doesn't have them, so provide empty lists — the TCL is silently
            # dropped and the PCIe hard IP is handled by pcie_7x Verilog sources.
            for attr in ("pre_synthesis_commands", "pre_placement_commands"):
                if not hasattr(platform.toolchain, attr):
                    setattr(platform.toolchain, attr, [])

        # Add PCIe x1 resource (lane 0 from the x4 connector).
        platform.add_extension(_pcie_x1_io)

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

        # Assert CLKREQ# to keep PCIe reference clock active.
        self.comb += platform.request("pcie_clkreq_n").eq(0)

        # CRG ----------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq)

        # SoCCore ------------------------------------------------------------------------------
        SoCCore.__init__(
            self,
            platform,
            clk_freq=int(sys_clk_freq),
            ident="PCIe Enumeration Test SoC (Acorn/LiteFury)",
            ident_version=True,
            uart_baudrate=115200,
            integrated_rom_size=0x10000,  # 64 KB BIOS ROM
            integrated_main_ram_size=0x10000,  # 64 KB SRAM
            **kwargs,
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
                " -group [get_clocks -include_generated_clocks {{clk200_p}}]"
                " -group [get_clocks -include_generated_clocks -of_objects " + _TXOUTCLK + "]"
            )
        else:
            # nextpnr has no clocks to derive through the GTP: give the pcie domain its period.
            platform.add_period_constraint(
                self.pcie_phy.cd_pcie.clk,
                1e9 / 125e6,  # Gen2 reference clock
            )


# Build --------------------------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PCIe Enumeration Test SoC for Acorn/LiteFury")
    parser.add_argument(
        "--variant",
        default="cle-215+",
        choices=["cle-215+", "cle-215", "cle-101"],
        help="Board variant: cle-215+ (Acorn), cle-215 (NiteFury), cle-101 (LiteFury).",
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
    parser.add_argument("--build", action="store_true", help="Build bitstream")
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

    # Variant in the path so cle-215+, cle-215, cle-101 don't clobber.
    board_name = board_dir("acorn", args.variant) + flow_suffix(args.toolchain, args.synth_mode)
    builder = Builder(soc, output_dir=default_build_dir(__file__, board_name))

    if args.toolchain == "vivado":
        # The open core's RXVALID -> rxvalid_cnt reset path at 250 MHz has one LUT but a long route out of the
        # GTP; default placement closed it on one run and missed by 0.244 ns on the next (Acorn CLE-215+,
        # yosys-vivado). ExtraTimingOpt placed the same netlist at +0.341 ns.
        builder.build(
            run=args.build,
            synth_mode=args.synth_mode or "vivado",
            vivado_place_directive="ExtraTimingOpt",
        )
        if args.build:
            check_build(builder.gateware_dir, soc.platform.name)
    else:
        builder.build(run=args.build)


if __name__ == "__main__":
    main()
