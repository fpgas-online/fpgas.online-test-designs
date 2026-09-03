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
import re
import subprocess
import sys
import time

# gpiod only exists on the Raspberry Pi (it wraps libgpiod). Guard the import
# so the board mapping + validation logic in this module can be imported and
# unit-tested on a development machine without the native library present.
# Any code path that actually reads GPIO raises a clear error if gpiod is None.
try:
    import gpiod
except ImportError:  # pragma: no cover - exercised only off-target
    gpiod = None

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

# -- Board pin maps (for --board validation mode) ------------------------------

# Expected RPi-BCM-GPIO -> FPGA-ball mappings used by `--board` mode to *verify*
# physical wiring (not just discover it). Each pin is (gpio, fpga_ball, label).
# When the FPGA runs the matching pmod_pin_id bitstream, the ball connected to
# each GPIO transmits its own name, so a correct decode == correct wiring.
BOARDS = {
    # Sqrl Acorn CLE-215+ / LiteFury P2 header, wired to the RPi 5 GPIO header
    # via an adapted Pico-EZmate cable with the fleet's null-modem crossover:
    # FPGA TX (K2) lands on the Pi's RXD0 (GPIO15) and FPGA RX (J2) on the
    # Pi's TXD0 (GPIO14). See docs/hardware/acorn-pinmap.md, "Measured P2
    # wiring (Welland, 2026-08-31)".
    "acorn": {
        "description": "Acorn CLE-215+ / LiteFury P2 header -> RPi 5 GPIO",
        "pins": [
            (15, "K2", "P2.1 Serial TX -> Pi RXD0"),
            (14, "J2", "P2.2 Serial RX <- Pi TXD0"),
            (3, "J5", "P2.3 Spare GPIO 0"),
            (4, "H5", "P2.4 Spare GPIO 1"),
        ],
    },
}


def evaluate_board(board_name, results):
    """Validate decoded pin labels against a board's expected wiring.

    *results* maps ``gpio -> decoded_label`` as produced by :func:`scan_gpios`
    (a clean ball name like ``"K2"``, a ``"?garbled"`` string, or ``None`` for
    no signal). Returns ``(all_ok, rows)`` where each row is a dict with
    ``gpio``, ``label``, ``expected``, ``got`` and ``ok``. A pin passes only on
    an exact clean match — garbled and missing decodes both fail, because a
    miswired or unprogrammed board must not be reported as good.
    """
    spec = BOARDS[board_name]
    rows = []
    all_ok = True
    for gpio, expected, label in spec["pins"]:
        got = results.get(gpio)
        ok = got == expected
        if not ok:
            all_ok = False
        rows.append(
            {"gpio": gpio, "label": label, "expected": expected, "got": got, "ok": ok}
        )
    return all_ok, rows


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
    if gpiod is None:
        raise RuntimeError(
            "python3-libgpiod (the `gpiod` module) is not installed. "
            "Pin scanning requires it; install it on the Raspberry Pi."
        )
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
    """Capture edge events on a single GPIO pin using gpiod (v1 or v2).

    Edge events carry kernel timestamps, so the UART decode is immune to
    Python scheduling jitter. (A polling sampler was used before; on the
    Pi 5 Acorn hosts it mis-framed bytes on some pins while gpiomon on the
    same line showed a clean 1200-baud signal, 2026-09-03.)
    """

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
                        edge_detection=gpiod.line.Edge.BOTH,
                        bias=gpiod.line.Bias.PULL_UP,
                    ),
                },
            )
        else:
            self._chip = gpiod.Chip(self.chip_path)
            self._line = self._chip.get_line(self.gpio_num)
            self._line.request(
                consumer="pmod-pin-id",
                type=gpiod.LINE_REQ_EV_BOTH_EDGES,
                flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
            )

    def capture_edges(self, duration_s):
        """Collect edge events for *duration_s*.

        Returns a list of ``(level_after_edge, timestamp_ns)`` tuples in
        time order, where level is 1 for a rising edge and 0 for a falling one.
        """
        events = []
        deadline = time.monotonic() + duration_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if _GPIOD_V2:
                if not self._request.wait_edge_events(remaining):
                    break
                for ev in self._request.read_edge_events():
                    rising = ev.event_type == gpiod.EdgeEvent.Type.RISING_EDGE
                    events.append((1 if rising else 0, ev.timestamp_ns))
            else:
                if not self._line.event_wait(sec=int(remaining), nsec=int((remaining % 1) * 1e9)):
                    break
                ev = self._line.event_read()
                rising = ev.type == gpiod.LineEvent.RISING_EDGE
                events.append((1 if rising else 0, ev.sec * 1_000_000_000 + ev.nsec))
        return events

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


# -- UART decoder (from edge timestamps) --------------------------------------

def _level_at(events, i, ts):
    """Line level at time *ts*, given that events[i] is the first edge at or
    before the frame start. The level before an edge is its complement."""
    level = 1 - events[i][0]
    j = i
    while j < len(events) and events[j][1] <= ts:
        level = events[j][0]
        j += 1
    return level


def decode_edges(events, baud=BAUD_RATE):
    """Decode 8N1 frames from ``(level_after_edge, timestamp_ns)`` edges.

    Every falling edge that is not inside a frame already being decoded is
    taken as a start bit; data bits are reconstructed at the centre of each
    bit period from the edge history. Returns ``[(byte, stop_bit_ok)]``.
    """
    bit_ns = 1e9 / baud
    frames = []
    i = 0
    while i < len(events):
        level, t0 = events[i]
        if level != 0:  # only a falling edge can start a frame
            i += 1
            continue
        byte = 0
        for k in range(8):
            byte |= _level_at(events, i, t0 + (1.5 + k) * bit_ns) << k
        stop_ok = _level_at(events, i, t0 + 9.5 * bit_ns) == 1
        frames.append((byte, stop_ok))
        frame_end = t0 + 9.5 * bit_ns
        while i < len(events) and events[i][1] < frame_end:
            i += 1
    return frames


# Expected label format: FPGA pin names are 2-4 alphanumeric characters.
# Examples: "G13", "B11", "A9", "K16", "V14" (Xilinx 7-series ball names)
# Also accepts PMOD-style names like "JA01" for backwards compatibility.
_LABEL_PATTERN = re.compile(r'^[A-Z][A-Za-z0-9]{1,3}$')


def is_valid_label(label):
    """Check if a decoded label looks like a valid pin identifier."""
    return bool(_LABEL_PATTERN.match(label))


def label_from_frames(frames):
    """Turn decoded frames into the pin label the FPGA is transmitting.

    Lines are split on ``\\n`` with a trailing ``\\r`` stripped. Returns the
    most common *valid* label, a ``"?<raw>"`` marker if there was signal but
    no valid label (so a miswired or unclocked pin is visible), or ``None``
    when nothing was received.
    """
    from collections import Counter

    text = bytes(b for b, _ok in frames).decode("latin-1")
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    valid = [ln for ln in lines if is_valid_label(ln)]
    if valid:
        return Counter(valid).most_common(1)[0][0]
    if lines:
        return "?" + Counter(lines).most_common(1)[0][0]
    return None


# 1200 baud, "XNN\r\n" is 5 frames = 50 bit periods = ~42 ms per repeat;
# 250 ms captures at least five repeats for the vote.
CAPTURE_SECONDS = 0.25


def identify_pin(reader, capture_s=CAPTURE_SECONDS):
    """Capture edges for *capture_s* and return the transmitted label.

    Returns the label string (e.g. "K2"), a "?<raw>" marker for a garbled
    signal, or None when the line is silent.
    """
    events = reader.capture_edges(capture_s)
    return label_from_frames(decode_edges(events))


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


# -- Board validation output ---------------------------------------------------

def print_validation(board_name, rows):
    """Print a per-pin expected-vs-decoded table for `--board` mode."""
    spec = BOARDS[board_name]
    print(f"\n=== Wiring check: {board_name} ({spec['description']}) ===\n")
    print("| RPi GPIO | Header pin         | Expect | Got    | OK |")
    print("|----------|--------------------|--------|--------|----|")
    for r in rows:
        got = r["got"] if r["got"] is not None else "(none)"
        mark = "✓" if r["ok"] else "✗"
        print(
            f"| GPIO{r['gpio']:<4d} | {r['label']:<18s} | {r['expected']:<6s}"
            f" | {got:<6s} | {mark}  |"
        )


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Identify FPGA pins via UART transmission at 1200 baud"
    )
    parser.add_argument(
        "--board", choices=sorted(BOARDS),
        help="Validate wiring for a known board against its expected GPIO->ball "
             "map (prints RESULT: PASS/FAIL). Overrides --gpios/--hat-port.",
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

    if args.board:
        gpio_list = [gpio for gpio, _ball, _label in BOARDS[args.board]["pins"]]
    elif args.gpios:
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

    # `--board` mode: validate against the expected wiring and emit a single
    # RESULT: marker so verify_hardware.py can score it pass/fail.
    if args.board:
        all_ok, rows = evaluate_board(args.board, results)
        print_validation(args.board, rows)
        n_ok = sum(1 for r in rows if r["ok"])
        print(f"\n{n_ok}/{len(rows)} pins match expected wiring.")
        print(f"RESULT: {'PASS' if all_ok else 'FAIL'}")
        sys.exit(0 if all_ok else 1)

    print_mapping_table(results)

    valid_count = sum(1 for v in results.values() if v and not v.startswith("?"))
    garbled_count = sum(1 for v in results.values() if v and v.startswith("?"))
    print(f"\n{valid_count}/{len(gpio_list)} pins identified"
          f" ({garbled_count} garbled).")
    sys.exit(0 if valid_count > 0 else 1)


if __name__ == "__main__":
    main()
