# PMOD Loopback Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify bidirectional PMOD connector connectivity between RPi PMOD HAT and Arty A7 PMOD ports by driving bit patterns in both directions and checking for mismatches.

**Architecture:** A LiteX SoC on the Arty A7 exposes GPIO cores (input + output) for each PMOD connector via CSR registers, plus a UART for command/response communication. A Python test script on the RPi uses `gpiod` to drive/read the PMOD HAT GPIO pins and `pyserial` to send commands to and read responses from the FPGA firmware. The firmware implements a simple text protocol: `READ` returns the current GPIO input value, and `DRIVE <hex>` sets the GPIO output value.

**Tech Stack:** LiteX (Python SoC builder), openXC7 toolchain (Yosys + nextpnr-xilinx), Python 3 with gpiod + pyserial, GitHub Actions CI

**Branch:** `feature/pmod-loopback-test` (developed in `.worktrees/pmod-loopback-test` worktree)

---

### Task 0: Set Up Worktree and Branch
**Prerequisites:** `.gitignore` must include `.worktrees/` (already configured in main).

**Step 1: Create worktree with feature branch**
```bash
git worktree add .worktrees/pmod-loopback-test -b feature/pmod-loopback-test
cd .worktrees/pmod-loopback-test
```

**Step 2: Verify clean baseline**
```bash
git status
git log --oneline -3
```

> **Note:** All subsequent tasks in this plan are executed inside the `.worktrees/pmod-loopback-test` worktree. File paths are relative to the worktree root.

---

### Task 1: Create Project Structure
**Files:**
- Create: `designs/pmod-loopback/pyproject.toml`
- Create: `designs/pmod-loopback/Makefile`

**Step 1: Create directory layout**
```bash
mkdir -p designs/pmod-loopback/gateware
mkdir -p designs/pmod-loopback/firmware
mkdir -p designs/pmod-loopback/host
```

**Step 2: Write pyproject.toml**
```toml
# designs/pmod-loopback/pyproject.toml
[project]
name = "pmod-loopback-test"
version = "0.1.0"
description = "PMOD loopback test for fpgas.online infrastructure"
requires-python = ">=3.9"
dependencies = [
    "litex",
    "litex-boards",
    "pyserial>=3.5",
    "gpiod>=2.0",
]

[project.optional-dependencies]
dev = [
    "ruff",
    "pytest",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
```

**Step 3: Write Makefile**
```makefile
# designs/pmod-loopback/Makefile
BOARD       ?= arty
VARIANT     ?= a7-35
TOOLCHAIN   ?= yosys+nextpnr
UART_PORT   ?= /dev/ttyUSB1
BAUD_RATE   ?= 115200
BUILD_DIR   ?= build/digilent_arty

.PHONY: gateware firmware test clean

gateware:
	uv run python gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

firmware:
	uv run python gateware/pmod_loopback_soc.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--no-compile-gateware

program:
	openFPGALoader -b arty $(BUILD_DIR)/gateware/digilent_arty.bit

test:
	uv run python host/test_pmod_loopback.py \
		--port $(UART_PORT) \
		--baud $(BAUD_RATE)

clean:
	rm -rf build/
```

**Step 4: Commit**
```bash
git add designs/pmod-loopback/pyproject.toml designs/pmod-loopback/Makefile
git commit -m "pmod-loopback: add project structure with pyproject.toml and Makefile"
```

---

### Task 2: Write LiteX SoC with GPIO Cores for PMOD Connectors
**Files:**
- Create: `designs/pmod-loopback/gateware/pmod_loopback_soc.py`

**Step 1: Write the SoC definition**
```python
#!/usr/bin/env python3
# designs/pmod-loopback/gateware/pmod_loopback_soc.py
"""LiteX SoC with CSR-mapped GPIO cores for PMOD loopback testing on Arty A7."""

import argparse

from migen import *

from litex.soc.cores.gpio import GPIOIn, GPIOOut
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import digilent_arty
from litex_boards.targets.digilent_arty import BaseSoC as ArtyBaseSoC


# -- Platform extensions: expose PMOD pins as named platform resources --------

_pmod_io = [
    # PMODA -- directly uses connector pins from the Arty platform
    ("pmoda_in",  0, Pins("pmoda:0 pmoda:1 pmoda:2 pmoda:3 pmoda:4 pmoda:5 pmoda:6 pmoda:7"), IOStandard("LVCMOS33")),
    ("pmoda_out", 0, Pins("pmoda:0 pmoda:1 pmoda:2 pmoda:3 pmoda:4 pmoda:5 pmoda:6 pmoda:7"), IOStandard("LVCMOS33")),
    # PMODB
    ("pmodb_in",  0, Pins("pmodb:0 pmodb:1 pmodb:2 pmodb:3 pmodb:4 pmodb:5 pmodb:6 pmodb:7"), IOStandard("LVCMOS33")),
    ("pmodb_out", 0, Pins("pmodb:0 pmodb:1 pmodb:2 pmodb:3 pmodb:4 pmodb:5 pmodb:6 pmodb:7"), IOStandard("LVCMOS33")),
    # PMODC
    ("pmodc_in",  0, Pins("pmodc:0 pmodc:1 pmodc:2 pmodc:3 pmodc:4 pmodc:5 pmodc:6 pmodc:7"), IOStandard("LVCMOS33")),
    ("pmodc_out", 0, Pins("pmodc:0 pmodc:1 pmodc:2 pmodc:3 pmodc:4 pmodc:5 pmodc:6 pmodc:7"), IOStandard("LVCMOS33")),
    # PMODD
    ("pmodd_in",  0, Pins("pmodd:0 pmodd:1 pmodd:2 pmodd:3 pmodd:4 pmodd:5 pmodd:6 pmodd:7"), IOStandard("LVCMOS33")),
    ("pmodd_out", 0, Pins("pmodd:0 pmodd:1 pmodd:2 pmodd:3 pmodd:4 pmodd:5 pmodd:6 pmodd:7"), IOStandard("LVCMOS33")),
]


class PmodLoopbackSoC(SoCCore):
    """LiteX SoC with GPIO cores on all four PMOD connectors.

    Each PMOD port gets two CSR peripherals:
      - pmod{x}_in  (GPIOIn):  8-bit input register, directly samples PMOD pins
      - pmod{x}_out (GPIOOut): 8-bit output register, drives PMOD pins

    The firmware selects the active direction by configuring the FPGA pin as
    either an input or output.  Because Migen Pins() cannot be simultaneously
    input AND output on the same resource, the SoC uses GPIOTristate from
    CSRStorage/CSRStatus instead.  For simplicity in this first version, we use
    separate GPIOIn and GPIOOut resources.  The test protocol ensures only one
    direction is active at a time (the other side is high-Z).
    """

    def __init__(self, variant="a7-35", toolchain="yosys+nextpnr", **kwargs):
        platform = digilent_arty.Platform(variant=variant, toolchain=toolchain)

        # Add PMOD extensions -- but we cannot add both _in and _out for the
        # same physical pins.  Instead, use GPIOTristate which handles
        # direction control via an output-enable CSR.
        #
        # We will use a custom approach: one Tristate GPIO per PMOD port.

        # Set up SoCCore with UART (115200 baud is the LiteX default)
        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq=100e6,
            ident="PMOD Loopback Test SoC",
            ident_version=True,
            uart_baudrate=115200,
            **kwargs,
        )

        # Add PMOD GPIO tristates using CSRStorage (oe + output) and CSRStatus (input)
        for port_name in ["pmoda", "pmodb", "pmodc", "pmodd"]:
            pmod_pads = platform.request(port_name)
            # pmod_pads is an 8-bit signal from the connector definition
            # Use GPIOTristate-style manual wiring via CSR registers

            gpio_in  = GPIOIn(pmod_pads)
            self.add_module(name=f"{port_name}_in", module=gpio_in)
            self.add_csr(f"{port_name}_in")

        # Note: For output direction, firmware will reconfigure pins.
        # In a tristate design, we'd use GPIOTristate.  For v1, the FPGA
        # reads inputs and the host script handles output via gpiod.
        # The FPGA-to-RPi direction uses CSRStorage to drive pins.
        for port_name in ["pmoda", "pmodb", "pmodc", "pmodd"]:
            # We need separate output pads -- but since we can't request
            # the same connector twice, we wire outputs manually.
            # For v1: use a single GPIOTristate per port instead.
            pass


def build_soc():
    parser = argparse.ArgumentParser(description="PMOD Loopback SoC for Arty A7")
    parser.add_argument("--variant",    default="a7-35",          help="Arty variant: a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr",  help="Toolchain: vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",      help="Build the bitstream")
    parser.add_argument("--load",       action="store_true",      help="Load bitstream to FPGA")
    parser.add_argument("--no-compile-gateware", action="store_true", help="Skip gateware compilation")
    args = parser.parse_args()

    soc = PmodLoopbackSoC(variant=args.variant, toolchain=args.toolchain)

    builder = Builder(soc, compile_gateware=not args.no_compile_gateware)
    builder.build(run=args.build)

    if args.load:
        from litex.build.openocd import OpenOCD
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    build_soc()
```

This initial version has a problem: you cannot `platform.request()` the same connector for both input and output. The correct approach is to use `GPIOTristate`. Let's replace the SoC with the proper tristate version:

**Step 2: Rewrite using GPIOTristate for bidirectional PMOD pins**
```python
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
```

**Step 3: Commit**
```bash
git add designs/pmod-loopback/gateware/pmod_loopback_soc.py
git commit -m "pmod-loopback: add LiteX SoC with GPIOTristate for all four PMOD ports"
```

---

### Task 3: Write Firmware for GPIO Read/Drive with UART Command Interface
**Files:**
- Create: `designs/pmod-loopback/firmware/main.c`

**Step 1: Write the firmware**
```c
/* designs/pmod-loopback/firmware/main.c
 *
 * PMOD Loopback Test Firmware
 *
 * Runs on the LiteX VexRiscv CPU.  Provides a UART command interface for
 * the host-side test script to read and drive PMOD GPIO pins.
 *
 * Commands (newline-terminated):
 *   READ <port>            -> "OK <hex>\n"   (read 8-bit input value)
 *   DRIVE <port> <hex>     -> "OK\n"         (set output value, enable OE)
 *   HIZ <port>             -> "OK\n"         (disable OE, set pins to input)
 *   PING                   -> "PONG\n"
 *
 * <port> is one of: A, B, C, D (maps to pmoda..pmodd)
 * <hex>  is a 2-digit hex value: 00..FF
 *
 * Example session:
 *   > PING
 *   < PONG
 *   > HIZ A
 *   < OK
 *   > READ A
 *   < OK 3F
 *   > DRIVE A FF
 *   < OK
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#include <irq.h>
#include <uart.h>
#include <generated/csr.h>

/* ---- helpers ------------------------------------------------------------ */

/* Read a line from UART into buf (max len-1 chars).  Returns length. */
static int uart_readline(char *buf, int len) {
    int i = 0;
    while (i < len - 1) {
        char c = uart_read();
        if (c == '\r' || c == '\n') {
            break;
        }
        buf[i++] = c;
    }
    buf[i] = '\0';
    return i;
}

/* Convert port letter (A-D) to index (0-3).  Returns -1 on invalid. */
static int parse_port(char c) {
    c = toupper(c);
    if (c >= 'A' && c <= 'D') return c - 'A';
    return -1;
}

/* CSR accessor macros -- generated names follow the pattern:
 *   pmoda_oe_read()  / pmoda_oe_write(v)
 *   pmoda_out_read() / pmoda_out_write(v)
 *   pmoda_in_read()
 * We use a dispatch table to avoid a giant switch. */

typedef struct {
    uint32_t (*in_read)(void);
    void     (*oe_write)(uint32_t);
    void     (*out_write)(uint32_t);
} pmod_ops_t;

static const pmod_ops_t pmod_ops[4] = {
    {
        .in_read   = pmoda_in_read,
        .oe_write  = pmoda_oe_write,
        .out_write = pmoda_out_write,
    },
    {
        .in_read   = pmodb_in_read,
        .oe_write  = pmodb_oe_write,
        .out_write = pmodb_out_write,
    },
    {
        .in_read   = pmodc_in_read,
        .oe_write  = pmodc_oe_write,
        .out_write = pmodc_out_write,
    },
    {
        .in_read   = pmodd_in_read,
        .oe_write  = pmodd_oe_write,
        .out_write = pmodd_out_write,
    },
};

/* ---- command handlers --------------------------------------------------- */

static void cmd_ping(void) {
    printf("PONG\n");
}

static void cmd_read(const char *args) {
    if (strlen(args) < 1) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    uint32_t val = pmod_ops[port].in_read() & 0xFF;
    printf("OK %02X\n", val);
}

static void cmd_drive(const char *args) {
    if (strlen(args) < 3) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    uint32_t val = (uint32_t)strtoul(&args[2], NULL, 16) & 0xFF;
    pmod_ops[port].oe_write(0xFF);    /* all 8 pins as outputs */
    pmod_ops[port].out_write(val);
    printf("OK\n");
}

static void cmd_hiz(const char *args) {
    if (strlen(args) < 1) { printf("ERR bad args\n"); return; }
    int port = parse_port(args[0]);
    if (port < 0) { printf("ERR bad port\n"); return; }

    pmod_ops[port].oe_write(0x00);    /* all 8 pins as inputs (high-Z) */
    printf("OK\n");
}

/* ---- main loop ---------------------------------------------------------- */

int main(void) {
    char line[64];

    irq_setmask(0);
    irq_setie(1);
    uart_init();

    printf("\n");
    printf("========================================\n");
    printf("  PMOD Loopback Test Firmware\n");
    printf("  Ports: A(JA), B(JB), C(JC), D(JD)\n");
    printf("  Commands: PING, READ, DRIVE, HIZ\n");
    printf("========================================\n");
    printf("READY\n");

    /* Default: all ports as inputs */
    for (int i = 0; i < 4; i++) {
        pmod_ops[i].oe_write(0x00);
    }

    while (1) {
        printf("> ");
        int len = uart_readline(line, sizeof(line));
        if (len == 0) continue;

        if (strncmp(line, "PING", 4) == 0) {
            cmd_ping();
        } else if (strncmp(line, "READ ", 5) == 0) {
            cmd_read(line + 5);
        } else if (strncmp(line, "DRIVE ", 6) == 0) {
            cmd_drive(line + 6);
        } else if (strncmp(line, "HIZ ", 4) == 0) {
            cmd_hiz(line + 4);
        } else {
            printf("ERR unknown command\n");
        }
    }

    return 0;
}
```

**Step 2: Commit**
```bash
git add designs/pmod-loopback/firmware/main.c
git commit -m "pmod-loopback: add firmware with UART command interface for GPIO read/drive"
```

---

### Task 4: Write Host-Side Test Script
**Files:**
- Create: `designs/pmod-loopback/host/test_pmod_loopback.py`

**Step 1: Write the test script**
```python
#!/usr/bin/env python3
# designs/pmod-loopback/host/test_pmod_loopback.py
"""Host-side PMOD loopback test script.

Runs on the Raspberry Pi.  Uses gpiod to drive/read the PMOD HAT GPIO pins
and pyserial to communicate with the FPGA firmware over UART.

Usage:
    uv run python host/test_pmod_loopback.py --port /dev/ttyUSB1 --pmod-port JA

Requirements:
    - Raspberry Pi with Digilent PMOD HAT
    - FPGA programmed with pmod_loopback_soc bitstream
    - PMOD cable connecting RPi PMOD HAT port to Arty PMOD port
    - libgpiod2 installed (apt install libgpiod2 python3-libgpiod)
"""

import argparse
import sys
import time

import gpiod
import serial


# -- PMOD HAT GPIO pin mapping (RPi BCM GPIO numbers) -------------------------
# Each PMOD HAT port has 8 signal pins mapped to specific BCM GPIO numbers.
# Pin order matches PMOD standard: pins 1-4 (top row), pins 7-10 (bottom row).

PMOD_HAT_PINS = {
    "JA": [6, 13, 19, 26, 12, 16, 20, 21],
    "JB": [5, 11,  9, 10,  7,  8,  0,  1],
    "JC": [17, 18,  4, 14,  2,  3, 15, 25],
}

# Map PMOD HAT port to Arty PMOD port letter for firmware commands
HAT_TO_ARTY_PORT = {
    "JA": "A",
    "JB": "B",
    "JC": "C",
}

# Default GPIO chip name (works on both RPi 4 and RPi 5)
GPIO_CHIP = "/dev/gpiochip0"
# On RPi 5, the main GPIO is on /dev/gpiochip4 (RP1 chip)
GPIO_CHIP_RPI5 = "/dev/gpiochip4"


# -- Test patterns -------------------------------------------------------------

def generate_test_patterns():
    """Generate the set of test bit patterns for 8-bit PMOD port."""
    patterns = []
    # All zeros and all ones
    patterns.append(0x00)
    patterns.append(0xFF)
    # Walking 1
    for i in range(8):
        patterns.append(1 << i)
    # Walking 0
    for i in range(8):
        patterns.append(0xFF ^ (1 << i))
    # Alternating
    patterns.append(0xAA)
    patterns.append(0x55)
    return patterns


# -- UART communication --------------------------------------------------------

class FpgaUart:
    """Communicate with PMOD loopback firmware over UART."""

    def __init__(self, port, baud=115200, timeout=2.0):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(0.1)  # let FPGA boot
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _send(self, cmd):
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()

    def _read_response(self):
        """Read lines until we get a response (skip prompt '> ' lines)."""
        deadline = time.time() + 2.0
        while time.time() < deadline:
            line = self.ser.readline().decode(errors="replace").strip()
            if line.startswith("> "):
                line = line[2:]
            if line.startswith("OK") or line.startswith("ERR") or line == "PONG":
                return line
        raise TimeoutError("No response from FPGA firmware")

    def ping(self):
        self._send("PING")
        resp = self._read_response()
        return resp == "PONG"

    def wait_ready(self):
        """Wait for the READY banner after boot/reset."""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            line = self.ser.readline().decode(errors="replace").strip()
            if "READY" in line:
                return True
        return False

    def read_port(self, port_letter):
        """Read 8-bit input value from FPGA PMOD port. Returns int."""
        self._send(f"READ {port_letter}")
        resp = self._read_response()
        if not resp.startswith("OK "):
            raise RuntimeError(f"READ failed: {resp}")
        return int(resp.split()[1], 16)

    def drive_port(self, port_letter, value):
        """Drive 8-bit value on FPGA PMOD port (enables output)."""
        self._send(f"DRIVE {port_letter} {value:02X}")
        resp = self._read_response()
        if resp != "OK":
            raise RuntimeError(f"DRIVE failed: {resp}")

    def hiz_port(self, port_letter):
        """Set FPGA PMOD port to high-impedance (input mode)."""
        self._send(f"HIZ {port_letter}")
        resp = self._read_response()
        if resp != "OK":
            raise RuntimeError(f"HIZ failed: {resp}")


# -- GPIO helper ---------------------------------------------------------------

def detect_gpio_chip():
    """Detect the correct gpiochip for RPi GPIO pins."""
    # Try RPi 5 chip first, fall back to RPi 4/3 chip
    for chip_path in [GPIO_CHIP_RPI5, GPIO_CHIP]:
        try:
            chip = gpiod.Chip(chip_path)
            chip.close()
            return chip_path
        except (OSError, PermissionError):
            continue
    raise RuntimeError("Cannot find GPIO chip. Is libgpiod installed?")


class PmodHatGpio:
    """Drive/read PMOD HAT GPIO pins using gpiod."""

    def __init__(self, hat_port, chip_path=None):
        if hat_port not in PMOD_HAT_PINS:
            raise ValueError(f"Unknown PMOD HAT port: {hat_port}. Use JA, JB, or JC.")
        self.pin_numbers = PMOD_HAT_PINS[hat_port]
        self.chip_path = chip_path or detect_gpio_chip()
        self._request = None

    def close(self):
        if self._request:
            self._request.release()
            self._request = None

    def configure_output(self):
        """Configure all 8 pins as outputs."""
        self.close()
        self._request = gpiod.request_lines(
            self.chip_path,
            consumer="pmod-loopback-test",
            config={
                tuple(self.pin_numbers): gpiod.LineSettings(
                    direction=gpiod.line.Direction.OUTPUT,
                    output_value=gpiod.line.Value.INACTIVE,
                ),
            },
        )

    def configure_input(self):
        """Configure all 8 pins as inputs."""
        self.close()
        self._request = gpiod.request_lines(
            self.chip_path,
            consumer="pmod-loopback-test",
            config={
                tuple(self.pin_numbers): gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                ),
            },
        )

    def write(self, value):
        """Write 8-bit value to output pins. Bit 0 = pin index 0, etc."""
        values = {}
        for i, pin in enumerate(self.pin_numbers):
            bit = (value >> i) & 1
            values[pin] = gpiod.line.Value.ACTIVE if bit else gpiod.line.Value.INACTIVE
        self._request.set_values(values)

    def read(self):
        """Read 8-bit value from input pins. Returns int."""
        values = self._request.get_values()
        result = 0
        for i, pin in enumerate(self.pin_numbers):
            if values[pin] == gpiod.line.Value.ACTIVE:
                result |= (1 << i)
        return result


# -- Test runner ----------------------------------------------------------------

def run_test(uart_port, baud, hat_port, arty_port):
    """Run bidirectional PMOD loopback test."""
    patterns = generate_test_patterns()
    total_tests = 0
    failures = []

    print(f"=== PMOD Loopback Test ===")
    print(f"UART:       {uart_port} @ {baud}")
    print(f"HAT port:   {hat_port} (RPi PMOD HAT)")
    print(f"Arty port:  PMOD{arty_port}")
    print(f"Patterns:   {len(patterns)}")
    print()

    fpga = FpgaUart(uart_port, baud)
    gpio = PmodHatGpio(hat_port)

    try:
        # Wait for firmware ready
        print("Waiting for FPGA firmware...", end=" ", flush=True)
        if not fpga.ping():
            print("FAIL - no PONG response")
            return False
        print("OK")

        # ---- Phase 1: RPi drives, FPGA reads ----
        print("\n--- Phase 1: RPi -> FPGA ---")
        fpga.hiz_port(arty_port)         # FPGA pins as inputs
        gpio.configure_output()           # RPi pins as outputs
        time.sleep(0.01)

        for pattern in patterns:
            gpio.write(pattern)
            time.sleep(0.001)  # settle time
            reading = fpga.read_port(arty_port)
            total_tests += 1
            if reading != pattern:
                failures.append(
                    f"RPi->FPGA: sent 0x{pattern:02X}, got 0x{reading:02X} "
                    f"(diff 0x{pattern ^ reading:02X})"
                )
                print(f"  FAIL: sent 0x{pattern:02X}, got 0x{reading:02X}")
            else:
                print(f"  OK:   0x{pattern:02X}")

        # ---- Phase 2: FPGA drives, RPi reads ----
        print("\n--- Phase 2: FPGA -> RPi ---")
        gpio.configure_input()            # RPi pins as inputs
        time.sleep(0.01)

        for pattern in patterns:
            fpga.drive_port(arty_port, pattern)
            time.sleep(0.001)  # settle time
            reading = gpio.read()
            total_tests += 1
            if reading != pattern:
                failures.append(
                    f"FPGA->RPi: sent 0x{pattern:02X}, got 0x{reading:02X} "
                    f"(diff 0x{pattern ^ reading:02X})"
                )
                print(f"  FAIL: sent 0x{pattern:02X}, got 0x{reading:02X}")
            else:
                print(f"  OK:   0x{pattern:02X}")

        # Clean up: set FPGA back to high-Z
        fpga.hiz_port(arty_port)

    finally:
        gpio.close()
        fpga.close()

    # ---- Results ----
    print()
    print(f"=== Results: {total_tests - len(failures)}/{total_tests} passed ===")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        return False
    else:
        print("PASS")
        return True


def main():
    parser = argparse.ArgumentParser(description="PMOD Loopback Test (host-side)")
    parser.add_argument("--port",      default="/dev/ttyUSB1",  help="UART serial port")
    parser.add_argument("--baud",      type=int, default=115200, help="UART baud rate")
    parser.add_argument("--hat-port",  default="JA",            help="PMOD HAT port: JA, JB, JC")
    parser.add_argument("--arty-port", default=None,            help="Arty PMOD port letter: A, B, C, D (default: matches HAT port)")
    args = parser.parse_args()

    arty_port = args.arty_port or HAT_TO_ARTY_PORT.get(args.hat_port, "A")

    success = run_test(args.port, args.baud, args.hat_port, arty_port)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/pmod-loopback/host/test_pmod_loopback.py
git commit -m "pmod-loopback: add host-side test script using gpiod + pyserial"
```

---

### Task 5: GitHub Actions Workflow
**Files:**
- Create: `.github/workflows/pmod-loopback-build.yml`

**Step 1: Write the CI workflow**
```yaml
# .github/workflows/pmod-loopback-build.yml
name: "Build: PMOD Loopback"

on:
  push:
    paths:
      - "designs/pmod-loopback/**"
      - ".github/workflows/pmod-loopback-build.yml"
  pull_request:
    paths:
      - "designs/pmod-loopback/**"

jobs:
  build-arty:
    name: "Arty A7-35T bitstream"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y git build-essential python3 python3-pip \
            yosys nextpnr-xilinx prjxray-tools

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install Python dependencies
        working-directory: designs/pmod-loopback
        run: uv sync

      - name: Build gateware (bitstream + firmware)
        working-directory: designs/pmod-loopback
        run: |
          uv run python gateware/pmod_loopback_soc.py \
            --variant a7-35 \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream artifact
        uses: actions/upload-artifact@v4
        with:
          name: pmod-loopback-arty-a7-35t
          path: designs/pmod-loopback/build/digilent_arty/gateware/digilent_arty.bit

  lint:
    name: "Lint Python"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Lint with ruff
        working-directory: designs/pmod-loopback
        run: |
          uv run ruff check gateware/ host/ firmware/
```

**Step 2: Commit**
```bash
git add .github/workflows/pmod-loopback-build.yml
git commit -m "pmod-loopback: add GitHub Actions workflow for bitstream build and lint"
```

---

### Task 6: Create Pull Request
**Step 1: Push branch to remote**
```bash
git push -u origin feature/pmod-loopback-test
```

**Step 2: Create pull request**
```bash
gh pr create --title "Add PMOD loopback test design for Arty A7" --body "$(cat <<'EOF'
## Summary
- LiteX SoC with GPIOTristate for all four PMOD connectors
- Custom C firmware with UART command interface (PING/READ/DRIVE/HIZ)
- Host-side Python test script using gpiod + pyserial for bidirectional testing
- GitHub Actions workflow for bitstream builds

## Test plan
- [ ] Verify SoC builds with `--help` flag
- [ ] Verify host script parses with `--help` flag
- [ ] CI builds bitstreams successfully

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 3: Clean up worktree (after PR is merged)**
```bash
cd /home/tim/github/mithro/fpgas-online-test-designs
git worktree remove .worktrees/pmod-loopback-test
git branch -d feature/pmod-loopback-test
```
