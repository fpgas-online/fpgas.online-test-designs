# Ethernet Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify Ethernet MAC/PHY functionality on Arty A7 (MII) and NeTV2 (RMII) by building a LiteX SoC with LiteEth, booting the BIOS, reading the MAC address from UART output, and confirming ARP + ICMP ping responses from the host RPi.

**Architecture:** The FPGA runs a standard LiteX SoC with `--with-ethernet` and `--with-sdram`, which gives the BIOS a full IP stack (ARP, ICMP, TFTP). The LiteX BIOS prints the MAC address and IP configuration during boot. The host-side Python script on the RPi configures the USB Ethernet adapter with a static IP (192.168.1.100), parses the BIOS UART output for the MAC address, then runs ARP and ICMP ping tests against the FPGA's default IP (192.168.1.50).

**Tech Stack:** LiteX with LiteEth, openXC7 toolchain, Python 3 with pyserial + subprocess (arping/ping), GitHub Actions CI

**Branch:** `feature/ethernet-test` (developed in `.worktrees/ethernet-test` worktree)

---

### Task 0: Set Up Worktree and Branch
**Prerequisites:** `.gitignore` must include `.worktrees/` (already configured in main).

**Step 1: Create worktree with feature branch**
```bash
git worktree add .worktrees/ethernet-test -b feature/ethernet-test
cd .worktrees/ethernet-test
```

**Step 2: Verify clean baseline**
```bash
git status
git log --oneline -3
```

> **Note:** All subsequent tasks in this plan are executed inside the `.worktrees/ethernet-test` worktree. File paths are relative to the worktree root.

---

### Task 1: Create Project Structure
**Files:**
- Create: `designs/ethernet-test/pyproject.toml`
- Create: `designs/ethernet-test/Makefile`

**Step 1: Create directory layout**
```bash
mkdir -p designs/ethernet-test/gateware
mkdir -p designs/ethernet-test/host
```

**Step 2: Write pyproject.toml**
```toml
# designs/ethernet-test/pyproject.toml
[project]
name = "ethernet-test"
version = "0.1.0"
description = "Ethernet connectivity test for fpgas.online infrastructure"
requires-python = ">=3.9"
dependencies = [
    "litex",
    "litex-boards",
    "liteeth",
    "pyserial>=3.5",
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
# designs/ethernet-test/Makefile
TOOLCHAIN   ?= yosys+nextpnr
BAUD_RATE   ?= 115200

# ---- Arty A7 ----------------------------------------------------------------
ARTY_VARIANT   ?= a7-35
ARTY_UART      ?= /dev/ttyUSB1
ARTY_BUILD_DIR ?= build/arty

# ---- NeTV2 -------------------------------------------------------------------
NETV2_UART     ?= /dev/ttyAMA0
NETV2_BUILD_DIR?= build/netv2

.PHONY: gateware-arty gateware-netv2 program-arty program-netv2 test-arty test-netv2 clean

# -- Arty A7 --
gateware-arty:
	uv run python gateware/ethernet_soc_arty.py \
		--variant $(ARTY_VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

program-arty:
	openFPGALoader -b arty $(ARTY_BUILD_DIR)/gateware/digilent_arty.bit

test-arty:
	uv run python host/test_ethernet.py \
		--board arty \
		--uart-port $(ARTY_UART) \
		--baud $(BAUD_RATE)

# -- NeTV2 --
gateware-netv2:
	uv run python gateware/ethernet_soc_netv2.py \
		--toolchain $(TOOLCHAIN) \
		--build

program-netv2:
	openocd -f alphamax-rpi.cfg -c "init; pld load 0 $(NETV2_BUILD_DIR)/gateware/kosagi_netv2.bit; exit"

test-netv2:
	uv run python host/test_ethernet.py \
		--board netv2 \
		--uart-port $(NETV2_UART) \
		--baud $(BAUD_RATE)

clean:
	rm -rf build/
```

**Step 4: Commit**
```bash
git add designs/ethernet-test/pyproject.toml designs/ethernet-test/Makefile
git commit -m "ethernet-test: add project structure with pyproject.toml and Makefile"
```

---

### Task 2: Write LiteX SoC with Ethernet for Arty A7
**Files:**
- Create: `designs/ethernet-test/gateware/ethernet_soc_arty.py`

**Step 1: Write the Arty Ethernet SoC**
```python
#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_arty.py
"""LiteX SoC with LiteEth (MII) for Arty A7 Ethernet testing.

Builds a standard LiteX SoC with:
  - VexRiscv CPU + BIOS (with built-in networking: ARP, ICMP, TFTP)
  - DDR3 SDRAM (256 MB via MT41K128M16JT-125)
  - LiteEth MAC + MII PHY (TI DP83848J, 100Base-T)
  - UART at 115200 baud

The BIOS boots, initializes the Ethernet PHY, prints the MAC address, and
responds to ARP/ICMP automatically.  No custom firmware is needed.

Default network config (LiteX BIOS defaults):
  - FPGA IP:  192.168.1.50
  - Host IP:  192.168.1.100 (TFTP server)
  - MAC:      10:e2:d5:00:00:00 (default, configurable via --eth-ip)
"""

import argparse

from litex.soc.integration.builder import Builder

from litex_boards.targets.digilent_arty import BaseSoC


def main():
    parser = argparse.ArgumentParser(description="Ethernet Test SoC for Arty A7")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream")
    parser.add_argument("--eth-ip",     default="192.168.1.50",  help="FPGA IP address")
    parser.add_argument("--remote-ip",  default="192.168.1.100", help="Host/TFTP IP address")
    args = parser.parse_args()

    # BaseSoC from litex-boards already supports --with-ethernet and --with-sdram.
    # We instantiate it directly with the flags we need.
    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=100e6,
        with_ethernet=True,
        with_sdram=True,
        uart_baudrate=115200,
        ident="Ethernet Test SoC (Arty A7)",
        ident_version=True,
    )

    builder = Builder(soc, output_dir="build/arty")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/ethernet-test/gateware/ethernet_soc_arty.py
git commit -m "ethernet-test: add LiteX SoC with LiteEth MII for Arty A7"
```

---

### Task 3: Write Host-Side Ethernet Test Script
**Files:**
- Create: `designs/ethernet-test/host/test_ethernet.py`

**Step 1: Write the test script**
```python
#!/usr/bin/env python3
# designs/ethernet-test/host/test_ethernet.py
"""Host-side Ethernet test script.

Runs on the Raspberry Pi.  Tests Ethernet connectivity to an FPGA running
a LiteX SoC with LiteEth.

Steps:
  1. Detect the USB Ethernet adapter connected to the FPGA
  2. Configure the adapter with static IP 192.168.1.100/24
  3. Read MAC address from LiteX BIOS UART output
  4. Send ARP request and verify response
  5. Send ICMP ping and verify response

Usage:
    uv run python host/test_ethernet.py --board arty --uart-port /dev/ttyUSB1
    uv run python host/test_ethernet.py --board netv2 --uart-port /dev/ttyAMA0

Requires root (sudo) for network interface configuration and arping.
"""

import argparse
import re
import subprocess
import sys
import time

import serial


# -- Constants -----------------------------------------------------------------

FPGA_IP      = "192.168.1.50"
HOST_IP      = "192.168.1.100"
NETMASK      = "255.255.255.0"
BIOS_TIMEOUT = 30  # seconds to wait for BIOS boot

# USB Ethernet adapter identification for Arty Pi hosts.
# Each RPi has a different USB Ethernet adapter connected to the Arty's
# Ethernet port.  We detect by USB vendor/product strings.
USB_ETH_IDENTIFIERS = [
    "dm9601",       # DM9601 (pi3)
    "ax88179",      # ASIX AX88179 (pi9)
    "cdc_ether",    # Linksys / generic CDC (pi5)
    "r8152",        # Realtek USB Ethernet
    "asix",         # ASIX generic
]


# -- Network interface detection -----------------------------------------------

def find_usb_ethernet_interface():
    """Find the network interface name of the USB Ethernet adapter.

    Returns the interface name (e.g., 'eth1', 'enx60e0...') or None.
    We identify USB Ethernet adapters by checking sysfs for USB bus paths.
    """
    result = subprocess.run(
        ["ip", "-o", "link", "show"],
        capture_output=True, text=True, check=True,
    )
    interfaces = []
    for line in result.stdout.strip().split("\n"):
        # Format: "2: eth1: <BROADCAST,MULTICAST> mtu 1500 ..."
        match = re.match(r"\d+:\s+(\S+):", line)
        if not match:
            continue
        iface = match.group(1)
        if iface == "lo":
            continue
        # Check if this is a USB device by looking at sysfs
        try:
            sysfs_path = f"/sys/class/net/{iface}/device"
            import os
            real_path = os.path.realpath(sysfs_path)
            if "/usb" in real_path:
                interfaces.append(iface)
        except (OSError, FileNotFoundError):
            continue

    if len(interfaces) == 0:
        return None
    if len(interfaces) == 1:
        return interfaces[0]

    # Multiple USB Ethernet adapters -- try to pick the one that isn't the
    # RPi's main connection (skip the one with a default route)
    result = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True, check=True,
    )
    default_iface = None
    match = re.search(r"dev\s+(\S+)", result.stdout)
    if match:
        default_iface = match.group(1)

    for iface in interfaces:
        if iface != default_iface:
            return iface

    return interfaces[0]


def configure_interface(iface, ip, netmask):
    """Configure network interface with static IP."""
    print(f"Configuring {iface} with {ip}/{netmask}...")
    subprocess.run(
        ["sudo", "ip", "addr", "flush", "dev", iface],
        check=True,
    )
    subprocess.run(
        ["sudo", "ip", "addr", "add", f"{ip}/24", "dev", iface],
        check=True,
    )
    subprocess.run(
        ["sudo", "ip", "link", "set", iface, "up"],
        check=True,
    )
    # Wait for link to come up
    time.sleep(2)
    print(f"  {iface} configured: {ip}/24")


# -- UART MAC address parsing ---------------------------------------------------

def read_mac_from_bios(uart_port, baud=115200, timeout=None):
    """Read MAC address from LiteX BIOS boot output over UART.

    The BIOS prints a line like:
      Initializing Ethernet MAC @ <mac_address>...
    or:
      mac: 10:e2:d5:00:00:00
    or:
      Network config: MAC: 10:e2:d5:00:00:00

    Returns MAC address string or None.
    """
    timeout = timeout or BIOS_TIMEOUT
    ser = serial.Serial(uart_port, baud, timeout=1)
    ser.reset_input_buffer()

    mac_pattern = re.compile(
        r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:"
        r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})"
    )

    deadline = time.time() + timeout
    bios_output = []
    mac_address = None

    print(f"Reading BIOS output from {uart_port}...")
    while time.time() < deadline:
        line = ser.readline().decode(errors="replace").strip()
        if not line:
            continue
        bios_output.append(line)
        print(f"  BIOS: {line}")

        # Look for MAC address in the output
        match = mac_pattern.search(line)
        if match:
            mac_address = match.group(1).lower()
            print(f"  Found MAC: {mac_address}")

        # BIOS is done booting when it shows the prompt
        if "litex>" in line.lower() or "RUNTIME" in line:
            break

    ser.close()
    return mac_address, bios_output


# -- Network tests --------------------------------------------------------------

def test_arp(fpga_ip, interface, timeout=5):
    """Send ARP request and verify response. Returns (success, mac_from_arp)."""
    print(f"ARP test: arping {fpga_ip} on {interface}...")
    result = subprocess.run(
        ["sudo", "arping", "-c", "3", "-w", str(timeout), "-I", interface, fpga_ip],
        capture_output=True, text=True,
    )
    print(f"  stdout: {result.stdout.strip()}")

    # Check for successful ARP reply
    if result.returncode == 0:
        # Extract MAC from arping output
        mac_match = re.search(
            r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:"
            r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})",
            result.stdout,
        )
        mac = mac_match.group(1).lower() if mac_match else None
        return True, mac
    return False, None


def test_ping(fpga_ip, interface, count=5, timeout=2):
    """Send ICMP ping and verify response. Returns (success, stats_line)."""
    print(f"Ping test: ping {fpga_ip} via {interface}...")
    result = subprocess.run(
        ["ping", "-c", str(count), "-W", str(timeout), "-I", interface, fpga_ip],
        capture_output=True, text=True,
    )
    print(f"  stdout: {result.stdout.strip()}")

    # Parse packet loss
    loss_match = re.search(r"(\d+)% packet loss", result.stdout)
    if loss_match:
        loss = int(loss_match.group(1))
        stats_line = result.stdout.strip().split("\n")[-1]  # rtt summary
        return loss < 100, stats_line

    return result.returncode == 0, ""


# -- Main test runner -----------------------------------------------------------

def run_test(board, uart_port, baud, eth_interface=None):
    """Run the full Ethernet test sequence."""
    total_tests = 0
    failures = []

    print(f"=== Ethernet Test ({board}) ===")
    print(f"UART:     {uart_port} @ {baud}")
    print(f"FPGA IP:  {FPGA_IP}")
    print(f"Host IP:  {HOST_IP}")
    print()

    # Step 1: Detect USB Ethernet adapter
    if eth_interface:
        iface = eth_interface
    else:
        print("Detecting USB Ethernet adapter...", end=" ", flush=True)
        iface = find_usb_ethernet_interface()
        if not iface:
            print("FAIL - no USB Ethernet adapter found")
            return False
        print(f"found: {iface}")

    # Step 2: Configure interface
    configure_interface(iface, HOST_IP, NETMASK)

    # Step 3: Read MAC from BIOS UART
    print()
    mac_address, _ = read_mac_from_bios(uart_port, baud)
    total_tests += 1
    if mac_address:
        # Validate MAC is in LiteX default range (10:e2:d5:xx:xx:xx)
        if mac_address.startswith("10:e2:d5:"):
            print(f"  MAC address valid: {mac_address}")
        else:
            print(f"  MAC address unexpected prefix: {mac_address} (not 10:e2:d5:*)")
            # Still pass -- custom MAC is valid
    else:
        print("  FAIL: Could not read MAC address from BIOS output")
        failures.append("MAC address not found in BIOS output")

    # Step 4: ARP test
    print()
    total_tests += 1
    arp_ok, arp_mac = test_arp(FPGA_IP, iface)
    if arp_ok:
        print(f"  ARP: PASS (MAC={arp_mac})")
        # Cross-check MAC if we got it from BIOS too
        if mac_address and arp_mac and mac_address != arp_mac:
            print(f"  WARNING: BIOS MAC ({mac_address}) != ARP MAC ({arp_mac})")
    else:
        print("  ARP: FAIL")
        failures.append("ARP request got no response")

    # Step 5: ICMP ping test
    print()
    total_tests += 1
    ping_ok, ping_stats = test_ping(FPGA_IP, iface)
    if ping_ok:
        print(f"  Ping: PASS ({ping_stats})")
    else:
        print("  Ping: FAIL")
        failures.append("ICMP ping failed")

    # Results
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
    parser = argparse.ArgumentParser(description="Ethernet Test (host-side)")
    parser.add_argument("--board",      required=True, choices=["arty", "netv2"], help="Target board")
    parser.add_argument("--uart-port",  default=None,  help="UART port (default: /dev/ttyUSB1 for arty, /dev/ttyAMA0 for netv2)")
    parser.add_argument("--baud",       type=int, default=115200)
    parser.add_argument("--interface",  default=None,  help="Network interface (auto-detect if not specified)")
    args = parser.parse_args()

    if args.uart_port is None:
        args.uart_port = "/dev/ttyUSB1" if args.board == "arty" else "/dev/ttyAMA0"

    success = run_test(args.board, args.uart_port, args.baud, args.interface)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/ethernet-test/host/test_ethernet.py
git commit -m "ethernet-test: add host-side test script (MAC parse, ARP, ping)"
```

---

### Task 3: Write LiteX SoC with Ethernet for NeTV2
**Files:**
- Create: `designs/ethernet-test/gateware/ethernet_soc_netv2.py`

**Step 1: Write the NeTV2 Ethernet SoC**
```python
#!/usr/bin/env python3
# designs/ethernet-test/gateware/ethernet_soc_netv2.py
"""LiteX SoC with LiteEth (RMII) for NeTV2 Ethernet testing.

The NeTV2 has an independent RMII 100Base-T Ethernet PHY with:
  - RMII reference clock on pin D17 (50 MHz)
  - Separate RJ45 jack (not shared with the RPi's Ethernet)

This builds a standard LiteX SoC using the kosagi_netv2 target with
--with-ethernet and --with-sdram enabled.
"""

import argparse

from litex.soc.integration.builder import Builder

from litex_boards.targets.kosagi_netv2 import BaseSoC


def main():
    parser = argparse.ArgumentParser(description="Ethernet Test SoC for NeTV2")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream")
    args = parser.parse_args()

    soc = BaseSoC(
        variant=args.variant,
        toolchain=args.toolchain,
        sys_clk_freq=50e6,
        with_ethernet=True,
        with_sdram=True,
        uart_baudrate=115200,
        ident="Ethernet Test SoC (NeTV2)",
        ident_version=True,
    )

    builder = Builder(soc, output_dir="build/netv2")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/ethernet-test/gateware/ethernet_soc_netv2.py
git commit -m "ethernet-test: add LiteX SoC with LiteEth RMII for NeTV2"
```

---

### Task 4: GitHub Actions Workflow
**Files:**
- Create: `.github/workflows/ethernet-test-build.yml`

**Step 1: Write the CI workflow**
```yaml
# .github/workflows/ethernet-test-build.yml
name: "Build: Ethernet Test"

on:
  push:
    paths:
      - "designs/ethernet-test/**"
      - ".github/workflows/ethernet-test-build.yml"
  pull_request:
    paths:
      - "designs/ethernet-test/**"

jobs:
  build-arty:
    name: "Arty A7-35T (MII Ethernet)"
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
        working-directory: designs/ethernet-test
        run: uv sync

      - name: Build Arty Ethernet SoC
        working-directory: designs/ethernet-test
        run: |
          uv run python gateware/ethernet_soc_arty.py \
            --variant a7-35 \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream
        uses: actions/upload-artifact@v4
        with:
          name: ethernet-test-arty-a7-35t
          path: designs/ethernet-test/build/arty/gateware/digilent_arty.bit

  build-netv2:
    name: "NeTV2 (RMII Ethernet)"
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
        working-directory: designs/ethernet-test
        run: uv sync

      - name: Build NeTV2 Ethernet SoC
        working-directory: designs/ethernet-test
        run: |
          uv run python gateware/ethernet_soc_netv2.py \
            --variant a7-35 \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream
        uses: actions/upload-artifact@v4
        with:
          name: ethernet-test-netv2
          path: designs/ethernet-test/build/netv2/gateware/kosagi_netv2.bit

  lint:
    name: "Lint Python"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Lint
        working-directory: designs/ethernet-test
        run: uv run ruff check gateware/ host/
```

**Step 2: Commit**
```bash
git add .github/workflows/ethernet-test-build.yml
git commit -m "ethernet-test: add GitHub Actions workflow for Arty + NeTV2 builds"
```

---

### Task 5: Create Pull Request
**Step 1: Push branch to remote**
```bash
git push -u origin feature/ethernet-test
```

**Step 2: Create pull request**
```bash
gh pr create --title "Add Ethernet test design for Arty A7 and NeTV2" --body "$(cat <<'EOF'
## Summary
- LiteX SoC targets with LiteEth for Arty A7 (MII) and NeTV2 (RMII)
- Host-side Python test script with MAC parsing, ARP, and ICMP ping
- GitHub Actions workflow for bitstream builds
- Makefile for local builds and testing

## Test plan
- [ ] Verify SoC targets parse with `--help` flag
- [ ] Verify host script parses with `--help` flag
- [ ] CI builds bitstreams successfully

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 3: Clean up worktree (after PR is merged)**
```bash
cd /home/tim/github/mithro/fpgas-online-test-designs
git worktree remove .worktrees/ethernet-test
git branch -d feature/ethernet-test
```
