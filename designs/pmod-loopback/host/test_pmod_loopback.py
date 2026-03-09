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
        # Use a short per-read timeout so readline() returns quickly,
        # allowing the retry loop in _read_response() to check multiple
        # lines within the overall deadline.
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self._response_timeout = timeout
        time.sleep(0.1)  # let FPGA boot
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _send(self, cmd):
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()

    def _read_response(self):
        """Read lines until we get a response (skip prompt '> ' lines)."""
        deadline = time.time() + self._response_timeout
        while time.time() < deadline:
            line = self.ser.readline().decode(errors="replace").strip()
            if not line:
                continue  # empty read due to per-read timeout, retry
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
