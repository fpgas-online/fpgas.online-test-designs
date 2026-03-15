#!/usr/bin/env python3
"""Program a TT FPGA Demo Board's iCE40 via its RP2350 MicroPython interface.

The TT FPGA Demo Board has an RP2350B running MicroPython with the 'ttboard'
SDK, which includes the 'fabricfox' module for programming the iCE40 FPGA via
SPI (either PIO-accelerated or bitbang).

This host-side script uses 'mpremote' to:
  1. Upload the bitstream file to the RP2350's filesystem
  2. Run fabricfox.spi_transferPIO() to program the iCE40

Usage:
    python3 tt_fpga_program.py /dev/ttyACM0 bitstream.bin [--method bitbang]
"""

import argparse
import os
import subprocess
import sys
import tempfile


BITSTREAM_DEVICE_PATH = "/bitstreams/custom.bin"

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
""".replace("__BITSTREAM_PATH__", BITSTREAM_DEVICE_PATH)

PROGRAM_SCRIPT_BITBANG = """\
from machine import Pin
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
""".replace("__BITSTREAM_PATH__", BITSTREAM_DEVICE_PATH)


def run_mpremote(port, args, timeout=60):
    """Run an mpremote command and return (returncode, stdout, stderr)."""
    cmd = ["mpremote", "connect", port] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


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
    args = parser.parse_args()

    # Validate bitstream exists
    if not args.probe:
        if not os.path.isfile(args.bitstream):
            print("ERROR: Bitstream file not found: {}".format(args.bitstream),
                  file=sys.stderr)
            return 1
        size = os.path.getsize(args.bitstream)
        print("Bitstream: {} ({} bytes)".format(args.bitstream, size))

    print("Port: {}".format(args.port))

    if args.probe:
        print("=== Probing RP2350 ===")
        rc, out, err = run_mpremote(args.port, [
            "exec",
            "import sys; print('Python:', sys.version); "
            "import os; print('Root:', os.listdir('/')); "
            "print('Bitstreams:', os.listdir('/bitstreams') if 'bitstreams' in os.listdir('/') else 'none')",
        ])
        print(out)
        if err.strip():
            print(err, file=sys.stderr)
        return rc

    # Step 1: Ensure /bitstreams/ directory exists on device
    print("Creating /bitstreams/ directory on device...")
    rc, out, err = run_mpremote(args.port, [
        "exec",
        "import os\n"
        "try:\n"
        "    os.mkdir('/bitstreams')\n"
        "    print('Created /bitstreams/')\n"
        "except OSError:\n"
        "    print('/bitstreams/ already exists')\n",
    ])
    print(out.strip())
    if rc != 0:
        print("ERROR: Failed to create directory: {}".format(err), file=sys.stderr)
        return 1

    # Step 2: Upload bitstream to device
    print("Uploading bitstream to device:{}...".format(BITSTREAM_DEVICE_PATH))
    rc, out, err = run_mpremote(args.port, [
        "cp", args.bitstream, ":" + BITSTREAM_DEVICE_PATH,
    ], timeout=120)
    if rc != 0:
        print("ERROR: Failed to upload bitstream", file=sys.stderr)
        print(out)
        print(err, file=sys.stderr)
        return 1
    print("Upload complete.")

    # Step 3: Program the FPGA
    script = PROGRAM_SCRIPT_PIO if args.method == "pio" else PROGRAM_SCRIPT_BITBANG
    print("Programming FPGA via {} method...".format(args.method))

    # Write script to a temporary file for mpremote run.
    # Use the directory containing this script (not /tmp/) for the temp file.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="tt_program_",
        dir=script_dir, delete=False,
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        rc, out, err = run_mpremote(args.port, [
            "run", script_path,
        ], timeout=120)
    finally:
        os.unlink(script_path)

    print(out)
    if err.strip():
        print(err, file=sys.stderr)

    if "PROGRAM_OK" in out:
        print("FPGA programming successful.")
        return 0
    else:
        print("ERROR: FPGA programming may have failed (no PROGRAM_OK marker).",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
