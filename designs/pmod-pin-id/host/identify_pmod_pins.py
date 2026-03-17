#!/usr/bin/env python3
"""Scan RPi GPIO pins and decode FPGA pin identification strings.

The FPGA continuously transmits each pin's FPGA ball name (e.g. "G13\\r\\n")
at 1200 baud 8N1. This script reads each RPi GPIO pin, decodes the UART
data via software bit-banging, and reports the mapping.

Usage:
    # Scan all PMOD HAT GPIOs (default for Arty setup)
    uv run python host/identify_pmod_pins.py

    # Scan specific GPIOs
    uv run python host/identify_pmod_pins.py --gpios 6 13 19 26

    # Use a predefined HAT port list
    uv run python host/identify_pmod_pins.py --hat-port JA

Requirements:
    - Raspberry Pi with PMOD HAT connected to FPGA
    - FPGA programmed with matching pmod_pin_id bitstream
    - python3-libgpiod installed (v1.6+ or v2.x)
"""

import argparse
import pathlib
import subprocess
import sys
import time

import gpiod

# -- PMOD HAT GPIO definitions ------------------------------------------------

# RPi BCM GPIO numbers for each PMOD HAT port, in PMOD pin order
# (pins 1-4 top row, pins 7-10 bottom row).
# Source: DesignSpark.Pmod HAT.py driver + Digilent PMOD HAT schematic.
# Note: JA pins 2-4 and JB pins 2-4 share the same GPIOs (SPI bus).
PMOD_HAT_PORTS = {
    "JA": [8, 10, 9, 11, 19, 21, 20, 18],
    "JB": [7, 10, 9, 11, 26, 13, 3, 2],
    "JC": [16, 14, 15, 17, 4, 12, 5, 6],
}

# All PMOD HAT GPIOs in a flat list (deduplicated, since JA/JB share pins 2-4).
_seen = set()
ALL_HAT_GPIOS = []
for port_name in ["JA", "JB", "JC"]:
    for gpio in PMOD_HAT_PORTS[port_name]:
        if gpio not in _seen:
            _seen.add(gpio)
            ALL_HAT_GPIOS.append(gpio)

# PMOD HAT pin labels for display (port + physical pin number).
HAT_GPIO_LABELS = {}
for port_name, gpios in PMOD_HAT_PORTS.items():
    pmod_phys = [1, 2, 3, 4, 7, 8, 9, 10]
    for gpio, phys in zip(gpios, pmod_phys):
        HAT_GPIO_LABELS[gpio] = f"HAT {port_name} pin {phys:02d}"

# -- UART bit-bang parameters --------------------------------------------------

BAUD_RATE = 1200
BIT_PERIOD = 1.0 / BAUD_RATE  # ~833µs


# -- GPIO chip detection -------------------------------------------------------

GPIO_CHIP_LABELS = {
    "pinctrl-rp1",       # RPi 5
    "pinctrl-bcm2711",   # RPi 4
    "pinctrl-bcm2835",   # RPi 3 / Zero
}

_GPIOD_V2 = hasattr(gpiod, "request_lines")


def detect_gpio_chip():
    """Find the gpiochip device for RPi GPIO by label."""
    for chip_path in sorted(pathlib.Path("/dev").glob("gpiochip*")):
        try:
            chip = gpiod.Chip(str(chip_path))
            label = chip.get_info().label if _GPIOD_V2 else chip.label()
            chip.close()
            if label in GPIO_CHIP_LABELS:
                return str(chip_path)
        except (OSError, PermissionError):
            continue
    raise RuntimeError(
        "Cannot find GPIO chip with a known label. Is this a Raspberry Pi?"
    )


# -- Single-pin GPIO reader ---------------------------------------------------

class GpioReader:
    """Read a single GPIO pin using gpiod (v1 or v2)."""

    def __init__(self, gpio_num, chip_path):
        self.gpio_num = gpio_num
        self.chip_path = chip_path
        self._request = None  # v2
        self._chip = None     # v1
        self._line = None     # v1

    def open(self):
        if _GPIOD_V2:
            self._request = gpiod.request_lines(
                self.chip_path,
                consumer="pmod-pin-id",
                config={
                    (self.gpio_num,): gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT,
                        bias=gpiod.line.Bias.PULL_UP,
                    ),
                },
            )
        else:
            self._chip = gpiod.Chip(self.chip_path)
            self._line = self._chip.get_line(self.gpio_num)
            self._line.request(
                consumer="pmod-pin-id",
                type=gpiod.LINE_REQ_DIR_IN,
                flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
            )

    def read(self):
        if _GPIOD_V2:
            val = self._request.get_values()
            return 1 if val[0] == gpiod.line.Value.ACTIVE else 0
        else:
            return self._line.get_value()

    def close(self):
        if _GPIOD_V2:
            if self._request:
                self._request.release()
                self._request = None
        else:
            if self._line:
                self._line.release()
                self._line = None
            if self._chip:
                self._chip.close()
                self._chip = None


# -- UART bit-bang decoder -----------------------------------------------------

def receive_byte(reader, timeout=0.1):
    """Receive one UART byte (8N1) by bit-banging.

    Properly synchronizes to the HIGH→LOW transition (start bit edge)
    to avoid sampling mid-byte. Samples 8 data bits at the center of
    each bit period.

    Returns the decoded byte, or None on timeout.
    """
    deadline = time.monotonic() + timeout

    # First wait for line to be HIGH (idle/stop-bit state).
    # This ensures we don't mistake a mid-byte LOW for a start bit.
    while reader.read() == 0:
        if time.monotonic() > deadline:
            return None

    # Now wait for the HIGH→LOW transition (actual start bit edge).
    while reader.read() != 0:
        if time.monotonic() > deadline:
            return None

    # We detected the falling edge. Wait half a bit period to reach
    # the center of the start bit, then verify it's still low.
    start_edge = time.monotonic()
    target = start_edge + BIT_PERIOD * 0.5
    while time.monotonic() < target:
        pass
    if reader.read() != 0:
        return None  # False start (glitch)

    # Sample 8 data bits at the center of each bit period.
    byte_val = 0
    for bit_idx in range(8):
        target = start_edge + BIT_PERIOD * (1.5 + bit_idx)
        while time.monotonic() < target:
            pass
        if reader.read():
            byte_val |= (1 << bit_idx)

    # Wait through the stop bit.
    target = start_edge + BIT_PERIOD * 9.5
    while time.monotonic() < target:
        pass

    return byte_val


def receive_label(reader, max_bytes=20, timeout=0.2):
    """Receive bytes until \\n is seen or timeout, return decoded string.

    Returns the label string (excluding \\r\\n), or None if nothing received.
    """
    buf = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        b = receive_byte(reader, timeout=remaining)
        if b is None:
            break
        if b == ord('\n'):
            # Strip trailing \r if present.
            text = bytes(buf).decode('ascii', errors='replace').rstrip('\r')
            return text
        buf.append(b)
        if len(buf) >= max_bytes:
            break
    # If we got some bytes but no newline, return what we have.
    if buf:
        return bytes(buf).decode('ascii', errors='replace').rstrip('\r')
    return None


# Expected label format: FPGA pin names are 2-4 alphanumeric characters.
# Examples: "G13", "B11", "A9", "K16", "V14" (Xilinx 7-series ball names)
# Also accepts PMOD-style names like "JA01" for backwards compatibility.
import re
_LABEL_PATTERN = re.compile(r'^[A-Z][A-Za-z0-9]{1,3}$')


def is_valid_label(label):
    """Check if a decoded label looks like a valid pin identifier."""
    return bool(_LABEL_PATTERN.match(label))


def identify_pin(reader, attempts=10):
    """Read the pin label, trying multiple times for reliability.

    Only accepts labels matching the expected format (e.g. "JA01").
    Returns the label string if consistently decoded, or None.
    """
    valid_results = []
    raw_results = []
    for _ in range(attempts):
        label = receive_label(reader)
        if label:
            raw_results.append(label)
            if is_valid_label(label):
                valid_results.append(label)
    if valid_results:
        from collections import Counter
        most_common, count = Counter(valid_results).most_common(1)[0]
        return most_common
    # Return raw data for debugging if we got signal but no valid decode.
    if raw_results:
        from collections import Counter
        most_common, count = Counter(raw_results).most_common(1)[0]
        return f"?{most_common}"  # Prefix with ? to flag as unvalidated
    return None


# -- Scanner -------------------------------------------------------------------

def scan_gpios(gpio_list, chip_path):
    """Scan a list of GPIO pins and return {gpio: label} mapping."""
    results = {}
    for gpio_num in gpio_list:
        hat_label = HAT_GPIO_LABELS.get(gpio_num, f"GPIO{gpio_num}")
        reader = GpioReader(gpio_num, chip_path)
        try:
            reader.open()
            label = identify_pin(reader)
            results[gpio_num] = label
            if label is None:
                print(f"  GPIO{gpio_num:2d} ({hat_label:20s}) -> (no signal)")
            elif label.startswith("?"):
                print(f"  GPIO{gpio_num:2d} ({hat_label:20s}) -> (garbled: {label[1:]!r})")
            else:
                print(f"  GPIO{gpio_num:2d} ({hat_label:20s}) -> {label}")
        except OSError as e:
            print(f"  GPIO{gpio_num:2d} ({hat_label:20s}) -> ERROR: {e}")
            results[gpio_num] = None
        finally:
            reader.close()
    return results


def print_mapping_table(results):
    """Print a formatted mapping table suitable for documentation."""
    valid = {gpio: label for gpio, label in results.items()
             if label and not label.startswith("?")}
    garbled = {gpio: label for gpio, label in results.items()
               if label and label.startswith("?")}
    no_signal = {gpio for gpio, label in results.items() if label is None}

    if not valid and not garbled:
        print("\nNo FPGA pins detected on any GPIO.")
        return

    print(f"\n=== Pin Mapping Table ({len(valid)} confirmed, "
          f"{len(garbled)} garbled, {len(no_signal)} no signal) ===\n")
    print("| RPi GPIO | HAT Location           | FPGA Pin |")
    print("|----------|------------------------|----------|")
    for gpio in sorted(valid.keys()):
        hat_label = HAT_GPIO_LABELS.get(gpio, f"GPIO{gpio}")
        fpga_pin = valid[gpio]
        print(f"| GPIO{gpio:<4d} | {hat_label:<22s} | {fpga_pin:<8s} |")

    # Also print by FPGA pin for reverse lookup.
    print("\n=== Reverse Mapping (by FPGA pin) ===\n")
    print("| FPGA Pin | RPi GPIO | HAT Location           |")
    print("|----------|----------|------------------------|")
    for gpio, fpga_pin in sorted(valid.items(), key=lambda x: x[1]):
        hat_label = HAT_GPIO_LABELS.get(gpio, f"GPIO{gpio}")
        print(f"| {fpga_pin:<8s} | GPIO{gpio:<4d} | {hat_label:<22s} |")

    if garbled:
        print("\n=== Garbled Pins (signal present, decode failed) ===\n")
        for gpio in sorted(garbled.keys()):
            hat_label = HAT_GPIO_LABELS.get(gpio, f"GPIO{gpio}")
            print(f"  GPIO{gpio:<4d} ({hat_label}): {garbled[gpio][1:]!r}")


# -- Kernel module management --------------------------------------------------

# Modules that claim GPIO pins used by PMOD HAT ports.
# SPI0 uses GPIO7-11 (JA pin 1, JB pin 1, and shared pins 2-4).
# I2C1 uses GPIO2-3 (JB pins 9-10). i2c_bcm2835 often can't be
# unloaded at runtime, but gpiod can usually still read these pins.
_MODULES_TO_UNLOAD = [
    "spidev",
    "spi_bcm2835",
]


def release_kernel_gpio_drivers():
    """Unload kernel modules that claim GPIO pins used by PMOD ports.

    SPI0 claims GPIO7-11 which are on HAT ports JA/JB pins 1-4.
    """
    unloaded = []
    for mod in _MODULES_TO_UNLOAD:
        result = subprocess.run(
            ["rmmod", mod], capture_output=True, text=True
        )
        if result.returncode == 0:
            unloaded.append(mod)
    if unloaded:
        print(f"Unloaded kernel modules: {', '.join(unloaded)}")
    else:
        print("No kernel modules needed unloading.")


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Identify FPGA pins via UART transmission at 1200 baud"
    )
    parser.add_argument(
        "--gpios", type=int, nargs="+",
        help="Specific GPIO numbers to scan"
    )
    parser.add_argument(
        "--hat-port", choices=["JA", "JB", "JC"],
        help="Scan all GPIOs on a specific PMOD HAT port"
    )
    parser.add_argument(
        "--no-unload", action="store_true",
        help="Skip unloading kernel modules (SPI, I2C)"
    )
    args = parser.parse_args()

    if args.gpios:
        gpio_list = args.gpios
    elif args.hat_port:
        gpio_list = PMOD_HAT_PORTS[args.hat_port]
    else:
        gpio_list = ALL_HAT_GPIOS

    if not args.no_unload:
        release_kernel_gpio_drivers()

    chip_path = detect_gpio_chip()

    print("=== FPGA Pin Identification Scanner ===")
    print(f"Baud rate:  {BAUD_RATE}")
    print(f"GPIO chip:  {chip_path}")
    print(f"Scanning:   {len(gpio_list)} GPIO pins")
    print()

    results = scan_gpios(gpio_list, chip_path)
    print_mapping_table(results)

    valid_count = sum(1 for v in results.values() if v and not v.startswith("?"))
    garbled_count = sum(1 for v in results.values() if v and v.startswith("?"))
    print(f"\n{valid_count}/{len(gpio_list)} pins identified"
          f" ({garbled_count} garbled).")
    sys.exit(0 if valid_count > 0 else 1)


if __name__ == "__main__":
    main()
