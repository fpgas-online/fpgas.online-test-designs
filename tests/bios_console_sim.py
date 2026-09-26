#!/usr/bin/env python3
"""Boot LiteX's BIOS in Verilator with DDR3, the console on the crossover UART, and nobody reading it.

Prints "sim: SDRAM init started", then "sim: SDRAM handed to the controller" when the BIOS finishes
sdram_init(), then finishes. If the BIOS is still stuck after --max-cycles it prints "sim: TIMEOUT".

    uv run python tests/bios_console_sim.py --output-dir tmp/bios-sim            # with the Acorn fix
    uv run python tests/bios_console_sim.py --output-dir tmp/bios-sim --stock    # LiteX as it is

Needs Verilator, libevent and json-c (LiteX's simulator), and a RISC-V toolchain for the BIOS.
"""

import argparse

from litex.build.sim.config import SimConfig
from litex.soc.integration.builder import Builder
from litex.tools.litex_sim import SimSoC
from migen import Display, Finish, If, Signal

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer

SYS_CLK_FREQ = int(1e6)  # SimSoC's clock


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stock", action="store_true", help="no auto TX flush: LiteX's crossover as it is")
    parser.add_argument("--max-cycles", type=int, default=4_000_000)
    args = parser.parse_args()

    soc = SimSoC(
        uart_name="crossover",
        with_sdram=True,
        sdram_module="MT41K128M16",  # DDR3, the Acorn's memory type
        sdram_data_width=16,
        integrated_rom_size=0x20000,
    )
    if not args.stock:
        soc.uart.add_auto_tx_flush(sys_clk_freq=SYS_CLK_FREQ)  # what acorn_pcie_soc.py does

    # The BIOS writes the DFII control register to start sdram_init(), and sets `sel` to hand the DRAM
    # to the controller at its end.
    control = soc.sdram.dfii._control
    cycles = Signal(32)
    started = Signal()
    soc.sync += [
        cycles.eq(cycles + 1),
        If(
            control.re & ~control.fields.sel & ~started,
            started.eq(1),
            Display("sim: SDRAM init started at cycle %d", cycles),
        ),
        If(
            control.re & control.fields.sel,
            Display("sim: SDRAM handed to the controller at cycle %d", cycles),
            Finish(),
        ),
        If(cycles == args.max_cycles, Display("sim: TIMEOUT after %d cycles", cycles), Finish()),
    ]

    sim_config = SimConfig()
    sim_config.add_clocker("sys_clk", freq_hz=SYS_CLK_FREQ)
    builder = Builder(soc, output_dir=args.output_dir)
    builder.build(sim_config=sim_config, interactive=False)


if __name__ == "__main__":
    main()
