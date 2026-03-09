# UART Test

## Purpose

Verify bidirectional UART serial communication between the FPGA and the host. This is a fundamental test that validates the serial link used by most other tests for status reporting, and confirms basic SoC functionality.

## Target Boards

| Board | UART Interface | Serial Device Path | Status |
|-------|---------------|-------------------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | USB-UART via FTDI FT2232HQ | `/dev/ttyUSBx` | Active |
| [Kosagi NeTV2](../hardware/netv2.md) | GPIO UART via RPi GPIO14 (TX) / GPIO15 (RX) | `/dev/ttyAMA0` or `/dev/serial0` | Active |
| [TT FPGA Demo Board](../hardware/tt-fpga.md) | USB via RP2040 intermediary | TBD | TBD |

**Note on TT FPGA:** The RP2040 sits between the iCE40 FPGA and the USB host, which complicates direct UART testing. The RP2040 firmware must bridge UART data between the FPGA and USB. Status is TBD pending RP2040 firmware support.

## Prerequisites

- FPGA programmed with UART test bitstream (LiteX BIOS or custom firmware)
- Serial connection established between host and FPGA
- For Arty A7: USB cable connected (FTDI provides both JTAG and UART)
- For NeTV2: RPi GPIO14/GPIO15 connected to FPGA UART pins

## How It Works

### Step 1: FPGA Boot and Identification

1. The FPGA runs LiteX BIOS or custom firmware.
2. On boot, the firmware sends an identification string over UART containing:
   - Board name
   - Firmware version
   - Build timestamp
3. The host reads and validates this identification string.

### Step 2: Echo Test

1. The host sends an echo command to the FPGA.
2. The FPGA echoes the command back verbatim.
3. The host verifies the echoed data matches exactly.

### Step 3: Full Byte Range Test

1. The host sends a test pattern containing all byte values from `0x00` to `0xFF` (256 bytes).
2. The FPGA echoes each byte back.
3. The host compares every sent byte against the received byte.
4. This catches issues with specific bit patterns, flow control problems, or encoding errors.

### Step 4: Result

All three steps must pass for the test to succeed.

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| Identification string | Received correctly, matches expected board | Not received or garbled |
| Echo test | Echoed data matches sent data exactly | Any byte mismatch |
| Full byte range (0x00-0xFF) | 0% data loss, all 256 bytes echoed correctly | Any missing or incorrect bytes |

## Default Baud Rate

**115200 baud, 8N1** (8 data bits, no parity, 1 stop bit)

This is the LiteX default baud rate for all supported boards.

## LiteX UART Details

LiteX implements UART with a PHY and FIFO:

| Component | Description |
|-----------|-------------|
| UART PHY | Handles serialization/deserialization with configurable baud rate |
| TX FIFO | Buffers outgoing data (default depth: 16) |
| RX FIFO | Buffers incoming data (default depth: 16) |
| Baud rate generation | Phase accumulator: `tuning_word = int((baudrate / clk_freq) * 2**32)` |

The phase accumulator approach avoids the need for exact clock division, allowing accurate baud rate generation from any system clock frequency.

Source: [LiteX UART core](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/uart.py)

## Host-Side Tools

### Option 1: `litex_term`

LiteX provides a built-in serial terminal tool:

```
litex_term /dev/ttyUSBx --speed 115200
```

`litex_term` supports:
- Serial console interaction
- File upload via SFL (Serial Flash Loader) protocol
- Automatic port detection

Source: [litex_term](https://github.com/enjoy-digital/litex/blob/master/litex/tools/litex_term.py)

### Option 2: Python pyserial

```python
import serial

ser = serial.Serial('/dev/ttyUSBx', 115200, timeout=2)

# Read identification string
ident = ser.readline().decode('utf-8', errors='replace')

# Echo test
test_data = bytes(range(256))  # 0x00 to 0xFF
ser.write(test_data)
response = ser.read(len(test_data))
assert response == test_data, "Echo test failed"
```

Source: [pyserial documentation](https://pyserial.readthedocs.io/)

## Serial Device Paths

| Board | Device Path | Interface Chip | Notes |
|-------|-------------|---------------|-------|
| Arty A7 | `/dev/ttyUSBx` (typically `/dev/ttyUSB1`) | FTDI FT2232HQ | Channel 0 = JTAG, Channel 1 = UART |
| NeTV2 | `/dev/ttyAMA0` or `/dev/serial0` | Direct GPIO connection | RPi GPIO14 (TX), GPIO15 (RX); no level shifting needed (both 3.3V) |
| TT FPGA | TBD | RP2040 (USB CDC ACM) | Depends on RP2040 firmware configuration |

### Arty A7 FTDI Details

The Arty A7 uses an FTDI FT2232HQ dual-channel USB-to-serial converter:

- **Channel A (ttyUSB0):** JTAG interface for FPGA programming
- **Channel B (ttyUSB1):** UART interface for serial communication

The actual device index (`ttyUSBx`) depends on other USB-serial devices connected to the host. Use `udevadm` rules or serial number matching for deterministic identification.

Source: [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)

### NeTV2 GPIO UART Details

On the NeTV2, the FPGA UART connects directly to the Raspberry Pi's GPIO header:

- **RPi GPIO14 (pin 8):** TX (RPi transmits to FPGA)
- **RPi GPIO15 (pin 10):** RX (RPi receives from FPGA)

The RPi's built-in UART (`/dev/ttyAMA0`) must be freed from Bluetooth use. On RPi3, add `dtoverlay=disable-bt` to `/boot/config.txt`. On RPi5, the primary UART is available by default.

Source: [Raspberry Pi UART documentation](https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-uarts)

## References

- [LiteX UART core](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/uart.py)
- [litex_term serial terminal](https://github.com/enjoy-digital/litex/blob/master/litex/tools/litex_term.py)
- [pyserial](https://pyserial.readthedocs.io/)
- [FTDI FT2232HQ datasheet](https://ftdichip.com/products/ft2232hq/)
- [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)
- [RPi UART configuration](https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-uarts)
