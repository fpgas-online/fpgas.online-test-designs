# SPI Flash ID Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify the FPGA can communicate with its SPI configuration flash by reading and validating the JEDEC manufacturer/device ID via a LiteX SoC with SPI flash access.

**Architecture:** A LiteX SoC is built with SPI flash support (`--with-spi-flash`). The LiteX BIOS already identifies the SPI flash on boot, printing "SPI flash" with the JEDEC ID. However, for a more thorough test, custom firmware reads the JEDEC ID by sending command 0x9F via the SPI CSR registers and prints the 3-byte response over UART. The host-side Python script captures this output, validates that the JEDEC ID is not all-zeros or all-ones (indicating a bus fault), and optionally checks it against known-good values for each board.

**Tech Stack:** LiteX + LiteSPI (Python SoC builder), openXC7 (Yosys + nextpnr-xilinx), C firmware (compiled by LiteX build system), Python 3 with pyserial, uv, GitHub Actions with OpenXC7-LiteX Docker container.

**Branch:** `feature/spi-flash-id-test` (developed in `.worktrees/spi-flash-id-test` worktree)

---

### Task 0: Set Up Worktree and Branch
**Prerequisites:** `.gitignore` must include `.worktrees/` (already configured in main).

**Step 1: Create worktree with feature branch**
```bash
git worktree add .worktrees/spi-flash-id-test -b feature/spi-flash-id-test
cd .worktrees/spi-flash-id-test
```

**Step 2: Verify clean baseline**
```bash
git status
git log --oneline -3
```

> **Note:** All subsequent tasks in this plan are executed inside the `.worktrees/spi-flash-id-test` worktree. File paths are relative to the worktree root.

---

### Task 1: Create Directory Structure and Write LiteX SoC with SPI Flash Access for Arty A7
**Files:**
- Create: `designs/spi-flash-id/gateware/spiflash_soc_arty.py`

**Step 1: Create the directory structure**
```bash
mkdir -p designs/spi-flash-id/gateware
mkdir -p designs/spi-flash-id/firmware
mkdir -p designs/spi-flash-id/host
```

**Step 2: Create the Arty A7 SPI flash test SoC target**
```python
#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Digilent Arty A7.

Builds a SoC with CPU + BIOS + UART + SPI Flash access. The BIOS prints
the SPI flash identification on boot. Additionally, custom firmware can
be loaded to explicitly read the JEDEC ID via command 0x9F.

Arty A7 SPI Flash: Quad SPI, CS=L13.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/spi-flash-id/build/arty/gateware/arty_spiflash_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.digilent_arty import Platform


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="SPI Flash ID Test SoC for Arty A7")
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
        ident          = "fpgas-online SPI Flash Test SoC — Arty A7",
        ident_version  = True,
        uart_baudrate  = 115200,
        **SoCCore.argdict(args),
    )

    # Add SPI Flash with bitbang access for JEDEC ID reading -------------------
    from litex.soc.cores.spi_flash import SpiFlash
    soc.submodules.spiflash = SpiFlash(
        platform.request("spiflash4x"),
        dummy=11,
        div=2,
        endianness="little",
    )
    soc.add_csr("spiflash")

    builder = Builder(soc, output_dir="designs/spi-flash-id/build/arty", **Builder.argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
```

**Step 3: Verify the target parses correctly**
```bash
uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --help
```

**Step 4: Commit**
```
Add LiteX SPI flash test SoC target for Arty A7
```

---

### Task 2: Write Custom Firmware to Read JEDEC ID
**Files:**
- Create: `designs/spi-flash-id/firmware/main.c`
- Create: `designs/spi-flash-id/firmware/Makefile`

**Step 1: Create the firmware C source**
```c
/*
 * SPI Flash JEDEC ID reader firmware for LiteX SoC.
 *
 * Reads the JEDEC ID (command 0x9F) from the SPI flash via CSR bitbang
 * registers and prints the result over UART.
 *
 * Output format:
 *   JEDEC_ID: 0xMM 0xTT 0xCC
 *   MANUFACTURER: 0xMM
 *   DEVICE_TYPE: 0xTT
 *   CAPACITY: 0xCC
 *   SPI_FLASH_TEST: PASS
 *
 * Where MM=manufacturer, TT=device type, CC=capacity.
 * If the ID is 0x000000 or 0xFFFFFF, it prints SPI_FLASH_TEST: FAIL.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <generated/csr.h>
#include <generated/mem.h>
#include <irq.h>
#include <uart.h>

/* SPI bitbang helpers */
#define SPI_CS_HIGH  (0 << 0)
#define SPI_CS_LOW   (1 << 0)
#define SPI_CLK_LOW  (0 << 1)
#define SPI_CLK_HIGH (1 << 1)
#define SPI_MOSI_LOW (0 << 2)
#define SPI_MOSI_HIGH (1 << 2)

static void spi_set(unsigned int val) {
    spiflash_bitbang_write(val);
}

static unsigned int spi_get_miso(void) {
    return (spiflash_bitbang_read() >> 1) & 1;
}

static void spi_cs_active(void) {
    spi_set(SPI_CS_LOW | SPI_CLK_LOW);
}

static void spi_cs_inactive(void) {
    spi_set(SPI_CS_HIGH | SPI_CLK_LOW);
}

static unsigned char spi_xfer_byte(unsigned char tx) {
    unsigned char rx = 0;
    int i;

    for (i = 7; i >= 0; i--) {
        /* Set MOSI */
        unsigned int mosi = (tx >> i) & 1 ? SPI_MOSI_HIGH : SPI_MOSI_LOW;
        spi_set(SPI_CS_LOW | SPI_CLK_LOW | mosi);

        /* Rising edge — latch data */
        spi_set(SPI_CS_LOW | SPI_CLK_HIGH | mosi);
        rx = (rx << 1) | spi_get_miso();

        /* Falling edge */
        spi_set(SPI_CS_LOW | SPI_CLK_LOW | mosi);
    }

    return rx;
}

static void read_jedec_id(unsigned char *mfr, unsigned char *type, unsigned char *cap) {
    /* Enable bitbang mode */
    spiflash_bitbang_en_write(1);

    spi_cs_active();

    /* Send JEDEC Read ID command (0x9F) */
    spi_xfer_byte(0x9F);

    /* Read 3 response bytes */
    *mfr  = spi_xfer_byte(0x00);
    *type = spi_xfer_byte(0x00);
    *cap  = spi_xfer_byte(0x00);

    spi_cs_inactive();

    /* Disable bitbang mode (return to memory-mapped) */
    spiflash_bitbang_en_write(0);
}

int main(void) {
    irq_setmask(0);
    irq_setie(1);
    uart_init();

    printf("\n");
    printf("=== SPI Flash JEDEC ID Test ===\n");
    printf("\n");

    unsigned char mfr, type, cap;
    read_jedec_id(&mfr, &type, &cap);

    printf("JEDEC_ID: 0x%02X 0x%02X 0x%02X\n", mfr, type, cap);
    printf("MANUFACTURER: 0x%02X\n", mfr);
    printf("DEVICE_TYPE: 0x%02X\n", type);
    printf("CAPACITY: 0x%02X\n", cap);

    /* Validate: all-zeros or all-ones means no device or bus fault */
    int all_zero = (mfr == 0x00 && type == 0x00 && cap == 0x00);
    int all_ones = (mfr == 0xFF && type == 0xFF && cap == 0xFF);

    if (all_zero) {
        printf("SPI_FLASH_TEST: FAIL (all zeros — MISO stuck low or no device)\n");
    } else if (all_ones) {
        printf("SPI_FLASH_TEST: FAIL (all ones — bus not connected or CS fault)\n");
    } else {
        printf("SPI_FLASH_TEST: PASS\n");
    }

    printf("=== Test Complete ===\n");

    /* Hang here */
    while (1);

    return 0;
}
```

**Step 2: Create a minimal firmware Makefile**
```makefile
# Firmware Makefile for SPI Flash JEDEC ID test.
#
# This is compiled by the LiteX build system. The build directory
# must contain generated/csr.h and the linker script.
#
# Typically invoked indirectly by the LiteX Builder, not standalone.

BUILD_DIR ?= ../build/arty

include $(BUILD_DIR)/software/include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

OBJECTS = main.o

all: firmware.bin

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

firmware.elf: $(OBJECTS)
	$(LD) $(LDFLAGS) -T linker.ld -o $@ $^ -L$(BUILD_DIR)/software/libbase -lbase-nofloat -L$(BUILD_DIR)/software/libcompiler_rt -lcompiler_rt

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f *.o *.elf *.bin

.PHONY: all clean
```

**Step 3: Commit**
```
Add custom firmware to read SPI flash JEDEC ID via bitbang
```

---

### Task 3: Write the Host-Side SPI Flash ID Test Script
**Files:**
- Create: `designs/spi-flash-id/host/test_spiflash.py`

**Step 1: Create the test script**
```python
#!/usr/bin/env python3
"""
Host-side SPI Flash ID test script.

Captures UART output from the FPGA and looks for the JEDEC ID
printed by the custom firmware or by the LiteX BIOS.

Two modes of operation:
  1. Custom firmware mode (default): Looks for "JEDEC_ID:" and
     "SPI_FLASH_TEST: PASS/FAIL" lines.
  2. BIOS mode (--bios): Parses the BIOS boot output for SPI flash
     identification messages.

Usage:
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyUSB1
    uv run python designs/spi-flash-id/host/test_spiflash.py --port /dev/ttyAMA0 --board netv2
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
BOOT_TIMEOUT_S = 30

# Known-good JEDEC IDs per board (to be filled in after initial runs).
# Format: (manufacturer, device_type, capacity)
# Set to None to skip validation — only check for non-zero/non-FF.
EXPECTED_JEDEC_IDS: dict[str, tuple[int, int, int] | None] = {
    "arty":  None,  # TBD — varies by board revision
    "netv2": None,  # TBD — to be determined
}

# Common manufacturer names for reporting.
MANUFACTURER_NAMES = {
    0x01: "Spansion/Cypress/Infineon",
    0x20: "Micron/Numonyx/ST",
    0xC2: "Macronix (MXIC)",
    0xEF: "Winbond",
    0x1F: "Adesto/Atmel",
    0xBF: "SST/Microchip",
}


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #

def run_firmware_mode(ser: serial.Serial, board: str) -> tuple[bool, list[str]]:
    """Parse output from custom JEDEC ID firmware.

    Looks for lines:
        JEDEC_ID: 0xMM 0xTT 0xCC
        SPI_FLASH_TEST: PASS
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S

    jedec_id = None
    test_result = None

    jedec_re = re.compile(r"JEDEC_ID:\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})\s+0x([0-9A-Fa-f]{2})")
    result_re = re.compile(r"SPI_FLASH_TEST:\s+(PASS|FAIL)")

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        m = jedec_re.search(line)
        if m:
            jedec_id = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))

        m = result_re.search(line)
        if m:
            test_result = m.group(1)

        if "Test Complete" in line:
            break

    # Report.
    if jedec_id is None:
        print("FAIL: JEDEC ID not found in firmware output")
        return False, lines

    mfr, dtype, cap = jedec_id
    mfr_name = MANUFACTURER_NAMES.get(mfr, "Unknown")
    cap_mb = (2 ** cap) // (1024 * 1024) if cap >= 20 else (2 ** cap) // 1024 if cap >= 10 else 2 ** cap
    print(f"JEDEC ID: 0x{mfr:02X} 0x{dtype:02X} 0x{cap:02X}")
    print(f"  Manufacturer: {mfr_name} (0x{mfr:02X})")
    print(f"  Device type:  0x{dtype:02X}")
    print(f"  Capacity:     0x{cap:02X}")

    results: list[bool] = []

    # Check firmware's own verdict.
    if test_result == "PASS":
        print("PASS: Firmware reported SPI flash test passed")
        results.append(True)
    elif test_result == "FAIL":
        print("FAIL: Firmware reported SPI flash test failed")
        results.append(False)
    else:
        print("FAIL: Firmware test result not found in output")
        results.append(False)

    # Optionally compare against expected JEDEC ID.
    expected = EXPECTED_JEDEC_IDS.get(board)
    if expected is not None:
        if jedec_id == expected:
            print(f"PASS: JEDEC ID matches expected value for {board}")
            results.append(True)
        else:
            exp_str = " ".join(f"0x{b:02X}" for b in expected)
            got_str = " ".join(f"0x{b:02X}" for b in jedec_id)
            print(f"FAIL: JEDEC ID mismatch — expected {exp_str}, got {got_str}")
            results.append(False)

    return all(results), lines


def run_bios_mode(ser: serial.Serial, board: str) -> tuple[bool, list[str]]:
    """Parse SPI flash info from standard LiteX BIOS boot output.

    The BIOS prints flash identification during boot, e.g.:
        Initializing SPI Flash @0x...
    """
    lines: list[str] = []
    deadline = time.monotonic() + BOOT_TIMEOUT_S

    spi_detected = False

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        lines.append(line)

        if "SPI" in line.upper() and "flash" in line.lower():
            spi_detected = True
            print(f"  SPI Flash detected: {line}")

        if "litex>" in line:
            break

    if spi_detected:
        print("PASS: SPI flash detected during BIOS boot")
        return True, lines
    else:
        print("FAIL: No SPI flash detection in BIOS output")
        return False, lines


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="SPI Flash ID test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(EXPECTED_JEDEC_IDS.keys()),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--bios",
        action="store_true",
        help="Use BIOS mode (parse standard BIOS output instead of custom firmware)",
    )
    parser.add_argument(
        "--expected-jedec",
        help="Expected JEDEC ID as hex string, e.g. '20BA18' for Micron 128Mbit",
    )
    args = parser.parse_args()

    # Override expected JEDEC ID if provided on command line.
    if args.expected_jedec:
        hex_str = args.expected_jedec.replace("0x", "").replace(" ", "")
        if len(hex_str) != 6:
            print(f"ERROR: --expected-jedec must be 6 hex digits, got '{args.expected_jedec}'")
            return 2
        EXPECTED_JEDEC_IDS[args.board] = (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
        )

    print(f"Opening {args.port} at {args.baud} baud...")
    print(f"Board: {args.board}")
    print(f"Mode: {'BIOS' if args.bios else 'Custom firmware'}")
    print()

    ser = serial.Serial(args.port, args.baud, timeout=2)

    if args.bios:
        passed, boot_lines = run_bios_mode(ser, args.board)
    else:
        passed, boot_lines = run_firmware_mode(ser, args.board)

    ser.close()

    if not passed:
        print("\nFull output:")
        for line in boot_lines:
            print(f"  {line}")

    print()
    if passed:
        print("RESULT: PASS — SPI Flash ID test completed successfully")
        return 0
    else:
        print("RESULT: FAIL — SPI Flash ID test had failures")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Commit**
```
Add host-side SPI flash JEDEC ID test script
```

---

### Task 4: Adapt Target for NeTV2
**Files:**
- Create: `designs/spi-flash-id/gateware/spiflash_soc_netv2.py`

**Step 1: Create the NeTV2 SPI flash test SoC target**
```python
#!/usr/bin/env python3
"""
LiteX SoC target for SPI Flash ID test on Kosagi NeTV2.

NeTV2 SPI Flash: Quad SPI, CS=T19.
Clock: 50 MHz system clock (pin J19).
UART: GPIO to RPi (FPGA TX=E14, RX=E13) -> /dev/ttyAMA0.

Build command:
    uv run python designs/spi-flash-id/gateware/spiflash_soc_netv2.py --toolchain yosys+nextpnr --build

The bitstream is written to: designs/spi-flash-id/build/netv2/gateware/netv2_spiflash_test.bit
"""

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.builder import Builder

from litex_boards.platforms.kosagi_netv2 import Platform


def main():
    from litex.soc.integration.soc import LiteXSoCArgumentParser
    parser = LiteXSoCArgumentParser(description="SPI Flash ID Test SoC for NeTV2")
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
        ident          = "fpgas-online SPI Flash Test SoC — NeTV2",
        ident_version  = True,
        uart_baudrate  = 115200,
        **SoCCore.argdict(args),
    )

    # Add SPI Flash with bitbang access for JEDEC ID reading -------------------
    from litex.soc.cores.spi_flash import SpiFlash
    soc.submodules.spiflash = SpiFlash(
        platform.request("spiflash4x"),
        dummy=11,
        div=2,
        endianness="little",
    )
    soc.add_csr("spiflash")

    builder = Builder(soc, output_dir="designs/spi-flash-id/build/netv2", **Builder.argdict(args))
    builder.build(run=args.build)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```
Add LiteX SPI flash test SoC target for NeTV2
```

---

### Task 5: Write GitHub Actions Workflow, Design Makefile, and Update Root Makefile
**Files:**
- Create: `.github/workflows/build-spiflash-test.yml`
- Create: `designs/spi-flash-id/Makefile`
- Edit: `Makefile`

**Step 1: Create the CI workflow**
```yaml
name: Build SPI Flash ID Test Bitstreams

on:
  push:
    branches: [main]
    paths:
      - 'designs/spi-flash-id/**'
      - '.github/workflows/build-spiflash-test.yml'
  pull_request:
    paths:
      - 'designs/spi-flash-id/**'
      - '.github/workflows/build-spiflash-test.yml'
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
            target: designs/spi-flash-id/gateware/spiflash_soc_arty.py
            output_dir: designs/spi-flash-id/build/arty
          - board: netv2
            target: designs/spi-flash-id/gateware/spiflash_soc_netv2.py
            output_dir: designs/spi-flash-id/build/netv2

    steps:
      - uses: actions/checkout@v4

      - name: Build ${{ matrix.board }} SPI flash test bitstream
        run: |
          python3 ${{ matrix.target }} \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream artifact
        uses: actions/upload-artifact@v4
        with:
          name: spiflash-test-${{ matrix.board }}
          path: |
            ${{ matrix.output_dir }}/gateware/*.bit
            ${{ matrix.output_dir }}/gateware/*.bin
          if-no-files-found: error
```

**Step 2: Create the design Makefile**
```makefile
# Makefile for SPI Flash ID test design.
#
# Usage:
#   make arty      — Build bitstream for Arty A7
#   make netv2     — Build bitstream for NeTV2
#   make all       — Build all bitstreams
#   make test-arty — Run host-side test (Arty, requires FPGA attached)
#   make test-netv2— Run host-side test (NeTV2, requires FPGA attached)

PYTHON ?= uv run python

.PHONY: all arty netv2 test-arty test-netv2 program-arty program-netv2

all: arty netv2

arty:
	$(PYTHON) gateware/spiflash_soc_arty.py --toolchain yosys+nextpnr --build

netv2:
	$(PYTHON) gateware/spiflash_soc_netv2.py --toolchain yosys+nextpnr --build

# --------------------------------------------------------------------------- #
# Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

test-arty:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyUSB1 --board arty

test-netv2:
	$(PYTHON) host/test_spiflash.py --port /dev/ttyAMA0 --board netv2

# --------------------------------------------------------------------------- #
# Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

program-arty:
	openFPGALoader -b arty build/arty/gateware/arty_spiflash_test.bit

program-netv2:
	openocd -f alphamax-rpi.cfg -c "pld load 0 build/netv2/gateware/netv2_spiflash_test.bit; exit"
```

**Step 3: Append SPI flash test targets to root Makefile**

Add the following after the DDR test section:

```makefile
# --------------------------------------------------------------------------- #
# SPI Flash ID Test
# --------------------------------------------------------------------------- #

.PHONY: spiflash-arty spiflash-netv2 spiflash-all

spiflash-arty:
	$(MAKE) -C designs/spi-flash-id arty

spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id netv2

spiflash-all: spiflash-arty spiflash-netv2

# --------------------------------------------------------------------------- #
# SPI Flash Host-side tests (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: test-spiflash-arty test-spiflash-netv2

test-spiflash-arty:
	$(MAKE) -C designs/spi-flash-id test-arty

test-spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id test-netv2

# --------------------------------------------------------------------------- #
# SPI Flash Programming (run on RPi with FPGA attached)
# --------------------------------------------------------------------------- #

.PHONY: program-spiflash-arty program-spiflash-netv2

program-spiflash-arty:
	$(MAKE) -C designs/spi-flash-id program-arty

program-spiflash-netv2:
	$(MAKE) -C designs/spi-flash-id program-netv2
```

**Step 4: Update the `all` target**

Change `all: uart-all ddr-all` to:
```makefile
all: uart-all ddr-all spiflash-all
```

**Step 5: Commit**
```
Add SPI flash test GitHub Actions workflow and Makefile targets
```

---

### Task 6: Create Pull Request
**Step 1: Push branch to remote**
```bash
git push -u origin feature/spi-flash-id-test
```

**Step 2: Create pull request**
```bash
gh pr create --title "Add SPI flash ID test design for Arty A7 and NeTV2" --body "$(cat <<'EOF'
## Summary
- LiteX SoC targets with SPI flash CSR access for Arty A7 and NeTV2
- Custom C firmware reading JEDEC ID via 0x9F command
- Host-side Python test script validating manufacturer/device/capacity bytes
- GitHub Actions workflow for bitstream builds
- Makefile for local builds and testing

## Test plan
- [ ] Verify `uv run python designs/spi-flash-id/gateware/spiflash_soc_arty.py --help` parses correctly
- [ ] Verify `uv run python designs/spi-flash-id/host/test_spiflash.py --help` parses correctly
- [ ] CI builds bitstreams successfully

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 3: Clean up worktree (after PR is merged)**
```bash
cd /home/tim/github/mithro/fpgas-online-test-designs
git worktree remove .worktrees/spi-flash-id-test
git branch -d feature/spi-flash-id-test
```
