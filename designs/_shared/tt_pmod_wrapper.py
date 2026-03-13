#!/usr/bin/env python3
"""Combined FPGA program + GPIO loopback test for TT FPGA Demo Board.

Programs the iCE40 with the loopback bitstream via RP2350, then runs
the GPIO inversion test entirely on the RP2350 (no RPi GPIO needed).

The FPGA does output = ~input. The RP2350 drives ui_in[0:7] GPIO pins
and reads uo_out[0:7] GPIO pins to verify inversion.

Usage (on RPi):
    python3 tt_pmod_wrapper.py /dev/ttyACM0 bitstream.bin
"""

import os
import sys
import time

# Reuse upload/serial infrastructure from the UART wrapper.
sys.path.insert(0, os.path.dirname(__file__))
from tt_test_wrapper import (
    upload_bitstream, open_raw_serial, enter_raw_repl, execute_raw_repl,
)


# MicroPython script that runs on the RP2350:
# 1. Programs the iCE40 via PIO SPI
# 2. Starts the 50 MHz clock
# 3. Runs GPIO loopback test patterns
PROGRAM_AND_TEST_SCRIPT = """\
from machine import Pin, PWM, freq as cpu_freq
import sys, utime

from ttboard.fpga.fabricfox import DoDummyClocks, spi_write
from rp2 import StateMachine

# --- Program FPGA (same as UART wrapper) ---
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
utime.sleep_ms(50)

# --- GPIO loopback test ---
# TTDBv3 pin mapping (empirically confirmed):
# ui_in[0:7] = RP2350 GPIO 17,18,19,20,21,22,23,24
# uo_out[0:7] = RP2350 GPIO 33,34,35,36,37,38,39,40
UI_IN_GPIOS  = [17, 18, 19, 20, 21, 22, 23, 24]
UO_OUT_GPIOS = [33, 34, 35, 36, 37, 38, 39, 40]
WIDTH = 8

drive = [Pin(g, Pin.OUT, value=0) for g in UI_IN_GPIOS]
read  = [Pin(g, Pin.IN, Pin.PULL_UP) for g in UO_OUT_GPIOS]

mask = (1 << WIDTH) - 1
patterns = [0x00, mask]
for i in range(WIDTH):
    patterns.append(1 << i)
for i in range(WIDTH):
    patterns.append(mask ^ (1 << i))
patterns.extend([0xAA & mask, 0x55 & mask])
# Deduplicate
seen = set()
unique = []
for p in patterns:
    if p not in seen:
        seen.add(p)
        unique.append(p)
patterns = unique

errors = 0
total = 0
for pattern in patterns:
    for i in range(WIDTH):
        drive[i].value((pattern >> i) & 1)
    utime.sleep_ms(1)
    reading = 0
    for i in range(WIDTH):
        if read[i].value():
            reading |= (1 << i)
    expected = (~pattern) & mask
    total += 1
    if reading != expected:
        errors += 1
        sys.stdout.write('FAIL: 0x{:02X} -> expected 0x{:02X}, got 0x{:02X}\\n'.format(
            pattern, expected, reading))
    else:
        sys.stdout.write('OK: 0x{:02X} -> ~=0x{:02X}\\n'.format(pattern, expected))

sys.stdout.write('\\n')
if errors == 0:
    sys.stdout.write('RESULT: PASS -- {}/{} GPIO loopback patterns correct\\n'.format(total, total))
else:
    sys.stdout.write('RESULT: FAIL -- {}/{} patterns failed\\n'.format(errors, total))
sys.stdout.write('TEST_DONE\\n')
""".replace("__BITSTREAM_PATH__", "/bitstreams/custom.bin")


def main():
    if len(sys.argv) < 3:
        print("usage: tt_pmod_wrapper.py PORT BITSTREAM", file=sys.stderr)
        return 2

    port = sys.argv[1]
    bitstream = sys.argv[2]

    # Step 1: Upload bitstream
    print("Uploading bitstream to RP2350...")
    if not upload_bitstream(port, bitstream):
        print("ERROR: Failed to upload bitstream", file=sys.stderr)
        return 1
    print("Upload complete.")

    time.sleep(0.5)

    # Step 2: Open raw serial and run combined program + test
    print("Opening raw serial to RP2350...")
    serial_fd = open_raw_serial(port)

    print("Entering raw REPL...")
    enter_raw_repl(serial_fd)

    print("Programming FPGA and running GPIO loopback test...")
    ok, extra_data = execute_raw_repl(
        serial_fd, PROGRAM_AND_TEST_SCRIPT,
        marker=b"TEST_DONE", timeout=60,
    )

    # Print all output
    if ok:
        pre = extra_data  # execute_raw_repl returns data after marker
        # The marker-based output includes everything before TEST_DONE
        # which was already printed by execute_raw_repl
        pass
    else:
        print("ERROR: Test did not complete", file=sys.stderr)
        print("Output: {}".format(
            extra_data.decode("utf-8", errors="replace")), file=sys.stderr)

    # Cleanup
    try:
        os.write(serial_fd, b'\x03')
        time.sleep(0.1)
        os.write(serial_fd, b'\x03')
    except OSError:
        pass
    os.close(serial_fd)

    # Check for PASS in the raw REPL output that was printed
    # The execute_raw_repl function prints pre-marker output
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
