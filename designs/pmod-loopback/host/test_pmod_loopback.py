#!/usr/bin/env python3
# designs/pmod-loopback/host/test_pmod_loopback.py
"""Host-side GPIO loopback test script.

Runs on the Raspberry Pi. Drives one set of GPIO pins and reads another set
to verify that the FPGA performs output = ~input (bitwise inversion).

No UART or serial communication — purely GPIO-based.

Usage:
    uv run python host/test_pmod_loopback.py --board arty
    uv run python host/test_pmod_loopback.py --board netv2
    uv run python host/test_pmod_loopback.py --board fomu

Requirements:
    - Raspberry Pi with appropriate wiring to the FPGA board
    - FPGA programmed with the matching gpio_loopback bitstream
    - libgpiod2 installed (apt install libgpiod2 python3-libgpiod)
"""

import argparse
import sys
import time

import gpiod


# -- Board-specific pin configurations ----------------------------------------
# Pin mappings: RPi BCM GPIO numbers.
# "drive_pins" are RPi outputs that connect to the FPGA input side.
# "read_pins" are RPi inputs that connect to the FPGA output side.

BOARD_CONFIGS = {
    "arty": {
        # RPi PMOD HAT JA -> Arty PMOD A (FPGA input side)
        "drive_pins": [6, 13, 19, 26, 12, 16, 20, 21],  # JA1-JA4, JA7-JA10
        # RPi PMOD HAT JB -> Arty PMOD B (FPGA output side)
        "read_pins": [5, 11, 9, 10, 7, 8, 0, 1],  # JB1-JB4, JB7-JB10
        "width": 8,
    },
    "netv2": {
        "drive_pins": [14],  # RPi GPIO14 (TX) -> FPGA E13 (RX)
        "read_pins": [15],   # RPi GPIO15 (RX) <- FPGA E14 (TX)
        "width": 1,
    },
    "fomu": {
        # These pin numbers depend on how the Fomu EVT is wired to the RPi.
        # Placeholder -- needs to be filled in based on actual wiring.
        "drive_pins": [],  # TBD: RPi GPIO pins wired to Fomu pmoda_n
        "read_pins": [],   # TBD: RPi GPIO pins wired to Fomu pmodb_n
        "width": 4,
    },
}


# GPIO chip labels for Raspberry Pi models.
GPIO_CHIP_LABELS = {
    "pinctrl-rp1":     None,   # RPi 5 (RP1 chip)
    "pinctrl-bcm2835": None,   # RPi 4 / RPi 3
}


# -- GPIO helpers --------------------------------------------------------------

def detect_gpio_chip():
    """Detect the correct gpiochip for RPi GPIO pins by chip label.

    Using the chip label (e.g. 'pinctrl-rp1' for RPi 5, 'pinctrl-bcm2835'
    for RPi 4) is more robust than relying on device node numbers like
    /dev/gpiochip0 or /dev/gpiochip4, which can change across kernels.
    """
    import pathlib
    for chip_path in sorted(pathlib.Path("/dev").glob("gpiochip*")):
        try:
            chip = gpiod.Chip(str(chip_path))
            info = chip.get_info()
            label = info.label
            chip.close()
            if label in GPIO_CHIP_LABELS:
                return str(chip_path)
        except (OSError, PermissionError):
            continue
    raise RuntimeError(
        "Cannot find GPIO chip with a known label "
        f"({', '.join(GPIO_CHIP_LABELS)}). Is this a Raspberry Pi?"
    )


class PmodHatGpio:
    """Drive/read GPIO pins using gpiod."""

    def __init__(self, drive_pins, read_pins, chip_path=None):
        self.drive_pins = drive_pins
        self.read_pins = read_pins
        self.chip_path = chip_path or detect_gpio_chip()
        self._drive_request = None
        self._read_request = None

    def open(self):
        """Configure drive pins as outputs and read pins as inputs."""
        if self.drive_pins:
            self._drive_request = gpiod.request_lines(
                self.chip_path,
                consumer="pmod-loopback-test",
                config={
                    tuple(self.drive_pins): gpiod.LineSettings(
                        direction=gpiod.line.Direction.OUTPUT,
                        output_value=gpiod.line.Value.INACTIVE,
                    ),
                },
            )
        if self.read_pins:
            self._read_request = gpiod.request_lines(
                self.chip_path,
                consumer="pmod-loopback-test",
                config={
                    tuple(self.read_pins): gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT,
                    ),
                },
            )

    def close(self):
        if self._drive_request:
            self._drive_request.release()
            self._drive_request = None
        if self._read_request:
            self._read_request.release()
            self._read_request = None

    def write(self, value):
        """Write N-bit value to drive (output) pins. Bit 0 = pin index 0."""
        values = {}
        for i, pin in enumerate(self.drive_pins):
            bit = (value >> i) & 1
            values[pin] = gpiod.line.Value.ACTIVE if bit else gpiod.line.Value.INACTIVE
        self._drive_request.set_values(values)

    def read(self):
        """Read N-bit value from read (input) pins. Returns int."""
        values = self._read_request.get_values()
        result = 0
        for i, pin in enumerate(self.read_pins):
            if values[pin] == gpiod.line.Value.ACTIVE:
                result |= (1 << i)
        return result


# -- Test patterns -------------------------------------------------------------

def generate_test_patterns(width):
    """Generate test bit patterns appropriate for the given pin width."""
    mask = (1 << width) - 1
    patterns = []

    # All zeros and all ones
    patterns.append(0x00)
    patterns.append(mask)

    # Walking 1
    for i in range(width):
        patterns.append(1 << i)

    # Walking 0
    for i in range(width):
        patterns.append(mask ^ (1 << i))

    # Alternating (only meaningful for width >= 2)
    if width >= 2:
        patterns.append(0xAA & mask)
        patterns.append(0x55 & mask)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# -- Test runner ---------------------------------------------------------------

def run_test(board_name, config):
    """Run GPIO loopback test for the specified board."""
    width = config["width"]
    mask = (1 << width) - 1
    patterns = generate_test_patterns(width)
    total_tests = 0
    failures = []

    print("=== PMOD GPIO Loopback Test ===")
    print(f"Board:      {board_name}")
    print(f"Width:      {width} bits")
    print(f"Drive pins: {config['drive_pins']}")
    print(f"Read pins:  {config['read_pins']}")
    print(f"Patterns:   {len(patterns)}")
    print()

    if not config["drive_pins"] or not config["read_pins"]:
        print("ERROR: Pin mapping not configured for this board.")
        print("Edit BOARD_CONFIGS in test_pmod_loopback.py to set pin numbers.")
        return False

    gpio = PmodHatGpio(config["drive_pins"], config["read_pins"])

    try:
        gpio.open()

        # Small delay to let lines settle after configuration
        time.sleep(0.01)

        for pattern in patterns:
            gpio.write(pattern)
            time.sleep(0.001)  # propagation settle time

            reading = gpio.read()
            expected = (~pattern) & mask

            total_tests += 1
            if reading != expected:
                failures.append(
                    f"sent 0x{pattern:0{(width + 3) // 4}X}, "
                    f"expected 0x{expected:0{(width + 3) // 4}X}, "
                    f"got 0x{reading:0{(width + 3) // 4}X} "
                    f"(diff 0x{expected ^ reading:0{(width + 3) // 4}X})"
                )
                print(f"  FAIL: sent 0x{pattern:0{(width + 3) // 4}X}, "
                      f"expected ~=0x{expected:0{(width + 3) // 4}X}, "
                      f"got 0x{reading:0{(width + 3) // 4}X}")
            else:
                print(f"  OK:   0x{pattern:0{(width + 3) // 4}X} -> "
                      f"~=0x{expected:0{(width + 3) // 4}X}")

    finally:
        gpio.close()

    # Results
    print()
    print(f"=== Results: {total_tests - len(failures)}/{total_tests} passed ===")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        print("FAIL")
        return False
    else:
        print("PASS")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="PMOD GPIO Loopback Test (host-side, no UART)")
    parser.add_argument(
        "--board", default="arty",
        choices=list(BOARD_CONFIGS.keys()),
        help="Target board (default: arty)")
    args = parser.parse_args()

    config = BOARD_CONFIGS[args.board]
    success = run_test(args.board, config)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
