# DDR Memory Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify DDR3 DRAM initialization, calibration, and data integrity on Arty A7 and NeTV2 boards by building a LiteX SoC with LiteDRAM and parsing the BIOS memtest output from the host.

**Architecture:** A standard LiteX SoC is built with `--with-sdram` enabled, which includes the LiteDRAM controller and PHY. On boot, the LiteX BIOS automatically runs DRAM calibration (read/write leveling) and a built-in memtest. The host-side Python script captures all UART output during boot, parses it for calibration results and the final "Memtest OK" / "Memtest KO" verdict, and reports pass/fail. This reuses the same SoC architecture as the UART test but adds the SDRAM controller.

**Tech Stack:** LiteX + LiteDRAM (Python SoC builder), openXC7 (Yosys + nextpnr-xilinx), Python 3 with pyserial, uv, GitHub Actions with OpenXC7-LiteX Docker container.

---

### Task 1: Create Directory Structure and Write the LiteX SoC Target for Arty A7 with SDRAM
**Files:**
- Create: `designs/ddr-memory/gateware/ddr_soc_arty.py`

**Step 1: Create the directory structure**
```bash
mkdir -p designs/ddr-memory/gateware
mkdir -p designs/ddr-memory/host
```

**Step 2: Create the Arty A7 DDR test SoC target**
```python
#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SDRAM (LiteDRAM). The BIOS
automatically runs DRAM calibration and memtest on boot. The host
just needs to parse the UART output for "Memtest OK" or "Memtest KO".

Arty A7 DRAM: Micron MT41K128M16JT-125, 256 MB, 16-bit DDR3.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/ddr-memory/build/arty/gateware/arty_ddr_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.digilent_arty import Platform

from litedram.modules import MT41K128M16
from litedram.phy import s7ddrphy


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="DDR Memory Test SoC for Arty A7")
    target_group = parser.add_argument_group(title="Target options")
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--toolchain",     default="yosys+nextpnr", help="FPGA toolchain.")
    target_group.add_argument("--sys-clk-freq",  default=100e6, type=float, help="System clock frequency.")
    builder_args = Builder.add_arguments(parser)
    soc_args = SoCCore.add_arguments(parser)
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = platform,
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online DDR Test SoC — Arty A7",
        ident_version  = True,
        uart_baudrate  = 115200,
        **SoCCore.argdict(args),
    )

    # Add DDR3 SDRAM ----------------------------------------------------------
    soc.submodules.ddrphy = s7ddrphy.A7DDRPHY(
        platform.request("ddram"),
        memtype   = "DDR3",
        nphases   = 4,
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_sdram(
        "sdram",
        phy       = soc.ddrphy,
        module    = MT41K128M16(sys_clk_freq, "1:4"),
        size      = 0x10000000,  # 256 MB
    )

    builder = Builder(soc, output_dir="designs/ddr-memory/build/arty", **Builder.argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
```

**Step 3: Verify the target parses correctly**
```bash
uv run python designs/ddr-memory/gateware/ddr_soc_arty.py --help
```

**Step 4: Commit**
```
Add LiteX DDR memory test SoC target for Arty A7
```

---

### Task 2: Write the Host-Side DDR Memory Test Script
**Files:**
- Create: `designs/ddr-memory/host/test_ddr.py`

**Step 1: Create the test script**
```python
#!/usr/bin/env python3
"""
Host-side DDR memory test script.

Captures UART output from the LiteX BIOS boot sequence and parses for:
  1. DRAM calibration results (read/write leveling)
  2. Memtest verdict ("Memtest OK" or "Memtest KO")

Usage:
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyUSB1
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import re
import sys
import time

import serial


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
BOOT_TIMEOUT_S = 60  # DDR calibration can take a while

# Expected DRAM sizes per board (bytes).
EXPECTED_DRAM_SIZE = {
    "arty":  256 * 1024 * 1024,  # 256 MB
    "netv2": 512 * 1024 * 1024,  # 512 MB
}


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #

def run_ddr_test(ser: serial.Serial, board: str) -> tuple[bool, list[str]]:
    """Capture boot output and parse DDR test results.

    Returns (overall_pass, captured_lines).
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S

    calibration_ok = False
    memtest_ok = None  # None = not seen, True = OK, False = KO
    memtest_line = ""

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        # Track calibration progress.
        if "SDRAM now under software control" in line:
            calibration_ok = True

        # Detect memtest result.
        if "Memtest OK" in line:
            memtest_ok = True
            memtest_line = line
            break
        elif "Memtest KO" in line:
            memtest_ok = False
            memtest_line = line
            break

        # Detect calibration failure.
        if re.search(r"(calibration|leveling).*(fail|error)", line, re.IGNORECASE):
            print(f"FAIL: DRAM calibration failed: {line}")
            return False, lines

        # If we see the BIOS prompt without a memtest result, boot
        # completed but memtest was skipped or not run.
        if "litex>" in line:
            break

    # Report results.
    results: list[bool] = []

    if calibration_ok:
        print("PASS: DRAM calibration completed (SDRAM under software control)")
    else:
        print("FAIL: DRAM calibration not detected")
    results.append(calibration_ok)

    if memtest_ok is True:
        print(f"PASS: {memtest_line}")
    elif memtest_ok is False:
        print(f"FAIL: {memtest_line}")
    else:
        print("FAIL: Memtest result not detected within timeout")
    results.append(memtest_ok is True)

    return all(results), lines


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="DDR memory test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(EXPECTED_DRAM_SIZE.keys()),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=BOOT_TIMEOUT_S,
        help=f"Boot timeout in seconds (default: {BOOT_TIMEOUT_S})",
    )
    args = parser.parse_args()

    global BOOT_TIMEOUT_S
    BOOT_TIMEOUT_S = args.timeout

    print(f"Opening {args.port} at {args.baud} baud...")
    print(f"Board: {args.board}, expected DRAM: "
          f"{EXPECTED_DRAM_SIZE[args.board] // (1024*1024)} MB")
    print(f"Waiting up to {BOOT_TIMEOUT_S}s for boot + memtest...")
    print()

    ser = serial.Serial(args.port, args.baud, timeout=2)

    passed, boot_lines = run_ddr_test(ser, args.board)
    ser.close()

    if not passed:
        print("\nFull boot output:")
        for line in boot_lines:
            print(f"  {line}")

    print()
    if passed:
        print("RESULT: PASS — DDR memory test completed successfully")
        return 0
    else:
        print("RESULT: FAIL — DDR memory test had failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Commit**
```
Add host-side DDR memory test script with BIOS output parser
```

---

### Task 3: Adapt Target for NeTV2
**Files:**
- Create: `designs/ddr-memory/gateware/ddr_soc_netv2.py`

**Step 1: Create the NeTV2 DDR test SoC target**
```python
#!/usr/bin/env python3
"""
LiteX SoC target for DDR memory test on Kosagi NeTV2.

NeTV2 DRAM: 512 MB, 32-bit DDR3 (4 byte lanes).
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/ddr-memory/gateware/ddr_soc_netv2.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/ddr-memory/build/netv2/gateware/netv2_ddr_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_netv2 import Platform

from litedram.modules import MT41K256M16
from litedram.phy import s7ddrphy


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="DDR Memory Test SoC for NeTV2")
    target_group = parser.add_argument_group(title="Target options")
    target_group.add_argument("--variant",       default="a7-35",     help="Board variant (a7-35 or a7-100).")
    target_group.add_argument("--toolchain",     default="yosys+nextpnr", help="FPGA toolchain.")
    target_group.add_argument("--sys-clk-freq",  default=50e6, type=float, help="System clock frequency.")
    builder_args = Builder.add_arguments(parser)
    soc_args = SoCCore.add_arguments(parser)
    args = parser.parse_args()

    platform = Platform(variant=args.variant, toolchain=args.toolchain)
    sys_clk_freq = int(args.sys_clk_freq)

    soc = SoCCore(
        platform       = platform,
        sys_clk_freq   = sys_clk_freq,
        ident          = "fpgas-online DDR Test SoC — NeTV2",
        ident_version  = True,
        uart_baudrate  = 115200,
        **SoCCore.argdict(args),
    )

    # Add DDR3 SDRAM ----------------------------------------------------------
    # NeTV2 has 32-bit wide DDR3 (4 byte lanes, 512 MB total).
    soc.submodules.ddrphy = s7ddrphy.A7DDRPHY(
        platform.request("ddram"),
        memtype   = "DDR3",
        nphases   = 4,
        sys_clk_freq = sys_clk_freq,
    )
    soc.add_sdram(
        "sdram",
        phy       = soc.ddrphy,
        module    = MT41K256M16(sys_clk_freq, "1:4"),
        size      = 0x20000000,  # 512 MB
    )

    builder = Builder(soc, output_dir="designs/ddr-memory/build/netv2", **Builder.argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```
Add LiteX DDR memory test SoC target for NeTV2
```

---

### Task 4: Write GitHub Actions Workflow
**Files:**
- Create: `.github/workflows/build-ddr-test.yml`

**Step 1: Create the CI workflow**
```yaml
name: Build DDR Memory Test Bitstreams

on:
  push:
    branches: [main]
    paths:
      - 'designs/ddr-memory/gateware/ddr_soc_*.py'
      - '.github/workflows/build-ddr-test.yml'
  pull_request:
    paths:
      - 'designs/ddr-memory/gateware/ddr_soc_*.py'
      - '.github/workflows/build-ddr-test.yml'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/meriac/openxc7-litex:latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - board: arty
            target: designs/ddr-memory/gateware/ddr_soc_arty.py
            output_dir: designs/ddr-memory/build/arty
          - board: netv2
            target: designs/ddr-memory/gateware/ddr_soc_netv2.py
            output_dir: designs/ddr-memory/build/netv2

    steps:
      - uses: actions/checkout@v4

      - name: Build ${{ matrix.board }} DDR test bitstream
        run: |
          python3 ${{ matrix.target }} \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream artifact
        uses: actions/upload-artifact@v4
        with:
          name: ddr-test-${{ matrix.board }}
          path: |
            ${{ matrix.output_dir }}/gateware/*.bit
            ${{ matrix.output_dir }}/gateware/*.bin
          if-no-files-found: error
```

**Step 2: Commit**
```
Add GitHub Actions workflow to build DDR memory test bitstreams
```

---

### Task 5: Add Makefile for DDR Test
**Files:**
- Create: `designs/ddr-memory/Makefile`

**Step 1: Create the DDR test Makefile**

```makefile
# --------------------------------------------------------------------------- #
# DDR Memory Test
# --------------------------------------------------------------------------- #

PYTHON ?= uv run python

.PHONY: build-arty build-netv2 build-all

build-arty:
	$(PYTHON) gateware/ddr_soc_arty.py --toolchain yosys+nextpnr --build

build-netv2:
	$(PYTHON) gateware/ddr_soc_netv2.py --toolchain yosys+nextpnr --build

build-all: build-arty build-netv2

# --------------------------------------------------------------------------- #
# DDR Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: test-ddr-arty test-ddr-netv2

test-ddr-arty:
	$(PYTHON) host/test_ddr.py --port /dev/ttyUSB1 --board arty

test-ddr-netv2:
	$(PYTHON) host/test_ddr.py --port /dev/ttyAMA0 --board netv2

# --------------------------------------------------------------------------- #
# DDR Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: program-ddr-arty program-ddr-netv2

program-ddr-arty:
	openFPGALoader -b arty build/arty/gateware/arty_ddr_test.bit

program-ddr-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_ddr_test.bit; exit"
```

**Step 2: Commit**
```
Add DDR memory test Makefile
```
