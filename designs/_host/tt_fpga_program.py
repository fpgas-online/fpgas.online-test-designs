#!/usr/bin/env python3
"""Program a TT FPGA Demo Board's iCE40 via its RP2350 MicroPython interface.

The TT FPGA Demo Board has an RP2350B running MicroPython with the 'ttboard'
SDK, which includes the 'fabricfox' module for programming the iCE40 FPGA via
SPI (either PIO-accelerated or bitbang).

This host-side script uses 'mpremote' to:
  1. Mount a temporary directory on the Pi, holding a copy of the bitstream,
     as /remote on the RP2350 (`mpremote mount`: served over the serial
     link, nothing is stored on the board, and the board is given nothing
     else of the Pi's)
  2. Run a script on the RP2350 that reads the bitstream from /remote and
     clocks it into the iCE40

Nothing is written to the demo board's filesystem: no file is copied to it,
no directory is made on it.

Usage:
    python3 tt_fpga_program.py /dev/ttyACM0 bitstream.bin [--method bitbang]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

# Where `mpremote mount` shows the Pi's directory on the board (mpremote's own, fixed, name).
REMOTE_MOUNT = "/remote"
# The bitstream's name in the mounted directory.
MOUNTED_NAME = "design.bin"
# One load. Measured on a demo board, 2026-10-05: about 10 s for a 104090-byte bitstream, clock and GPIO
# release included. At that speed two loads (tt_test_wrapper retries once), the bridge and a test fit in
# the check's 300 s; if every step took its own limit they would not, and the check would say it ran out of time.
PROGRAM_TIMEOUT = 60

# Run last on the board: mpremote's mount also made /remote the working directory, and it is unmounted when
# mpremote leaves.
LEAVE_MOUNT = """
import os
os.chdir("/")
"""

# Appended to the programming script when --gpio-release is used.
# Starts the 50 MHz clock and releases all ui_in/uo_out/uio GPIOs
# to input (high-Z) so the RPi can drive/read them via the PMOD HAT.
GPIO_RELEASE_SNIPPET = """
# --- Start 50 MHz clock ---
from machine import PWM, freq as cpu_freq
cpu_freq(150_000_000)
clk = PWM(Pin(16))
clk.freq(50_000_000)
clk.duty_u16(32768)
# Workaround for RP2350 PWM bug: deinit and recreate
clk.deinit()
utime.sleep_ms(1)
clk = PWM(Pin(16))
clk.freq(50_000_000)
clk.duty_u16(32768)
print("CLK_OK")

# --- Release all ui_in/uo_out/uio GPIOs to input (high-Z) ---
for g in list(range(17, 41)):
    Pin(g, Pin.IN)
print("GPIO_RELEASED")
"""

# MicroPython scripts that run on the RP2350 to program the iCE40 FPGA.
#
# The ttboard SDK has two bugs:
# 1. pin_objects() returns MuxedSelection wrappers lacking .high()/.low()
# 2. pin_indices() returns TT04 GPIO numbers due to GPIOMap firmware bug
#    (all boards load GPIOMapTT04 instead of GPIOMapTTDBv3)
#
# Workaround: hardcode the correct TTDBv3 GPIO numbers directly.

PROGRAM_SCRIPT_PIO = """\
from machine import Pin
try:  # TT SDK 3.x renamed it fabricfoxv2 (same API); 2.x has fabricfox
    from ttboard.fpga.fabricfoxv2 import DoDummyClocks, spi_write
except ImportError:
    from ttboard.fpga.fabricfox import DoDummyClocks, spi_write
import rp2
from rp2 import PIO, StateMachine
import utime

# TTDBv3 SPI programming pins (hardcoded to bypass GPIOMap firmware bug:
# all boards load GPIOMapTT04 instead of GPIOMapTTDBv3, so pin_indices()
# returns wrong GPIO numbers).
sck_pin = Pin(6, Pin.OUT)    # MNG03
mosi_pin = Pin(3, Pin.OUT)   # MNG00
ss_pin = Pin(5, Pin.OUT)     # MNG02
reset_pin = Pin(1, Pin.OUT)  # CTRL_SEL_nRST (CRESET_B)

print("Pins: sck=6, mosi=3, ss=5, reset=1 (TTDBv3 hardcoded)")

# FPGA reset sequence
reset_pin.low()
ss_pin.low()
utime.sleep_us(15000)
reset_pin.high()
utime.sleep_us(15000)

# Set up PIO state machine for SPI
freq = 1_000_000
pio_freq = freq * 2 * 8
sm = StateMachine(0, spi_write, freq=pio_freq,
                  sideset_base=Pin(6),
                  out_base=Pin(3))
sm.restart()
sm.active(1)

try:
    with open("__BITSTREAM_PATH__", "rb") as f:
        if DoDummyClocks:
            ss_pin.high()
            utime.sleep_us(2000)
            sm.put(0)
            utime.sleep_us(20)
            while sm.tx_fifo() != 0:
                utime.sleep_us(2)
            ss_pin.low()
            utime.sleep_us(2000)

        print("Programming iCE40 via PIO SPI...")
        byte_count = 0
        while True:
            data = f.read(128)
            if not data:
                for _ in range(6):
                    while sm.tx_fifo() != 0:
                        utime.sleep_us(1)
                    sm.put(0)
                break
            for byte in data:
                sm.put(byte & 0xff, 24)
                while sm.tx_fifo() != 0:
                    utime.sleep_us(1)
                byte_count += 1

        while sm.tx_fifo():
            utime.sleep_us(10)

        print("Transmitted {} bytes".format(byte_count))
finally:
    sm.active(0)
    ss_pin.high()
    sm.restart()

print("PROGRAM_OK")
"""

PROGRAM_SCRIPT_BITBANG = """\
from machine import Pin
try:  # TT SDK 3.x renamed it fabricfoxv2 (same API); 2.x has fabricfox
    from ttboard.fpga.fabricfoxv2 import DoDummyClocks
except ImportError:
    from ttboard.fpga.fabricfox import DoDummyClocks
import utime

# TTDBv3 SPI programming pins (hardcoded to bypass GPIOMap firmware bug).
sck_pin = Pin(6, Pin.OUT)    # MNG03
mosi_pin = Pin(3, Pin.OUT)   # MNG00
ss_pin = Pin(5, Pin.OUT)     # MNG02
reset_pin = Pin(1, Pin.OUT)  # CTRL_SEL_nRST (CRESET_B)

print("Pins: sck=6, mosi=3, ss=5, reset=1 (TTDBv3 hardcoded)")

def spi_send_byte(sck, mosi, val):
    sck.low()
    for i in range(8):
        if val & (1 << (7 - i)):
            mosi.high()
        else:
            mosi.low()
        sck.high()
        utime.sleep_us(1)
        sck.low()
        utime.sleep_us(1)

# FPGA reset sequence
reset_pin.low()
ss_pin.low()
utime.sleep_us(15000)
reset_pin.high()
utime.sleep_us(15000)

with open("__BITSTREAM_PATH__", "rb") as f:
    if DoDummyClocks:
        ss_pin.high()
        utime.sleep_us(2000)
        spi_send_byte(sck_pin, mosi_pin, 0)
        utime.sleep_us(20)
        ss_pin.low()
        utime.sleep_us(2000)

    print("Programming iCE40 via bitbang SPI...")
    byte_count = 0
    while True:
        data = f.read(128)
        if not data:
            for _ in range(6):
                spi_send_byte(sck_pin, mosi_pin, 0)
            break
        for byte in data:
            spi_send_byte(sck_pin, mosi_pin, byte)
            byte_count += 1

    print("Transmitted {} bytes".format(byte_count))

ss_pin.high()
print("PROGRAM_OK")
"""


def run_mpremote(port, args, timeout=60):
    """Run an mpremote command and return (returncode, stdout, stderr)."""
    cmd = ["mpremote", "connect", port, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def board_script(method, gpio_release, bitstream_name=MOUNTED_NAME):
    """The MicroPython script that programs the iCE40 from `bitstream_name` in the mounted directory."""
    script = PROGRAM_SCRIPT_PIO if method == "pio" else PROGRAM_SCRIPT_BITBANG
    script = script.replace("__BITSTREAM_PATH__", f"{REMOTE_MOUNT}/{bitstream_name}")
    if gpio_release:
        script += GPIO_RELEASE_SNIPPET
    return script + LEAVE_MOUNT


def program(port, bitstream, method="pio", gpio_release=False, timeout=PROGRAM_TIMEOUT):
    """Program the iCE40 with the bitstream file `bitstream` on this host; (returncode, stdout, stderr).

    One mpremote run: mount a temporary directory of this host on the board (over the serial link; nothing is
    stored on the board), run the programming script, leave. The directory holds a copy of the bitstream and
    nothing else the board could read or change, and is removed afterwards. mpremote not finishing in time is
    returncode 124, mpremote not being installed 127, a bitstream that cannot be copied 1: each with the reason
    as stderr, none an exception."""
    script = board_script(method, gpio_release)
    with (
        tempfile.TemporaryDirectory(prefix="tt_program_") as tmp,
        tempfile.TemporaryDirectory(prefix="tt_program_script_") as script_dir,
    ):
        try:
            shutil.copyfile(os.path.realpath(bitstream), os.path.join(tmp, MOUNTED_NAME))
        except OSError as e:
            return 1, "", f"the bitstream could not be copied for the board to read: {e}"
        script_path = os.path.join(script_dir, "program.py")
        with open(script_path, "w") as f:
            f.write(script)
        try:
            return run_mpremote(port, ["mount", tmp, "run", script_path], timeout=timeout)
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return 124, out, f"mpremote did not finish within {timeout} s"
        except FileNotFoundError:
            return 127, "", "mpremote is not installed"


def main():
    parser = argparse.ArgumentParser(
        description="Program TT FPGA Demo Board iCE40 via RP2350 + fabricfox",
    )
    parser.add_argument("port", help="Serial port for RP2350 (e.g. /dev/ttyACM0)")
    parser.add_argument("bitstream", help="Path to .bin bitstream file on host")
    parser.add_argument(
        "--method",
        choices=["pio", "bitbang"],
        default="pio",
        help="SPI transfer method (default: pio)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Just probe the RP2350, don't program",
    )
    parser.add_argument(
        "--gpio-release",
        action="store_true",
        help="After programming, start 50 MHz clock and release all "
        "ui_in/uo_out/uio GPIOs to high-Z for RPi PMOD HAT access",
    )
    args = parser.parse_args()

    # Validate bitstream exists
    if not args.probe:
        if not os.path.isfile(args.bitstream):
            print(f"ERROR: Bitstream file not found: {args.bitstream}", file=sys.stderr)
            return 1
        size = os.path.getsize(args.bitstream)
        print(f"Bitstream: {args.bitstream} ({size} bytes)")

    print(f"Port: {args.port}")

    if args.probe:
        print("=== Probing RP2350 ===")
        rc, out, err = run_mpremote(
            args.port,
            [
                "exec",
                "import sys; print('Python:', sys.version); "
                "import os; print('Root:', os.listdir('/')); "
                "print('Bitstreams:', os.listdir('/bitstreams') if 'bitstreams' in os.listdir('/') else 'none')",
            ],
        )
        print(out)
        if err.strip():
            print(err, file=sys.stderr)
        return rc

    print(f"Programming FPGA via {args.method} method, reading the bitstream from the Pi...")
    rc, out, err = program(args.port, args.bitstream, args.method, args.gpio_release)

    print(out)
    if err.strip():
        print(err, file=sys.stderr)

    if rc != 0 or "PROGRAM_OK" not in out:
        marker = "with" if "PROGRAM_OK" in out else "no"
        print(f"ERROR: FPGA programming failed (mpremote exit {rc}, {marker} PROGRAM_OK marker).", file=sys.stderr)
        return 1

    if args.gpio_release:
        if "GPIO_RELEASED" in out:
            print("FPGA programmed, clock started, GPIOs released for RPi access.")
        else:
            print("ERROR: GPIO release failed (no GPIO_RELEASED marker).", file=sys.stderr)
            return 1
    else:
        print("FPGA programming successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
