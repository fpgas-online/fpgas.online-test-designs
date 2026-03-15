#!/usr/bin/env python3
"""Program TT FPGA Demo Board for PMOD loopback and release RP2350 GPIOs.

Programs the iCE40 with the loopback bitstream via RP2350, starts the
50 MHz clock, then releases all RP2350 GPIOs to high-Z so the RPi can
drive/read them directly through the PMOD HAT.

The actual GPIO loopback test runs on the RPi via test_pmod_loopback.py.

Usage (on RPi):
    python3 tt_pmod_wrapper.py /dev/ttyACM0 bitstream.bin
"""

import os
import sys

# Reuse upload/serial infrastructure from the UART wrapper.
sys.path.insert(0, os.path.dirname(__file__))
from tt_test_wrapper import (
    upload_bitstream, open_raw_serial, enter_raw_repl, execute_raw_repl, drain,
)


# MicroPython script: program FPGA, start clock, release GPIOs.
PROGRAM_AND_RELEASE_SCRIPT = """\
from machine import Pin, PWM, freq as cpu_freq
import sys, utime

from ttboard.fpga.fabricfox import DoDummyClocks, spi_write
from rp2 import StateMachine

# --- Program FPGA via PIO SPI ---
sck_pin = Pin(6, Pin.OUT)
mosi_pin = Pin(3, Pin.OUT)
ss_pin = Pin(5, Pin.OUT)
reset_pin = Pin(1, Pin.OUT)

reset_pin.low()
ss_pin.low()
utime.sleep_us(15000)
reset_pin.high()
utime.sleep_us(15000)

freq = 1_000_000
sm = StateMachine(0, spi_write, freq=freq*2*8,
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
        bc = 0
        while True:
            data = f.read(128)
            if not data:
                for _ in range(6):
                    while sm.tx_fifo() != 0:
                        utime.sleep_us(1)
                    sm.put(0)
                break
            for b in data:
                sm.put(b & 0xff, 24)
                while sm.tx_fifo() != 0:
                    utime.sleep_us(1)
                bc += 1
        while sm.tx_fifo():
            utime.sleep_us(10)
finally:
    sm.active(0)
    ss_pin.high()
    sm.restart()

sys.stdout.write('PROGRAM_OK\\n')

# --- Start 50 MHz clock ---
cpu_freq(150_000_000)
clk = PWM(Pin(16))
clk.freq(50_000_000)
clk.duty_u16(32768)
clk.deinit()
utime.sleep_ms(1)
clk = PWM(Pin(16))
clk.freq(50_000_000)
clk.duty_u16(32768)
sys.stdout.write('CLK_OK\\n')

# --- Release all ui_in/uo_out GPIOs to input (high-Z) ---
# This allows the RPi to drive/read them via the PMOD HAT.
for g in list(range(17, 25)) + list(range(33, 41)):
    Pin(g, Pin.IN)
sys.stdout.write('GPIO_RELEASED\\n')
sys.stdout.write('SETUP_DONE\\n')
""".replace("__BITSTREAM_PATH__", "/bitstreams/custom.bin")


def main():
    if len(sys.argv) < 3:
        print("usage: tt_pmod_wrapper.py PORT BITSTREAM", file=sys.stderr)
        return 2

    port = sys.argv[1]
    bitstream = sys.argv[2]

    # Step 1: Upload bitstream (handles reset, retry, safe main.py)
    print("Uploading bitstream to RP2350...")
    if not upload_bitstream(port, bitstream):
        print("ERROR: Failed to upload bitstream", file=sys.stderr)
        return 1
    print("Upload complete.")

    # Step 2: Program FPGA, start clock, release GPIOs
    print("Opening raw serial to RP2350...")
    serial_fd = open_raw_serial(port)

    print("Entering raw REPL...")
    enter_raw_repl(serial_fd)

    print("Programming FPGA and releasing GPIOs...")
    ok, extra_data = execute_raw_repl(
        serial_fd, PROGRAM_AND_RELEASE_SCRIPT,
        marker=b"SETUP_DONE", timeout=60,
    )

    if not ok:
        print("ERROR: Setup did not complete", file=sys.stderr)
        print("Output: {}".format(
            extra_data.decode("utf-8", errors="replace")), file=sys.stderr)

    # Cleanup — leave RP2350 at REPL prompt
    try:
        os.write(serial_fd, b'\x03')
        drain(serial_fd, timeout=0.2)
        os.write(serial_fd, b'\x03')
        drain(serial_fd, timeout=0.2)
    except OSError:
        pass
    os.close(serial_fd)

    if ok:
        print("FPGA programmed, GPIOs released for RPi access.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
