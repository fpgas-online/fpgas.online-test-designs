# PMOD Loopback Test

## Purpose

Verify PMOD connector connectivity between the Raspberry Pi PMOD HAT and the FPGA board. This test confirms that all PMOD pins can transmit and receive data in both directions, catching wiring errors, broken traces, or loose connections.

## Target Boards

| Board | PMOD Interface | Status |
|-------|---------------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | Standard 12-pin PMOD connectors (JA, JB, JC, JD) | Active |
| [TT FPGA Demo Board](../hardware/tt-fpga.md) | PMOD connector on demo board | Active |

## Prerequisites

- Raspberry Pi with [PMOD HAT](../hardware/pmod-hat.md) installed
- PMOD cable connecting RPi PMOD HAT to FPGA board PMOD connector
- FPGA programmed with the PMOD loopback test bitstream
- UART connection available for status reporting

## How It Works

### Step 1: FPGA Design

The FPGA is loaded with a LiteX SoC design that includes:

- GPIO cores mapped to each PMOD connector pin via CSR (Control and Status Register) bus
- UART core for status reporting at 115200 baud
- Each PMOD pin is individually controllable as input or output via CSR registers

### Step 2: RPi Drives Patterns (RPi-to-FPGA Direction)

1. The RPi host script configures PMOD HAT GPIO pins as outputs.
2. The FPGA configures its PMOD GPIO cores as inputs.
3. The RPi drives known bit patterns on each PMOD pin:
   - Walking 1: `0b00000001`, `0b00000010`, `0b00000100`, ... (one pin high at a time)
   - Walking 0: `0b11111110`, `0b11111101`, `0b11111011`, ... (one pin low at a time)
   - All-ones: `0b11111111`
   - All-zeros: `0b00000000`
4. For each pattern, the FPGA reads the GPIO input register and reports the value over UART.
5. The host script reads the UART response and compares against the expected pattern.

### Step 3: FPGA Drives Patterns (FPGA-to-RPi Direction)

1. The FPGA reconfigures its PMOD GPIO cores as outputs.
2. The RPi reconfigures PMOD HAT GPIO pins as inputs.
3. The host script sends a command over UART telling the FPGA which pattern to drive.
4. The FPGA drives the requested pattern on its PMOD pins.
5. The RPi reads the PMOD HAT GPIO pins and compares against the expected pattern.

### Step 4: Result

Both directions must match for all patterns. Any mismatch indicates a connectivity problem on the specific pin(s) that failed.

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| RPi-to-FPGA direction | All patterns read correctly by FPGA | Any pin mismatch |
| FPGA-to-RPi direction | All patterns read correctly by RPi | Any pin mismatch |
| All PMOD pins tested | Every pin exercised individually | Any pin untested |

## FPGA Design Requirements

| Component | Details |
|-----------|---------|
| SoC framework | LiteX |
| GPIO cores | CSR-mapped GPIO for each PMOD pin, individually configurable as input/output |
| UART | 115200 baud, 8N1 |
| CSR bus | Default LiteX CSR bus for register access from firmware |

The GPIO cores use LiteX's `CSRStorage` (for output) and `CSRStatus` (for input) registers. Each PMOD connector has 8 data pins (pins 1-4 and 7-10 on a standard 12-pin PMOD; pins 5, 6, 11, 12 are power/ground).

Source: [LiteX GPIO module](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/gpio.py)

## Host-Side Test Script

The test harness runs on the Raspberry Pi and requires:

| Dependency | Purpose |
|------------|---------|
| `RPi.GPIO` or `gpiod` | Drive and read PMOD HAT GPIO pins |
| `pyserial` | Communicate with FPGA over UART at 115200 baud |
| Python 3 | Script runtime |

### Script Flow

```python
# Pseudocode
import serial
import RPi.GPIO  # or gpiod

# Open UART to FPGA
uart = serial.Serial('/dev/ttyUSBx', 115200, timeout=2)

# Test RPi -> FPGA direction
for pattern in test_patterns:
    set_pmod_hat_outputs(pattern)
    fpga_reading = read_uart_response(uart)
    assert fpga_reading == pattern, f"RPi->FPGA mismatch: sent {pattern}, got {fpga_reading}"

# Test FPGA -> RPi direction
for pattern in test_patterns:
    send_uart_command(uart, f"DRIVE {pattern}")
    rpi_reading = read_pmod_hat_inputs()
    assert rpi_reading == pattern, f"FPGA->RPi mismatch: expected {pattern}, got {rpi_reading}"
```

## Pin Mapping Reference

- **RPi PMOD HAT pin mapping**: See [docs/hardware/pmod-hat.md](../hardware/pmod-hat.md)
- **Arty A7 PMOD connectors**: See [docs/hardware/arty-a7.md](../hardware/arty-a7.md)
- **TT FPGA PMOD connector**: See [docs/hardware/tt-fpga.md](../hardware/tt-fpga.md)

### Standard PMOD Pinout (12-pin)

| Pin | Function | Pin | Function |
|-----|----------|-----|----------|
| 1 | IO1 | 7 | IO5 |
| 2 | IO2 | 8 | IO6 |
| 3 | IO3 | 9 | IO7 |
| 4 | IO4 | 10 | IO8 |
| 5 | GND | 11 | GND |
| 6 | VCC | 12 | VCC |

Source: [Digilent PMOD Specification](https://digilent.com/reference/pmod/start)

## References

- [LiteX SoC builder](https://github.com/enjoy-digital/litex)
- [LiteX GPIO core](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/gpio.py)
- [Digilent PMOD Specification](https://digilent.com/reference/pmod/start)
- [RPi.GPIO documentation](https://pypi.org/project/RPi.GPIO/)
- [libgpiod (gpiod)](https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git/)
