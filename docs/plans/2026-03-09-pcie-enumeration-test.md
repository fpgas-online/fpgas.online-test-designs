# PCIe Enumeration Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify that the NeTV2 FPGA's PCIe endpoint enumerates on the RPi5 PCIe bus after programming, confirming the Xilinx 7-Series hard IP PCIe block, physical link training, and Linux kernel device detection all work correctly.

**Architecture:** A LiteX SoC with LitePCIe endpoint is built for the NeTV2. The host-side script on the RPi5 programs the FPGA via OpenOCD JTAG (GPIO bitbang), triggers a PCIe bus rescan, then checks `lspci` for device 10ee:7011 and reads link speed/width and BAR allocation from sysfs. All checks are non-destructive reads -- no kernel module or DMA is required.

**Tech Stack:** LiteX with LitePCIe, openXC7 toolchain, OpenOCD (bcm2835gpio/linuxgpiod JTAG), Python 3 with subprocess, GitHub Actions CI

---

### Task 1: Create Project Structure
**Files:**
- Create: `designs/pcie-enumeration/pyproject.toml`
- Create: `designs/pcie-enumeration/Makefile`
- Create: `designs/pcie-enumeration/openocd/alphamax-rpi.cfg`

**Step 1: Create directory layout**
```bash
mkdir -p designs/pcie-enumeration/gateware
mkdir -p designs/pcie-enumeration/host
mkdir -p designs/pcie-enumeration/openocd
```

**Step 2: Write pyproject.toml**
```toml
# designs/pcie-enumeration/pyproject.toml
[project]
name = "pcie-enumeration-test"
version = "0.1.0"
description = "PCIe enumeration test for NeTV2 on RPi5"
requires-python = ">=3.9"
dependencies = [
    "litex",
    "litex-boards",
    "litepcie",
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
# designs/pcie-enumeration/Makefile
TOOLCHAIN      ?= yosys+nextpnr
VARIANT        ?= a7-35
BUILD_DIR      ?= build/netv2
OPENOCD_CFG    ?= openocd/alphamax-rpi.cfg
BITSTREAM      ?= $(BUILD_DIR)/gateware/kosagi_netv2.bit
UART_PORT      ?= /dev/ttyAMA0

.PHONY: gateware program test clean

gateware:
	uv run python gateware/pcie_soc_netv2.py \
		--variant $(VARIANT) \
		--toolchain $(TOOLCHAIN) \
		--build

program:
	openocd -f $(OPENOCD_CFG) -c "init; pld load 0 $(BITSTREAM); exit"

test:
	sudo uv run python host/test_pcie_enumeration.py

clean:
	rm -rf build/
```

**Step 4: Write OpenOCD configuration**
```tcl
# designs/pcie-enumeration/openocd/alphamax-rpi.cfg
#
# OpenOCD configuration for NeTV2 JTAG via Raspberry Pi GPIO.
# Works on RPi3/4 with bcm2835gpio.  RPi5 needs linuxgpiod (see below).
#
# GPIO mapping:
#   TCK  = GPIO4  (RPi header pin 7)
#   TMS  = GPIO17 (RPi header pin 11)
#   TDI  = GPIO27 (RPi header pin 13)
#   TDO  = GPIO22 (RPi header pin 15)
#   SRST = GPIO24 (RPi header pin 18)

# ---- Interface selection ----
# Uncomment ONE of the following blocks:

# For RPi 3/4 (bcm2835gpio):
adapter driver bcm2835gpio
bcm2835gpio peripheral_base 0x3F000000
bcm2835gpio speed_coeffs 100000 5
bcm2835gpio jtag_nums 4 17 27 22
bcm2835gpio srst_num 24

# For RPi 5 (linuxgpiod):
# adapter driver linuxgpiod
# linuxgpiod gpiochip 4
# linuxgpiod jtag_nums 4 17 27 22
# linuxgpiod srst_num 24

# ---- JTAG config ----
adapter speed 1000
transport select jtag
reset_config srst_only

# ---- Target: Xilinx XC7A35T ----
source [find cpld/xilinx-xc7.cfg]

# Override scan chain for the specific device
# XC7A35T IDCODE
jtag newtap xc7 tap -irlen 6 -expected-id 0x0362D093
```

**Step 5: Commit**
```bash
git add designs/pcie-enumeration/pyproject.toml \
       designs/pcie-enumeration/Makefile \
       designs/pcie-enumeration/openocd/alphamax-rpi.cfg
git commit -m "pcie-enumeration: add project structure with OpenOCD config"
```

---

### Task 2: Write LiteX SoC with PCIe Endpoint for NeTV2
**Files:**
- Create: `designs/pcie-enumeration/gateware/pcie_soc_netv2.py`

**Step 1: Write the PCIe SoC**
```python
#!/usr/bin/env python3
# designs/pcie-enumeration/gateware/pcie_soc_netv2.py
"""LiteX SoC with LitePCIe endpoint for NeTV2 PCIe enumeration testing.

Builds a LiteX SoC that includes:
  - VexRiscv CPU + BIOS + UART (115200 baud on /dev/ttyAMA0)
  - DDR3 SDRAM (512 MB)
  - LitePCIe endpoint using the Xilinx 7-Series hard IP PCIe block
    - Vendor ID: 0x10EE (Xilinx)
    - Device ID: 0x7011
    - PCIe Gen2 x1
    - BAR0 for Wishbone bridge access

The FPGA must be programmed via JTAG (OpenOCD) BEFORE the RPi5 scans
the PCIe bus.  After programming, the host triggers a bus rescan.

NeTV2 PCIe pinout:
  - CLK: F10 (P) / E10 (N)
  - RST_N: E18
  - Lane 0: RX D11/C11, TX D5/C5
"""

import argparse

from migen import *

from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore

from litex_boards.platforms import kosagi_netv2

# Try to import LitePCIe
try:
    from litepcie.phy.s7pciephy import S7PCIEPHY
    from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
    from litepcie.frontend.wishbone import LitePCIeWishboneBridge
    HAS_LITEPCIE = True
except ImportError:
    HAS_LITEPCIE = False
    print("WARNING: LitePCIe not installed.  Install with: pip install litepcie")


class PCIeEnumerationSoC(SoCCore):
    def __init__(self, variant="a7-35", toolchain="yosys+nextpnr", **kwargs):
        platform = kosagi_netv2.Platform(variant=variant, toolchain=toolchain)

        SoCCore.__init__(
            self,
            platform,
            sys_clk_freq=50e6,
            ident="PCIe Enumeration Test SoC (NeTV2)",
            ident_version=True,
            uart_baudrate=115200,
            **kwargs,
        )

        # Add DDR3 SDRAM
        from litex.soc.cores.sdram import SDRAMModule
        from litex.soc.integration.soc import SoCRegion
        from litedram.modules import MT41K256M16
        from litedram.phy import s7ddrphy

        self.ddrphy = s7ddrphy.A7DDRPHY(
            platform.request("ddram"),
            memtype="DDR3",
            nphases=4,
            sys_clk_freq=50e6,
        )
        self.add_sdram(
            "sdram",
            phy=self.ddrphy,
            module=MT41K256M16(50e6, "1:4"),
            l2_cache_size=8192,
        )

        # Add LitePCIe endpoint
        if not HAS_LITEPCIE:
            raise ImportError("LitePCIe is required. Install with: pip install litepcie")

        # PCIe PHY -- uses the Xilinx 7-Series integrated hard block
        self.pcie_phy = S7PCIEPHY(
            platform,
            platform.request("pcie_x1"),
            data_width=64,
            bar0_size=0x20000,  # 128 KB BAR0
        )
        self.add_module(name="pcie_phy", module=self.pcie_phy)

        # PCIe endpoint
        self.pcie_endpoint = LitePCIeEndpoint(self.pcie_phy, max_pending_requests=4)

        # PCIe Wishbone bridge (allows host to access SoC registers via BAR0)
        self.pcie_bridge = LitePCIeWishboneBridge(
            self.pcie_endpoint, base_address=self.bus.regions["main_ram"].origin
        )
        self.bus.add_master(master=self.pcie_bridge.wishbone)

        # PCIe MSI (Message Signaled Interrupts)
        self.pcie_msi = LitePCIeMSI()
        self.add_module(name="pcie_msi", module=self.pcie_msi)

        # Connect MSI to PHY
        self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)

        # PCIe interrupt (active low reset from connector)
        platform.add_period_constraint(self.pcie_phy.cd_pcie.clk, 1e9 / 62.5e6)


def main():
    parser = argparse.ArgumentParser(description="PCIe Enumeration Test SoC for NeTV2")
    parser.add_argument("--variant",    default="a7-35",         help="a7-35 or a7-100")
    parser.add_argument("--toolchain",  default="yosys+nextpnr", help="vivado or yosys+nextpnr")
    parser.add_argument("--build",      action="store_true",     help="Build bitstream")
    parser.add_argument("--load",       action="store_true",     help="Load bitstream via OpenOCD")
    args = parser.parse_args()

    soc = PCIeEnumerationSoC(variant=args.variant, toolchain=args.toolchain)

    builder = Builder(soc, output_dir="build/netv2")
    builder.build(run=args.build)

    if args.load:
        import subprocess
        bitstream = builder.get_bitstream_filename(mode="sram")
        subprocess.run(
            ["openocd", "-f", "openocd/alphamax-rpi.cfg",
             "-c", f"init; pld load 0 {bitstream}; exit"],
            check=True,
        )


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/pcie-enumeration/gateware/pcie_soc_netv2.py
git commit -m "pcie-enumeration: add LiteX SoC with LitePCIe endpoint for NeTV2"
```

---

### Task 3: Write Host-Side PCIe Enumeration Test Script
**Files:**
- Create: `designs/pcie-enumeration/host/test_pcie_enumeration.py`

**Step 1: Write the test script**
```python
#!/usr/bin/env python3
# designs/pcie-enumeration/host/test_pcie_enumeration.py
"""Host-side PCIe enumeration test for NeTV2 on RPi5.

This script verifies that the NeTV2 FPGA's PCIe endpoint is properly
detected by the Linux kernel after JTAG programming.

Steps:
  1. Optionally program the FPGA via OpenOCD
  2. Trigger PCIe bus rescan
  3. Check lspci for device 10ee:7011
  4. Verify link speed and width from sysfs
  5. Verify BAR allocation

Requirements:
  - RPi5 with NeTV2 connected via PCIe
  - Root access (sudo) for PCIe rescan and lspci
  - FPGA must be programmed BEFORE running this test (or use --program flag)

Usage:
    sudo uv run python host/test_pcie_enumeration.py
    sudo uv run python host/test_pcie_enumeration.py --program --bitstream build/netv2/gateware/kosagi_netv2.bit
"""

import argparse
import os
import re
import subprocess
import sys
import time


# -- Constants -----------------------------------------------------------------

VENDOR_ID = "10ee"   # Xilinx Corporation
DEVICE_ID = "7011"   # 7-Series PCIe endpoint (LitePCIe default)
EXPECTED_LINK_SPEEDS = ["2.5 GT/s", "5 GT/s"]  # Gen1 or Gen2
EXPECTED_LINK_WIDTH  = "x1"
OPENOCD_CFG = "openocd/alphamax-rpi.cfg"


# -- FPGA programming ----------------------------------------------------------

def program_fpga(bitstream, openocd_cfg=OPENOCD_CFG):
    """Program the NeTV2 FPGA via OpenOCD JTAG."""
    print(f"Programming FPGA with {bitstream}...")
    if not os.path.exists(bitstream):
        print(f"  ERROR: Bitstream file not found: {bitstream}")
        return False

    result = subprocess.run(
        ["openocd", "-f", openocd_cfg,
         "-c", f"init; pld load 0 {bitstream}; exit"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: OpenOCD failed:\n{result.stderr}")
        return False

    print("  FPGA programmed successfully")
    # Give the FPGA time to initialize
    time.sleep(1)
    return True


# -- PCIe bus rescan ------------------------------------------------------------

def pcie_rescan():
    """Trigger a PCIe bus rescan."""
    print("Rescanning PCIe bus...")
    rescan_path = "/sys/bus/pci/rescan"
    try:
        with open(rescan_path, "w") as f:
            f.write("1")
        print("  Rescan triggered")
        # Wait for enumeration to complete
        time.sleep(2)
        return True
    except PermissionError:
        print(f"  ERROR: Permission denied writing to {rescan_path}")
        print("  This script must run as root (sudo)")
        return False
    except OSError as e:
        print(f"  ERROR: {e}")
        return False


# -- Device detection -----------------------------------------------------------

def find_pcie_device(vendor, device):
    """Find PCIe device by vendor:device ID.  Returns BDF string or None.

    BDF format: "0000:XX:YY.Z"
    """
    result = subprocess.run(
        ["lspci", "-n", "-d", f"{vendor}:{device}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    # First line: "XX:YY.Z Class VVVV:DDDD"
    line = result.stdout.strip().split("\n")[0]
    bdf_short = line.split()[0]  # "XX:YY.Z"
    return f"0000:{bdf_short}"


def get_device_info(vendor, device):
    """Get detailed device info from lspci -vvv."""
    result = subprocess.run(
        ["lspci", "-vvv", "-d", f"{vendor}:{device}"],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else ""


# -- Link verification ---------------------------------------------------------

def check_link_status(lspci_output):
    """Parse link capability and status from lspci -vvv output.

    Returns dict with keys: link_speed, link_width, link_cap_speed, link_cap_width
    """
    info = {}

    # Link Capabilities: ... Speed 5GT/s, Width x1 ...
    cap_match = re.search(r"LnkCap:.*Speed\s+(\S+),\s+Width\s+(\S+)", lspci_output)
    if cap_match:
        info["link_cap_speed"] = cap_match.group(1)
        info["link_cap_width"] = cap_match.group(2)

    # Link Status: Speed 5GT/s, Width x1
    sta_match = re.search(r"LnkSta:.*Speed\s+(\S+).*Width\s+(\S+)", lspci_output)
    if sta_match:
        info["link_speed"] = sta_match.group(1)
        info["link_width"] = sta_match.group(2)

    return info


def check_link_from_sysfs(bdf):
    """Read link speed and width from sysfs as a fallback."""
    info = {}
    sysfs_dir = f"/sys/bus/pci/devices/{bdf}"

    for attr, key in [("current_link_speed", "link_speed"),
                      ("current_link_width", "link_width")]:
        path = os.path.join(sysfs_dir, attr)
        try:
            with open(path) as f:
                info[key] = f.read().strip()
        except (OSError, FileNotFoundError):
            pass

    return info


# -- BAR verification -----------------------------------------------------------

def check_bars(lspci_output):
    """Parse BAR allocations from lspci -vvv output.

    Returns list of (region_num, type, address, size) tuples.
    """
    bars = []
    # Region 0: Memory at f0000000 (32-bit, non-prefetchable) [size=128K]
    for match in re.finditer(
        r"Region\s+(\d+):\s+(\S+)\s+at\s+(\S+)\s+.*\[size=([^\]]+)\]",
        lspci_output
    ):
        bars.append({
            "region":  int(match.group(1)),
            "type":    match.group(2),
            "address": match.group(3),
            "size":    match.group(4),
        })
    return bars


# -- Config space verification --------------------------------------------------

def check_config_space(bdf):
    """Read vendor and device ID from config space using setpci."""
    info = {}
    for reg, key in [("VENDOR_ID.w", "vendor_id"), ("DEVICE_ID.w", "device_id")]:
        result = subprocess.run(
            ["setpci", "-s", bdf, reg],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            info[key] = result.stdout.strip().lower()
    return info


# -- Main test runner -----------------------------------------------------------

def run_test(program=False, bitstream=None, openocd_cfg=OPENOCD_CFG):
    """Run the full PCIe enumeration test."""
    total_tests = 0
    failures = []

    print("=== PCIe Enumeration Test (NeTV2 on RPi5) ===")
    print(f"Expected device: {VENDOR_ID}:{DEVICE_ID}")
    print()

    # Step 0: Optionally program the FPGA
    if program:
        if not bitstream:
            print("ERROR: --bitstream required when using --program")
            return False
        if not program_fpga(bitstream, openocd_cfg):
            return False
        print()

    # Step 1: PCIe bus rescan
    total_tests += 1
    if not pcie_rescan():
        failures.append("PCIe bus rescan failed")
        # Can't continue without rescan
        print(f"\n=== Results: 0/{total_tests} passed ===")
        return False
    print()

    # Step 2: Device detection
    total_tests += 1
    print(f"Looking for device {VENDOR_ID}:{DEVICE_ID}...")
    bdf = find_pcie_device(VENDOR_ID, DEVICE_ID)
    if bdf:
        print(f"  FOUND at {bdf}")
    else:
        print(f"  NOT FOUND")
        failures.append(f"Device {VENDOR_ID}:{DEVICE_ID} not found in lspci")
        # Can't continue without device
        print(f"\n=== Results: {total_tests - len(failures)}/{total_tests} passed ===")
        print("Failures:")
        for f in failures:
            print(f"  - {f}")

        # Show all PCIe devices for debugging
        print("\nAll PCIe devices:")
        result = subprocess.run(["lspci"], capture_output=True, text=True)
        print(result.stdout)
        return False

    # Step 3: Get detailed device info
    device_info = get_device_info(VENDOR_ID, DEVICE_ID)
    print()
    print("Device details:")
    # Print first few lines
    for line in device_info.split("\n")[:5]:
        if line.strip():
            print(f"  {line.strip()}")

    # Step 4: Verify config space
    total_tests += 1
    print()
    print("Config space check...")
    config = check_config_space(bdf)
    if config.get("vendor_id") == VENDOR_ID and config.get("device_id") == DEVICE_ID:
        print(f"  Vendor ID: {config['vendor_id']} (expected {VENDOR_ID}) - OK")
        print(f"  Device ID: {config['device_id']} (expected {DEVICE_ID}) - OK")
    else:
        print(f"  Config space mismatch: {config}")
        failures.append(f"Config space vendor/device mismatch: {config}")

    # Step 5: Link status
    total_tests += 1
    print()
    print("Link status...")
    link_info = check_link_status(device_info)
    if not link_info:
        # Fallback to sysfs
        link_info = check_link_from_sysfs(bdf)

    link_speed = link_info.get("link_speed", "unknown")
    link_width = link_info.get("link_width", "unknown")

    speed_ok = any(s in link_speed for s in ["2.5", "5"])
    width_ok = "x1" in link_width or "1" == link_width

    if speed_ok:
        print(f"  Link speed: {link_speed} - OK")
    else:
        print(f"  Link speed: {link_speed} - FAIL (expected 2.5 GT/s or 5 GT/s)")
        failures.append(f"Link speed unexpected: {link_speed}")

    if width_ok:
        print(f"  Link width: {link_width} - OK")
    else:
        print(f"  Link width: {link_width} - FAIL (expected x1)")
        failures.append(f"Link width unexpected: {link_width}")

    # Also print capabilities if available
    if "link_cap_speed" in link_info:
        print(f"  Link capability: {link_info['link_cap_speed']}, {link_info.get('link_cap_width', '?')}")

    # Step 6: BAR allocation
    total_tests += 1
    print()
    print("BAR allocation...")
    bars = check_bars(device_info)
    if bars:
        for bar in bars:
            addr = bar["address"]
            is_allocated = addr != "0000000000000000" and addr != "00000000"
            status = "OK" if is_allocated else "FAIL (not allocated)"
            print(f"  Region {bar['region']}: {bar['type']} at {addr} [{bar['size']}] - {status}")
            if not is_allocated:
                failures.append(f"BAR {bar['region']} not allocated")
    else:
        print("  No BARs found in lspci output")
        failures.append("No BAR regions found")

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
    parser = argparse.ArgumentParser(description="PCIe Enumeration Test (host-side)")
    parser.add_argument("--program",     action="store_true",     help="Program FPGA before testing")
    parser.add_argument("--bitstream",   default=None,            help="Path to bitstream file")
    parser.add_argument("--openocd-cfg", default=OPENOCD_CFG,     help="OpenOCD config file")
    parser.add_argument("--skip-rescan", action="store_true",     help="Skip PCIe bus rescan")
    args = parser.parse_args()

    success = run_test(
        program=args.program,
        bitstream=args.bitstream,
        openocd_cfg=args.openocd_cfg,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add designs/pcie-enumeration/host/test_pcie_enumeration.py
git commit -m "pcie-enumeration: add host-side test script (rescan, lspci, sysfs, BAR checks)"
```

---

### Task 4: GitHub Actions Workflow
**Files:**
- Create: `.github/workflows/pcie-enumeration-build.yml`

**Step 1: Write the CI workflow**
```yaml
# .github/workflows/pcie-enumeration-build.yml
name: "Build: PCIe Enumeration"

on:
  push:
    paths:
      - "designs/pcie-enumeration/**"
      - ".github/workflows/pcie-enumeration-build.yml"
  pull_request:
    paths:
      - "designs/pcie-enumeration/**"

jobs:
  build-netv2:
    name: "NeTV2 PCIe endpoint"
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
        working-directory: designs/pcie-enumeration
        run: uv sync

      - name: Build PCIe SoC bitstream
        working-directory: designs/pcie-enumeration
        run: |
          uv run python gateware/pcie_soc_netv2.py \
            --variant a7-35 \
            --toolchain yosys+nextpnr \
            --build

      - name: Upload bitstream
        uses: actions/upload-artifact@v4
        with:
          name: pcie-enumeration-netv2
          path: designs/pcie-enumeration/build/netv2/gateware/kosagi_netv2.bit

  lint:
    name: "Lint Python"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Lint
        working-directory: designs/pcie-enumeration
        run: uv run ruff check gateware/ host/
```

**Step 2: Commit**
```bash
git add .github/workflows/pcie-enumeration-build.yml
git commit -m "pcie-enumeration: add GitHub Actions workflow for NeTV2 bitstream build"
```
