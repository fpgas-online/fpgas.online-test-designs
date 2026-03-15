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
    - python3-libgpiod installed (v1.6+ or v2.x both supported)
"""

import argparse
import pathlib
import sys
import time

import gpiod


# -- Board-specific pin configurations ----------------------------------------
# Pin mappings: RPi BCM GPIO numbers.
# "drive_pins" are RPi outputs that connect to the FPGA input side.
# "read_pins" are RPi inputs that connect to the FPGA output side.

BOARD_CONFIGS = {
    "arty": {
        # Empirically confirmed loopback pairs (100% confidence):
        # Two PMOD cables: RPi HAT JA -> Arty JA, RPi HAT JC -> Arty JB
        # FPGA does: pmodb = ~pmoda (per-bit inversion)
        # 4 of 8 pairs confirmed; others need further investigation.
        "drive_pins": [8, 19, 20, 21],   # RPi -> FPGA pmoda inputs
        "read_pins":  [7, 26, 3, 13],    # FPGA pmodb outputs -> RPi
        "width": 4,
    },
    "netv2": {
        "drive_pins": [14],  # RPi GPIO14 (TX) -> FPGA E13 (RX)
        "read_pins": [15],   # RPi GPIO15 (RX) <- FPGA E14 (TX)
        "width": 1,
    },
    "fomu": {
        # Empirically confirmed: Fomu EVT on pi17/pi21 test jig.
        # Only 1 of the 4 loopback pairs connects to RPi GPIO.
        "drive_pins": [27],   # RPi GPIO27 -> Fomu pmoda_n input
        "read_pins":  [9],    # Fomu pmodb_n output -> RPi GPIO9
        "width": 1,
    },
    "tt": {
        # Empirically confirmed: TT FPGA Demo Board v3 via PMOD HAT.
        # PMOD cables: RPi HAT JA/JC/JB -> TT PMOD headers.
        # FPGA does: uo_out = ~ui_in (per-bit inversion, 8-bit).
        # RP2350 GPIOs must be released to input (high-Z) first.
        #   ui_in[0:7] drive GPIOs: JA1, JA7, JA8, JB1, JC1, JC3, JC4, JC9
        #   uo_out[0:7] read GPIOs: JC2, JA10, JB8, JA9, JB2, JA3, JB4, JB3
        "drive_pins": [6, 12, 16, 5, 17, 4, 14, 15],
        "read_pins":  [18, 21, 8, 20, 11, 19, 10, 9],
        "width": 8,
        "pre_test": "rmmod spidev spi_bcm2835 2>&1; true",
    },
}


# GPIO chip labels for Raspberry Pi models.
GPIO_CHIP_LABELS = {
    "pinctrl-rp1",       # RPi 5 (RP1 chip)
    "pinctrl-bcm2711",   # RPi 4 (BCM2711)
    "pinctrl-bcm2835",   # RPi 3 / RPi Zero
}

# Detect gpiod API version.
_GPIOD_V2 = hasattr(gpiod, "request_lines")


# -- GPIO helpers --------------------------------------------------------------

def detect_gpio_chip():
    """Detect the correct gpiochip for RPi GPIO pins by chip label.

    Using the chip label (e.g. 'pinctrl-rp1' for RPi 5, 'pinctrl-bcm2835'
    for RPi 4) is more robust than relying on device node numbers like
    /dev/gpiochip0 or /dev/gpiochip4, which can change across kernels.
    """
    for chip_path in sorted(pathlib.Path("/dev").glob("gpiochip*")):
        try:
            chip = gpiod.Chip(str(chip_path))
            if _GPIOD_V2:
                label = chip.get_info().label
            else:
                label = chip.label()
            chip.close()
            if label in GPIO_CHIP_LABELS:
                return str(chip_path)
        except (OSError, PermissionError):
            continue
    raise RuntimeError(
        "Cannot find GPIO chip with a known label "
        "({}). Is this a Raspberry Pi?".format(', '.join(GPIO_CHIP_LABELS))
    )


class PmodHatGpio:
    """Drive/read GPIO pins using gpiod (supports both v1.6+ and v2.x)."""

    def __init__(self, drive_pins, read_pins, chip_path=None):
        self.drive_pins = drive_pins
        self.read_pins = read_pins
        self.chip_path = chip_path or detect_gpio_chip()
        # v2 state
        self._drive_request = None
        self._read_request = None
        # v1 state
        self._chip = None
        self._drive_lines = []
        self._read_lines = []

    def open(self):
        """Configure drive pins as outputs and read pins as inputs."""
        if _GPIOD_V2:
            self._open_v2()
        else:
            self._open_v1()

    def _open_v2(self):
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

    def _open_v1(self):
        self._chip = gpiod.Chip(self.chip_path)
        for pin in self.drive_pins:
            line = self._chip.get_line(pin)
            line.request(consumer="pmod-loopback-test",
                         type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
            self._drive_lines.append(line)
        for pin in self.read_pins:
            line = self._chip.get_line(pin)
            line.request(consumer="pmod-loopback-test",
                         type=gpiod.LINE_REQ_DIR_IN)
            self._read_lines.append(line)

    def close(self):
        if _GPIOD_V2:
            if self._drive_request:
                self._drive_request.release()
                self._drive_request = None
            if self._read_request:
                self._read_request.release()
                self._read_request = None
        else:
            for line in self._drive_lines + self._read_lines:
                line.release()
            self._drive_lines.clear()
            self._read_lines.clear()
            if self._chip:
                self._chip.close()
                self._chip = None

    def write(self, value):
        """Write N-bit value to drive (output) pins. Bit 0 = pin index 0."""
        if _GPIOD_V2:
            values = {}
            for i, pin in enumerate(self.drive_pins):
                bit = (value >> i) & 1
                values[pin] = gpiod.line.Value.ACTIVE if bit else gpiod.line.Value.INACTIVE
            self._drive_request.set_values(values)
        else:
            for i, line in enumerate(self._drive_lines):
                line.set_value((value >> i) & 1)

    def read(self):
        """Read N-bit value from read (input) pins. Returns int."""
        result = 0
        if _GPIOD_V2:
            values = self._read_request.get_values()
            for i, pin in enumerate(self.read_pins):
                if values[i] == gpiod.line.Value.ACTIVE:
                    result |= (1 << i)
        else:
            for i, line in enumerate(self._read_lines):
                if line.get_value():
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
    print("Board:      {}".format(board_name))
    print("Width:      {} bits".format(width))
    print("Drive pins: {}".format(config['drive_pins']))
    print("Read pins:  {}".format(config['read_pins']))
    print("Patterns:   {}".format(len(patterns)))
    print()

    if not config["drive_pins"] or not config["read_pins"]:
        print("ERROR: Pin mapping not configured for this board.")
        print("Edit BOARD_CONFIGS in test_pmod_loopback.py to set pin numbers.")
        return False

    gpio = PmodHatGpio(config["drive_pins"], config["read_pins"])

    try:
        gpio.open()

        # Write initial value and poll until output settles (confirms
        # GPIO lines are active and FPGA loopback is responding).
        gpio.write(0)
        expected_init = mask  # ~0x00
        for _ in range(100):
            if gpio.read() == expected_init:
                break
            time.sleep(0.001)

        hex_w = (width + 3) // 4

        for pattern in patterns:
            gpio.write(pattern)
            expected = (~pattern) & mask

            # Poll until output matches expected or timeout (~50ms).
            reading = gpio.read()
            if reading != expected:
                for _ in range(50):
                    time.sleep(0.001)
                    reading = gpio.read()
                    if reading == expected:
                        break

            total_tests += 1
            if reading != expected:
                failures.append(
                    "sent 0x{:0{}X}, "
                    "expected 0x{:0{}X}, "
                    "got 0x{:0{}X} "
                    "(diff 0x{:0{}X})".format(
                        pattern, hex_w, expected, hex_w,
                        reading, hex_w, expected ^ reading, hex_w))
                print("  FAIL: sent 0x{:0{}X}, "
                      "expected ~=0x{:0{}X}, "
                      "got 0x{:0{}X}".format(
                          pattern, hex_w, expected, hex_w,
                          reading, hex_w))
            else:
                print("  OK:   0x{:0{}X} -> "
                      "~=0x{:0{}X}".format(
                          pattern, hex_w, expected, hex_w))

    finally:
        gpio.close()

    # Results
    print()
    print("=== Results: {}/{} passed ===".format(
        total_tests - len(failures), total_tests))
    if failures:
        print("Failures:")
        for fail in failures:
            print("  - {}".format(fail))
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
