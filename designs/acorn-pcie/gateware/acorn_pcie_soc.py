#!/usr/bin/env python3
"""The fpgas.online Acorn SoC: one image carrying everything a host needs to test and update the card.

Design and rationale: docs/plans/2026-09-03-acorn-pcie-design.md (§3.2, amended in §9).

Reachable two ways, with the same CSRs behind both:

- **PCIe** Gen2 x1, BAR0 -> Wishbone (`litex_server --pcie`), plus one DMA channel.
- **UARTBone** on the P2 serial pins, K2 (FPGA TX) / J2 (FPGA RX). The link comes
  out of reset at 1200 baud; the host writes `uartbone_phy_tuning_word` to move
  it to 921600, and a UART break (J2 low for 50 ms) puts it back. A command has
  1 s to complete, not LiteX's usual 100 ms, so multi-word transfers work at 1200.

The BIOS console is on the crossover UART, so `litex_term crossover` works
through either bridge.

`--golden` builds the recovery image for flash offset 0x0: same PCIe, flash,
ICAP, DNA/XADC, CPU and UART, but no DDR3 and no P2 GPIO, so there is nothing
in it that can fail calibration. Both images pin the shared CSRs to the same
addresses (`csr_map`) so one kernel driver and one set of host tools serve both.

Build:
    uv run --extra build python designs/acorn-pcie/gateware/acorn_pcie_soc.py \\
        --variant cle-215+ --build --driver

Variants:
    cle-215+ : Acorn CLE-215+        (XC7A200T-3, 1 GiB)   Welland
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2, 1 GiB)
    cle-101  : Acorn CLE-101 / LiteFury (XC7A100T-2, 512 MiB) PS1
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from litedram.modules import MT41K256M16, MT41K512M16
from litedram.phy import s7ddrphy
from litepcie.phy.s7pciephy import S7PCIEPHY
from litepcie.software import generate_litepcie_software
from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.gen import *
from litex.soc.cores.clock import S7IDELAYCTRL, S7PLL
from litex.soc.cores.dna import DNA
from litex.soc.cores.gpio import GPIOOut, GPIOTristate
from litex.soc.cores.icap import ICAP
from litex.soc.cores.led import LedChaser
from litex.soc.cores.spi_flash import S7SPIFlash
from litex.soc.cores.uart import RS232PHY, UARTBone
from litex.soc.cores.xadc import XADC
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex_boards.platforms import sqrl_acorn
from migen import *

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import default_build_dir
from designs._shared.uart_break import UARTBreakDetector

UART_RESET_BAUD = 1200
UART_FAST_BAUD = 921600
UART_BREAK_S = 0.05
# Stream2Wishbone abandons a command that has not finished within 100 ms of its
# first byte. At 1200 baud a one-word read takes 75 ms and a two-word read 108 ms,
# so the stock timeout would limit the slow link to gap-free single-word
# transfers and leave a bit-banged host no slack. 1 s covers a 29-word read.
UARTBONE_TIMEOUT_S = 1.0

_extension_io = [
    # The Pi 5 HAT and the Compute Blade both give the card a single Gen2 lane (lane 0).
    (
        "pcie_x1",
        0,
        Subsignal("rst_n", Pins("J1"), IOStandard("LVCMOS33"), Misc("PULLUP=TRUE")),
        Subsignal("clk_p", Pins("F6")),
        Subsignal("clk_n", Pins("E6")),
        Subsignal("rx_p", Pins("B10")),
        Subsignal("rx_n", Pins("A10")),
        Subsignal("tx_p", Pins("B6")),
        Subsignal("tx_n", Pins("A6")),
    ),
    # P2 spare GPIOs: bit 0 = J5 -> Pi GPIO3, bit 1 = H5 -> Pi GPIO4.
    ("p2_gpio", 0, Pins("J5 H5"), IOStandard("LVCMOS33")),
]

# DDR3 fitted per variant.
_DDR3_MODULE = {
    "cle-215+": MT41K512M16,
    "cle-215": MT41K512M16,
    "cle-101": MT41K256M16,
}


def tuning_word(baudrate, clk_freq):
    """The RS232PHY phase-accumulator increment for `baudrate` (same formula as litex.soc.cores.uart)."""
    return int((baudrate / clk_freq) * 2**32)


# CRG ----------------------------------------------------------------------------------------------


class _CRG(LiteXModule):
    """Same clocking as litex_boards.targets.sqrl_acorn: the known-good PLL + IDELAYCTRL setup for DDR3 here."""

    def __init__(self, platform, sys_clk_freq, with_ddr):
        self.rst = Signal()
        self.cd_sys = ClockDomain("sys")
        if with_ddr:
            self.cd_sys4x = ClockDomain("sys4x")
            self.cd_sys4x_dqs = ClockDomain("sys4x_dqs")
            self.cd_idelay = ClockDomain("idelay")

        clk200 = platform.request("clk200")

        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        if with_ddr:
            pll.create_clkout(self.cd_sys4x, 4 * sys_clk_freq)
            pll.create_clkout(self.cd_sys4x_dqs, 4 * sys_clk_freq, phase=90)
            pll.create_clkout(self.cd_idelay, 200e6)
            self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


# SoC ----------------------------------------------------------------------------------------------


class AcornPCIeSoC(SoCCore):
    # Shared by the operational and golden images, so their CSR addresses must not
    # move when modules are dropped. LiteX otherwise allocates in sorted-name order.
    csr_map = {  # noqa: RUF012  -- SoCCore reads this class attribute in __init__
        "ctrl": 0,
        "identifier_mem": 1,
        "uart": 2,
        "uartbone": 3,
        "timer0": 4,
        "dna": 5,
        "xadc": 6,
        "flash": 7,
        "flash_cs_n": 8,
        "icap": 9,
        "pcie_phy": 10,
        "pcie_msi": 11,
        "pcie_dma0": 12,
        "pcie_endpoint": 13,
        "leds": 14,
    }

    def __init__(self, variant="cle-215+", toolchain="vivado", sys_clk_freq=100e6, golden=False, **kwargs):
        platform = sqrl_acorn.Platform(variant=variant, toolchain=toolchain)
        platform.add_extension(_extension_io)
        with_ddr = not golden

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq, with_ddr=with_ddr)

        # SoCCore ----------------------------------------------------------------------------------
        kwargs["uart_name"] = "crossover"  # the BIOS console; reachable through either bridge
        kwargs["integrated_main_ram_size"] = 0
        kwargs.setdefault("integrated_rom_size", 0x20000)  # the parser's default; needed when built from Python
        SoCCore.__init__(
            self,
            platform,
            int(sys_clk_freq),
            ident=f"fpgas-online Acorn PCIe SoC {variant}{' golden' if golden else ''}",
            ident_version=True,
            **kwargs,
        )
        self.add_constant("UART_RESET_BAUD", UART_RESET_BAUD)
        self.add_constant("UART_FAST_BAUD", UART_FAST_BAUD)
        self.add_constant("UART_FAST_TUNING_WORD", tuning_word(UART_FAST_BAUD, sys_clk_freq))
        self.add_constant("UARTBONE_TIMEOUT_MS", int(UARTBONE_TIMEOUT_S * 1000))

        # UARTBone on P2 (K2/J2) -------------------------------------------------------------------
        # Built by hand rather than with uart_name="crossover+uartbone" for the longer
        # command timeout: Stream2Wishbone sizes its only timer as 100e-3 * clk_freq.
        serial = platform.request("serial")
        self.uartbone = UARTBone(
            phy=RS232PHY(serial, sys_clk_freq, UART_RESET_BAUD, with_dynamic_baudrate=True),
            clk_freq=sys_clk_freq * UARTBONE_TIMEOUT_S / 100e-3,
            address_width=self.bus.address_width,
        )
        self.bus.add_master(name="uartbone", master=self.uartbone.wishbone)

        # UART break -> back to the reset baud rate ------------------------------------------------
        self.uart_break = UARTBreakDetector(sys_clk_freq, break_s=UART_BREAK_S)
        self.comb += self.uart_break.rx.eq(serial.rx)
        self.sync += If(
            self.uart_break.detected,
            self.uartbone.phy._tuning_word.storage.eq(tuning_word(UART_RESET_BAUD, sys_clk_freq)),
        )

        # XADC + DNA (R1) --------------------------------------------------------------------------
        self.xadc = XADC()
        self.dna = DNA()
        self.dna.add_timing_constraints(platform, sys_clk_freq, self.crg.cd_sys.clk)

        # DDR3 (R5a) -------------------------------------------------------------------------------
        if with_ddr:
            self.ddrphy = s7ddrphy.A7DDRPHY(
                platform.request("ddram"),
                memtype="DDR3",
                nphases=4,
                sys_clk_freq=sys_clk_freq,
                iodelay_clk_freq=200e6,
            )
            self.add_sdram(
                "sdram",
                phy=self.ddrphy,
                module=_DDR3_MODULE[variant](sys_clk_freq, "1:4"),
                l2_cache_size=8192,
            )

        # PCIe Gen2 x1 -----------------------------------------------------------------------------
        self.comb += platform.request("pcie_clkreq_n").eq(0)
        self.pcie_phy = S7PCIEPHY(platform, platform.request("pcie_x1"), data_width=64, bar0_size=0x20000)
        # address_width=64: the BCM2712 root complex maps host RAM above 4 GiB on the
        # bus and litepcie.ko sets its DMA mask from this at probe.
        self.add_pcie(phy=self.pcie_phy, ndmas=1, address_width=64, with_dma_loopback=True)
        platform.add_period_constraint(self.crg.cd_sys.clk, 1e9 / sys_clk_freq)
        if toolchain == "vivado":
            # add_pcie() already declares sys and pcie asynchronous, but LiteX's XDC is read at
            # synthesis, when the Xilinx PCIe IP is a black box with no clocks in it: the command
            # matches nothing ([Vivado 12-4739]) and is never retried, so every CDC path gets timed
            # and the placer chases ~80 false failures. Say it again once the IP is linked, and
            # cover all the PHY's MMCM outputs (clk125/clk250/userclk), not only the pcie domain.
            platform.toolchain.pre_placement_commands.append(
                "set_clock_groups -asynchronous"
                " -group [get_clocks -include_generated_clocks {{clk200_p sys_clk}}]"
                " -group [get_clocks -include_generated_clocks -of_objects"
                " [get_pins -hierarchical -filter {{NAME =~ *gtpe2_channel_i/TXOUTCLK}}]]"
            )

        # Flash + ICAP: gateware update over PCIe (R2) ---------------------------------------------
        self.icap = ICAP()
        self.icap.add_reload()
        self.icap.add_timing_constraints(platform, sys_clk_freq, self.crg.cd_sys.clk)
        self.flash_cs_n = GPIOOut(platform.request("flash_cs_n"))
        self.flash = S7SPIFlash(platform.request("flash"), sys_clk_freq, 25e6)

        # P2 spare GPIOs (R3): inputs out of reset, so they never fight the Pi or JTAG -------------
        if not golden:
            self.p2_gpio = GPIOTristate(platform.request("p2_gpio"))

        # LEDs: visible "the design is alive" on the camera feed -----------------------------------
        self.leds = LedChaser(pads=platform.request_all("user_led"), sys_clk_freq=sys_clk_freq)


# Build --------------------------------------------------------------------------------------------


def main():
    from litex.build.parser import LiteXArgumentParser

    parser = LiteXArgumentParser(platform=sqrl_acorn.Platform, description="fpgas.online Acorn PCIe SoC")
    parser.add_target_argument(
        "--variant",
        default="cle-215+",
        choices=sorted(_DDR3_MODULE),
        help="Board variant: cle-215+ (Acorn), cle-215 (NiteFury), cle-101 (LiteFury).",
    )
    parser.add_target_argument("--sys-clk-freq", default=100e6, type=float, help="System clock frequency.")
    parser.add_target_argument("--golden", action="store_true", help="Build the minimal recovery image.")
    parser.add_target_argument("--driver", action="store_true", help="Generate the LitePCIe driver and tools.")
    args = parser.parse_args()

    soc_kwargs = parser.soc_argdict
    for owned in ("uart_name", "integrated_main_ram_size", "ident"):
        soc_kwargs.pop(owned, None)
    soc_kwargs.pop("ident_version", None)

    soc = AcornPCIeSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=args.sys_clk_freq,
        golden=args.golden,
        **soc_kwargs,
    )

    builder_kwargs = parser.builder_argdict
    board = f"acorn-{args.variant}{'-golden' if args.golden else ''}"
    builder_kwargs["output_dir"] = default_build_dir(__file__, board)
    builder = Builder(soc, **builder_kwargs)
    builder.build(**parser.toolchain_argdict, run=args.build)

    if args.driver:
        generate_litepcie_software(soc, os.path.join(builder.output_dir, "driver"))


if __name__ == "__main__":
    main()
