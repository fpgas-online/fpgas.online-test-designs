"""The Acorn BIOS console must not wait for a reader, or DDR3 is never initialised after a boot.

The console is LiteX's crossover UART. Nothing drains it until a host attaches, and with LiteX's defaults the
BIOS blocks in uart_write() once about 160 characters are queued (libbase's 128-byte ring, the UART's
16-deep TX FIFO, the crossover's 16-deep RX FIFO): after the banner, before "Initializing SDRAM". Until
someone read the console, the DRAM bridge returned all zeros (pi-sw2-p48, 2026-09-26). Both images must carry
the flush; test_console_nonblocking.py tests how it behaves, test_bios_console_sim.py the BIOS end to end.
"""

import functools
import importlib.util
import pathlib

import pytest

pytest.importorskip("litex")
pytest.importorskip("litepcie")

from litex.gen.genlib.misc import WaitTimer

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "gateware" / "acorn_pcie_soc.py"
_spec = importlib.util.spec_from_file_location("acorn_pcie_soc", _PATH)
soc_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soc_mod)


@functools.cache
def _soc(variant, golden):
    return soc_mod.AcornPCIeSoC(variant=variant, golden=golden)  # about a minute each, so build each one once


@pytest.mark.parametrize(("variant", "golden"), [("cle-215+", False), ("cle-215+", True)])
def test_the_bios_console_drops_output_instead_of_waiting_for_a_reader(variant, golden):
    # UART.add_auto_tx_flush() is what adds the timer; without it the console can stall the CPU for ever.
    assert isinstance(getattr(_soc(variant, golden).uart, "timer", None), WaitTimer)
