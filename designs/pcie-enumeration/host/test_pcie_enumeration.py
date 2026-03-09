#!/usr/bin/env python3
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
