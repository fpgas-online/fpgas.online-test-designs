#!/usr/bin/env python3
"""Combined FPGA program + UART bridge + test for TT FPGA Demo Board.

The TT FPGA Demo Board has an RP2350B that communicates with the host via
USB CDC (/dev/ttyACM0 = MicroPython REPL).  The FPGA's UART connects to
RP2350 GPIO20 (TX to FPGA RX = iCE40 pin 21 / ui_in[3]) and GPIO37
(RX from FPGA TX = iCE40 pin 45 / uo_out[4]), NOT directly to USB.
This wrapper sets up a transparent UART bridge on the RP2350 so test
scripts can communicate with the FPGA as if connected directly.

Flow:
  1. Upload bitstream to RP2350 filesystem (via mpremote)
  2. Open raw serial to RP2350, enter MicroPython raw REPL
  3. Execute combined script: set up UART0, program FPGA, enter bridge mode
  4. Create PTY pair -- test script connects to the PTY slave
  5. Relay data between serial (USB CDC / bridge) and PTY
  6. Run test script, report results, clean up

Usage (on RPi):
    python3 tt_test_wrapper.py /dev/ttyACM0 bitstream.bin \\
        python3 test_uart.py --port /dev/ttyACM0 --board tt

The wrapper replaces occurrences of the serial port in the test command
with the PTY path so the test script transparently sees the FPGA UART.
"""

import contextlib
import os
import pty
import select
import subprocess
import sys
import termios
import threading
import time
import tty

BITSTREAM_DEVICE_PATH = "/bitstreams/custom.bin"

# MicroPython script that runs on the RP2350.
# 1. Programs the iCE40 via PIO SPI
# 2. Sets up UART1 on correct TTDBv3 GPIO pins
# 3. Starts 50 MHz clock with deinit/recreate PWM fix
# 4. Enters transparent UART <-> USB CDC bridge
PROGRAM_AND_BRIDGE_SCRIPT = """\
from machine import UART, Pin
import sys, utime

from ttboard.fpga.fabricfox import DoDummyClocks, spi_write
from rp2 import StateMachine

# TTDBv3 SPI programming pins (hardcoded to bypass GPIOMap firmware bug:
# all boards load GPIOMapTT04 instead of GPIOMapTTDBv3, so pin_indices()
# returns wrong GPIO numbers).
sck_pin = Pin(6, Pin.OUT)    # MNG03
mosi_pin = Pin(3, Pin.OUT)   # MNG00
ss_pin = Pin(5, Pin.OUT)     # MNG02
reset_pin = Pin(1, Pin.OUT)  # CTRL_SEL_nRST (CRESET_B)

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

# Set up UART1 on correct TTDBv3 pins BEFORE starting the clock,
# so it captures the firmware boot banner.
# TTDBv3 GPIO mapping: ui_in[3] = GPIO 20 (iCE40 pin 21 = serial_rx),
#                      uo_out[4] = GPIO 37 (iCE40 pin 45 = serial_tx).
uart = UART(1, 115200, tx=Pin(20), rx=Pin(37))
sys.stdout.write('UART1_OK\\n')

# Start 50 MHz clock on GPIO 16 (RP_PROJCLK on TTDBv3) for the iCE40 PLL.
# RP2350 PWM initialization bug: first PWM() creates a stuck-HIGH output.
# Must deinit + recreate to get actual oscillation.
from machine import PWM, freq as cpu_freq
cpu_freq(150_000_000)
clk_pwm = PWM(Pin(16))
clk_pwm.freq(50_000_000)
clk_pwm.duty_u16(32768)
clk_pwm.deinit()
utime.sleep_ms(1)
clk_pwm = PWM(Pin(16))
clk_pwm.freq(50_000_000)
clk_pwm.duty_u16(32768)
sys.stdout.write('CLK_OK\\n')

# Wait for PLL lock + POR + firmware boot.
utime.sleep_ms(200)

# Check if UART has any data buffered from boot
boot = uart.read()
if boot:
    sys.stdout.write('BOOT_DATA:' + str(len(boot)) + '\\n')
else:
    sys.stdout.write('BOOT_DATA:none\\n')

sys.stdout.write('BRIDGE_ACTIVE\\n')

si = getattr(sys.stdin, 'buffer', sys.stdin)
so = getattr(sys.stdout, 'buffer', sys.stdout)

# Write any boot data to stdout before entering bridge loop
if boot:
    so.write(boot)

import select as _sel
p = _sel.poll()
p.register(uart, _sel.POLLIN)
p.register(si, _sel.POLLIN)
while True:
    evts = p.poll(100)
    for obj, ev in evts:
        if obj is uart:
            d = uart.read()
            if d:
                so.write(d)
        else:
            d = si.read(1)
            if d:
                uart.write(d)
""".replace("__BITSTREAM_PATH__", BITSTREAM_DEVICE_PATH)


def reset_rp2350(port):
    """Send Ctrl-C to break any running MicroPython script on the RP2350.

    If the RP2350 is stuck in bridge mode from a previous session,
    mpremote cannot enter raw REPL.  Opening the serial port and
    sending Ctrl-C interrupts the running script.
    """
    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        try:
            tty.setraw(fd)
            for _ in range(3):
                os.write(fd, b"\x03")
                drain(fd, timeout=0.2)
            drain(fd, timeout=0.5)
        finally:
            os.close(fd)
    except OSError as e:
        print(f"Warning: could not reset RP2350: {e}")


def usb_power_cycle(port):
    """Power-cycle the RP2350's USB port via uhubctl as a last resort.

    Looks up which USB hub port hosts the device and cycles power.
    Only works if the RP2350 is solely USB-powered.
    """
    import glob as _glob

    # Find USB device backing ttyACM port
    acm_idx = port.replace("/dev/ttyACM", "")
    sysfs_matches = _glob.glob(f"/sys/class/tty/ttyACM{acm_idx}/device/..")
    if not sysfs_matches:
        return
    dev_path = os.path.realpath(sysfs_matches[0])
    # dev_path like /sys/devices/.../1-1.2  →  busport = "1-1.2"
    busport = os.path.basename(dev_path)
    if "." not in busport:
        return
    hub = busport.rsplit(".", 1)[0]  # "1-1"
    port_num = busport.rsplit(".", 1)[1]  # "2"
    print(f"USB power-cycling hub {hub} port {port_num}...")
    subprocess.call(["uhubctl", "-l", hub, "-p", port_num, "-a", "cycle"], timeout=15)
    # Poll for device re-enumeration instead of sleeping
    for _ in range(30):
        time.sleep(0.1)
        if os.path.exists(port):
            break


def _install_safe_main(port):
    """Replace the ttboard main.py with a minimal version.

    The stock ttboard main.py calls DemoBoard() which probes I2C and
    can hang permanently, making the RP2350 unrecoverable without a
    physical reset.  Replace it with a no-op so the REPL always starts.
    """
    try:
        result = subprocess.run(
            [
                "mpremote",
                "connect",
                port,
                "exec",
                "f = open('main.py', 'w')\n"
                "f.write('# Safe main.py for FPGA test automation\\n')\n"
                "f.write('print(\"TT FPGA board ready\")\\n')\n"
                "f.close()",
            ],
            timeout=30,
            capture_output=True,
        )
        if result.returncode != 0:
            print("Warning: safe main.py install failed (non-critical)", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("Warning: safe main.py install timed out (non-critical)", file=sys.stderr)


def upload_bitstream(port, local_path):
    """Upload bitstream to RP2350 filesystem via mpremote."""
    # Break any stuck MicroPython script before mpremote tries raw REPL.
    reset_rp2350(port)

    subprocess.call(
        ["mpremote", "connect", port, "exec", "import os\ntry:\n os.mkdir('/bitstreams')\nexcept OSError:\n pass"],
        timeout=30,
    )
    rc = subprocess.call(
        ["mpremote", "connect", port, "cp", local_path, ":" + BITSTREAM_DEVICE_PATH],
        timeout=120,
    )
    if rc != 0:
        # mpremote failed — try USB power cycle and retry once
        print("mpremote failed, trying USB power cycle recovery...")
        usb_power_cycle(port)
        reset_rp2350(port)
        subprocess.call(
            ["mpremote", "connect", port, "exec", "import os\ntry:\n os.mkdir('/bitstreams')\nexcept OSError:\n pass"],
            timeout=30,
        )
        rc = subprocess.call(
            ["mpremote", "connect", port, "cp", local_path, ":" + BITSTREAM_DEVICE_PATH],
            timeout=120,
        )
    if rc == 0:
        # Install safe main.py to prevent DemoBoard() hangs on reboot
        _install_safe_main(port)
    return rc == 0


def open_raw_serial(port):
    """Open a serial port in raw mode at 115200 baud using termios."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    # Set baud rate. cfsetispeed/cfsetospeed were added in Python 3.13;
    # fall back to direct index assignment for older versions.
    baud = termios.B115200
    if hasattr(termios, "cfsetispeed"):
        termios.cfsetispeed(attrs, baud)
        termios.cfsetospeed(attrs, baud)
    else:
        attrs[4] = baud  # ispeed
        attrs[5] = baud  # ospeed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def drain(fd, timeout=0.3):
    """Read and discard all pending data from a file descriptor."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.05)
        if fd in r:
            try:
                os.read(fd, 4096)
            except OSError:
                break
        else:
            break


def enter_raw_repl(fd):
    """Enter MicroPython raw REPL mode on the serial port."""
    os.write(fd, b"\x03")
    drain(fd, timeout=0.2)
    os.write(fd, b"\x03")
    drain(fd, timeout=0.3)
    os.write(fd, b"\x01")
    drain(fd, timeout=0.3)


def execute_raw_repl(fd, script, marker, timeout=60):
    """Send script via raw REPL, execute, wait for marker.

    Returns (success, data_after_marker).
    """
    if isinstance(script, str):
        script = script.encode()
    os.write(fd, script)
    os.write(fd, b"\x04")

    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.1)
        if fd in r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if data:
                buf += data
                if marker in buf:
                    marker_pos = buf.index(marker)
                    pre_marker = buf[:marker_pos]
                    print(
                        "Raw REPL output before marker ({} bytes): {}".format(
                            len(pre_marker), pre_marker.decode("utf-8", errors="replace")[:500]
                        )
                    )
                    idx = marker_pos + len(marker)
                    while idx < len(buf) and buf[idx : idx + 1] in (b"\r", b"\n"):
                        idx += 1
                    return True, buf[idx:]
    return False, buf


def main():
    if len(sys.argv) < 4:
        print("usage: tt_test_wrapper.py PORT BITSTREAM TEST_CMD [ARGS...]", file=sys.stderr)
        return 2

    port = sys.argv[1]
    bitstream = sys.argv[2]
    test_cmd = sys.argv[3:]

    # Step 1: Upload bitstream to RP2350
    print("Uploading bitstream to RP2350...")
    if not upload_bitstream(port, bitstream):
        print("ERROR: Failed to upload bitstream", file=sys.stderr)
        return 1
    print("Upload complete.")

    # Step 2: Open raw serial and program + bridge
    print("Opening raw serial to RP2350...")
    serial_fd = open_raw_serial(port)

    print("Entering raw REPL...")
    enter_raw_repl(serial_fd)

    print("Programming FPGA and starting UART bridge...")
    ok, extra_data = execute_raw_repl(
        serial_fd,
        PROGRAM_AND_BRIDGE_SCRIPT,
        marker=b"BRIDGE_ACTIVE",
        timeout=60,
    )
    if not ok:
        print("ERROR: Bridge did not activate", file=sys.stderr)
        print("Output: {}".format(extra_data.decode("utf-8", errors="replace")), file=sys.stderr)
        os.close(serial_fd)
        return 1

    print("FPGA programmed, UART bridge active.")
    print(f"Extra data after marker ({len(extra_data)} bytes): {extra_data[:200]!r}")

    # Step 3: Create PTY pair
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    pty_attrs = termios.tcgetattr(slave_fd)
    pty_attrs[0] = 0
    pty_attrs[1] = 0
    pty_attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    pty_attrs[3] = 0
    termios.tcsetattr(slave_fd, termios.TCSANOW, pty_attrs)

    if extra_data:
        os.write(master_fd, extra_data)

    # Wait for boot data from RP2350 bridge.  The MicroPython script
    # writes the captured FPGA boot banner to stdout AFTER the
    # BRIDGE_ACTIVE marker, so it arrives on serial_fd slightly after
    # execute_raw_repl() returns.  Read it here and inject into the
    # PTY so the test script sees the BIOS banner immediately.
    boot_deadline = time.monotonic() + 1.0
    while time.monotonic() < boot_deadline:
        r, _, _ = select.select([serial_fd], [], [], 0.2)
        if serial_fd in r:
            boot_data = os.read(serial_fd, 4096)
            if boot_data:
                os.write(master_fd, boot_data)
                print(f"Boot data forwarded to PTY ({len(boot_data)} bytes)")
                break
        else:
            # No more data within 200 ms — boot data has been consumed
            # or the FPGA didn't produce any.
            break

    # Step 4: Start relay thread
    relay_active = True
    relay_stats = {"serial_to_pty": 0, "pty_to_serial": 0}

    def relay_loop():
        while relay_active:
            try:
                r, _, _ = select.select([serial_fd, master_fd], [], [], 0.1)
                for ready_fd in r:
                    if ready_fd == serial_fd:
                        data = os.read(serial_fd, 4096)
                        if data:
                            os.write(master_fd, data)
                            relay_stats["serial_to_pty"] += len(data)
                    elif ready_fd == master_fd:
                        data = os.read(master_fd, 4096)
                        if data:
                            # Strip Ctrl-C (0x03) before forwarding to
                            # RP2350; MicroPython interprets it as
                            # KeyboardInterrupt which kills the bridge.
                            # The test script sends Ctrl-C to reset the
                            # BIOS command buffer, but our custom firmware
                            # doesn't need it.
                            data = data.replace(b"\x03", b"")
                            if data:
                                os.write(serial_fd, data)
                            relay_stats["pty_to_serial"] += len(data)
            except OSError as e:
                print(f"Relay error: {e}", flush=True)
                break
        print("Relay thread exiting", flush=True)

    relay_thread = threading.Thread(target=relay_loop, daemon=True)
    relay_thread.start()

    # Step 5: Run test script, replacing port with PTY.
    # Keep slave_fd open — closing it before the subprocess opens the
    # slave device would leave zero slave references, causing the relay
    # thread to get EIO from the PTY master.  We never read from
    # slave_fd so it won't steal data from the test subprocess.
    actual_cmd = [slave_name if arg == port else arg for arg in test_cmd]
    # Insert -u after python3 for unbuffered stdout so output isn't
    # lost if the subprocess is killed by timeout (SIGKILL).
    if actual_cmd and actual_cmd[0] in ("python3", "python"):
        actual_cmd.insert(1, "-u")
    print("Running: {}".format(" ".join(actual_cmd)), flush=True)
    try:
        rc = subprocess.call(actual_cmd, timeout=180)
    except subprocess.TimeoutExpired:
        print("ERROR: Test timed out", file=sys.stderr)
        rc = 1

    print(
        "Relay stats: serial->pty={}, pty->serial={}".format(relay_stats["serial_to_pty"], relay_stats["pty_to_serial"])
    )

    # Step 6: Cleanup -- send Ctrl-C to break the MicroPython bridge
    # script.  The relay is stopped first so Ctrl-C goes directly to
    # the RP2350 (not filtered by the relay's Ctrl-C stripping).
    relay_active = False
    relay_thread.join(timeout=2)
    try:
        os.write(serial_fd, b"\x03")
        drain(fd=serial_fd, timeout=0.2)
        os.write(serial_fd, b"\x03")
        drain(fd=serial_fd, timeout=0.2)
    except OSError:
        pass
    for fd in (master_fd, slave_fd, serial_fd):
        with contextlib.suppress(OSError):
            os.close(fd)

    return rc


if __name__ == "__main__":
    sys.exit(main())
