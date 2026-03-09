#!/usr/bin/env python3
# designs/pmod-loopback/gateware/pmod_loopback_soc.py
"""LiteX SoC with tristate GPIO cores for PMOD loopback testing on Arty A7.

Each PMOD port (A-D) gets a GPIOTristate peripheral with three CSR registers:
  - pmod{x}_oe  (CSRStorage, 8-bit): output enable (1 = output, 0 = input)
  - pmod{x}_out (CSRStorage, 8-bit): output value (driven when oe=1)
  - pmod{x}_in  (CSRStatus,  8-bit): input value (active when oe=0)

The firmware sets direction via oe, then reads/writes via in/out registers.
"""

import argparse

from migen import *

from litex.soc.cores.gpio import GPIOTristate
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import digilent_arty


class PmodLoopbackSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="yosys+nextpnr", **kwargs):
        platform = digilent_arty.Platform(variant=variant, toolchain=toolchain)

        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq=100e6,
            ident="PMOD Loopback Test SoC",
            ident_version=True,
            uart_baudrate=115200,
            **kwargs,
        )

        # Add a GPIOTristate for each PMOD connector.
        # The Arty platform defines connectors "pmoda" through "pmodd",
        # each with 8 data pins.
        for port_name in ["pmoda", "pmodb", "pmodc", "pmodd"]:
            pads = platform.request(port_name)
            gpio = GPIOTristate(pads)
            self.add_module(name=port_name, module=gpio)
            self.add_csr(port_name)


def main():
    parser = argparse.ArgumentParser(description="PMOD Loopback SoC for Arty A7")
    parser.add_argument("--variant",    default="a7-35",          help="Arty variant: a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr",  help="Toolchain: vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",      help="Build the bitstream")
    parser.add_argument("--load",       action="store_true",      help="Load bitstream to FPGA")
    parser.add_argument("--no-compile-gateware", action="store_true")
    args = parser.parse_args()

    soc = PmodLoopbackSoC(variant=args.variant, toolchain=args.toolchain)

    builder = Builder(soc, compile_gateware=not args.no_compile_gateware)
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
