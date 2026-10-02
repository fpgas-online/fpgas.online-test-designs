"""The BIOS, simulated in Verilator with nobody reading its crossover console, must get through SDRAM init.

The control run leaves LiteX's crossover as it is and must still be stuck when the time runs out: that is
what pi-sw2-p48 did after every load (2026-09-26), and it shows the simulation can see the bug. Each run
builds a Verilator model and the BIOS, about a minute each. Skipped without Verilator or a RISC-V gcc.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("litex")
if shutil.which("verilator") is None:
    pytest.skip("Verilator is not on PATH", allow_module_level=True)
if not any(shutil.which(f"riscv64-{abi}-gcc") for abi in ("unknown-elf", "linux-gnu", "elf", "unknown-linux-gnu")):
    pytest.skip("no RISC-V gcc for the BIOS", allow_module_level=True)

REPO = pathlib.Path(__file__).resolve().parents[1]


def _boot(tmp_path, *extra):
    result = subprocess.run(
        [sys.executable, str(REPO / "tests" / "bios_console_sim.py"), "--output-dir", str(tmp_path), *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=1200,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    return [line for line in result.stdout.splitlines() if line.startswith("sim:")]


def test_the_bios_gets_through_sdram_init_with_nobody_reading_the_console(tmp_path):
    lines = _boot(tmp_path)
    assert any(line.startswith("sim: SDRAM init started") for line in lines), lines
    assert any(line.startswith("sim: SDRAM handed to the controller") for line in lines), lines
    assert not any("TIMEOUT" in line for line in lines), lines


def test_control_stock_litex_never_reaches_sdram_init(tmp_path):
    lines = _boot(tmp_path, "--stock")
    assert any("TIMEOUT" in line for line in lines), lines
    assert not any(line.startswith("sim: SDRAM init started") for line in lines), lines
