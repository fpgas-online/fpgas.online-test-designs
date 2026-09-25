#!/usr/bin/env python3
"""GPIO pin identification design for Sqrl Acorn CLE-215+ / NiteFury / LiteFury.

Each of the 4 P2 header pins continuously transmits its FPGA pin name
(e.g. "K2\\r\\n") as 1200-baud 8N1 UART. Connect any RPi GPIO to
any header pin and decode the name to verify the wiring.

P2 header pins:
    K2  = Serial TX
    J2  = Serial RX
    J5  = Spare GPIO 0 (SD card MOSI)
    H5  = Spare GPIO 1 (SD card CS_N)

JTAG pins (P1) are FPGA configuration pins and cannot be used as
regular GPIO in user designs.

Variants:
    cle-215+ : Acorn CLE-215+ (XC7A200T-3)
    cle-215  : Acorn CLE-215 / NiteFury (XC7A200T-2)
    cle-101  : LiteFury (XC7A100T-2)

No CPU, no firmware. Pure gateware.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from litex.build.generic_platform import IOStandard, Pins
from litex.gen import LiteXModule
from litex.soc.cores.clock import S7PLL
from litex_boards.platforms.sqrl_acorn import Platform
from migen import *
from pmod_pin_id import UARTTxIdentifier

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.build_helpers import board_dir, flow_suffix
from designs._shared.platform_fixups import ensure_chipdb_symlink, fix_openxc7_device_name
from designs._shared.yosys_workarounds import YOSYS_TEMPLATE_STRIP_SCOPEINFO

# P2 header pins and their FPGA ball names.
# These are the 4 user-accessible I/O pins on the Acorn's Pico-EZmate P2 connector.
P2_PINS = [
    ("K2", "serial:tx"),   # Serial TX
    ("J2", "serial:rx"),   # Serial RX
    ("J5", "spisdcard:mosi"),  # Spare GPIO 0
    ("H5", "spisdcard:cs_n"),  # Spare GPIO 1
]

BAUD_RATE = 1200
# Driven by the PLL in _CRG below, not by the raw oscillator. The Acorn's 200 MHz
# input is a differential pair and cannot be used directly as a clock -- see _CRG.
SYS_CLK_FREQ = 100e6

# Define each pin as a standalone output for the identifier.
_pin_id_io = [
    ("pin_id_0", 0, Pins("K2"), IOStandard("LVCMOS33")),
    ("pin_id_1", 0, Pins("J2"), IOStandard("LVCMOS33")),
    ("pin_id_2", 0, Pins("J5"), IOStandard("LVCMOS33")),
    ("pin_id_3", 0, Pins("H5"), IOStandard("LVCMOS33")),
]


class _CRG(LiteXModule):
    """Clock/reset generator — mirrors designs/uart/gateware/uart_soc_acorn.py.

    This design previously had no CRG at all, relying on migen's implicit
    default-clock wiring. That does not work on this board: the platform's
    `default_clk_name` is `clk200`, which the Acorn brings out as a DIFFERENTIAL
    pair (J19/H19, DIFF_SSTL15). The implicit path cannot turn that Record into a
    usable single-ended `sys` clock, so `UARTTxIdentifier`'s `self.sync` logic had
    no clock: the bitstream built and configured cleanly, and then every pin sat
    idle forever. On real hardware (Acorn CLE-215+ on a Pi 5, 2026-08-31) all four
    P2 pins measured silent, which was misread as "the P2 cable is not connected"
    until the clocked UART SoC proved the wiring was fine.

    Feeding the pair through the PLL fixes it: S7PLL.register_clkin() instantiates
    the differential input buffer for a p/n Record, and `sys` is driven from its
    output.
    """

    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain()

        clk200 = platform.request("clk200")

        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


class AcornPinIdentifier(Module):
    def __init__(self, platform, sys_clk_freq=SYS_CLK_FREQ):
        self.submodules.crg = _CRG(platform, sys_clk_freq)
        for i, (fpga_pin, _resource) in enumerate(P2_PINS):
            pin = platform.request(f"pin_id_{i}")
            label = f"{fpga_pin}\r\n"
            tx = UARTTxIdentifier(pin, label, int(sys_clk_freq), baud=BAUD_RATE)
            self.submodules += tx


def main():
    import argparse

    parser = argparse.ArgumentParser(description="GPIO Pin Identification for Acorn/LiteFury")
    parser.add_argument("--variant", default="cle-215+", choices=["cle-215+", "cle-215", "cle-101"])
    parser.add_argument("--toolchain", default="openxc7", choices=["openxc7", "vivado"])
    parser.add_argument("--synth-mode", default=None, choices=["vivado", "yosys"],
                        help="Vivado synthesis mode (only honoured with "
                             "--toolchain=vivado; default vivado. Use 'yosys' "
                             "for the Yosys→Vivado hybrid flow).")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)

    # Remove the default serial and sdcard extensions so our pin_id_io can claim the pins.
    # The Platform.__init__ auto-adds _serial_io and _sdcard_io which would conflict.
    # We need to create a fresh platform without those extensions.
    # Workaround: just add our IO — LiteX will error if pins conflict, so we skip
    # requesting "serial" or "spisdcard" and use direct pin assignments instead.
    platform.add_extension(_pin_id_io)

    if args.toolchain == "openxc7":
        fix_openxc7_device_name(platform)
        ensure_chipdb_symlink(platform)

    print(f"Pin ID: {len(P2_PINS)} pins")
    for fpga_pin, resource in P2_PINS:
        print(f"  {resource:20s} -> {fpga_pin!r}")

    module = AcornPinIdentifier(platform)

    if args.toolchain == "openxc7" and hasattr(platform.toolchain, "_yosys_template"):
        platform.toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)

    if args.build:
        # Write to build/<board>-<variant>-<flow>/gateware/<platform>.bit
        # to match LiteX Builder's layout used by the other designs.
        build_dir = str(
            Path(__file__).resolve().parent.parent
            / "build"
            / f"{board_dir('acorn', args.variant)}{flow_suffix(args.toolchain, args.synth_mode)}"
            / "gateware"
        )
        build_kwargs = {"build_dir": build_dir, "build_name": platform.name}
        if args.toolchain == "vivado":
            build_kwargs["synth_mode"] = args.synth_mode or "vivado"
        platform.build(module, **build_kwargs)


if __name__ == "__main__":
    main()
