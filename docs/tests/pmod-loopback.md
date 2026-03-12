# PMOD Loopback Test

## Purpose

Verify PMOD connector connectivity between the Raspberry Pi and the FPGA board. The FPGA performs a pure combinational bitwise inversion (`output = ~input`), and the RPi verifies it by driving patterns on one set of pins and reading the inverted result on another set.

No CPU, no UART, no firmware required on the FPGA.

## Target Boards

| Board | Interface | Pin Width | Status |
|-------|-----------|-----------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | PMOD A top row (input) / PMOD A bottom row (output) | 4-bit | Active |
| [Kosagi NeTV2](../hardware/netv2.md) | Serial pins E13 (input) / E14 (output) | 1-bit | Active |
| [Fomu EVT](../hardware/fomu-evt.md) | Half-PMOD A (input) / Half-PMOD B (output) | 4-bit | Active |

## Prerequisites

- Raspberry Pi with appropriate GPIO wiring to the FPGA board
- FPGA programmed with the matching `gpio_loopback` bitstream
- `libgpiod2` installed on the RPi (`apt install libgpiod2 python3-libgpiod`)
- No UART connection needed

## How It Works

### Architecture

```
RPi GPIO (drive pins) ──→ FPGA input pins ──→ [~] ──→ FPGA output pins ──→ RPi GPIO (read pins)
```

The design is pure combinational logic: the FPGA connects output pins to the bitwise inversion of the input pins. There is no clock, no CPU, no firmware.

### Step 1: FPGA Gateware

The FPGA is loaded with a minimal bitstream containing only:

```
output_pins = ~input_pins
```

- **Arty A7**: 4-bit inversion from PMOD A top row to PMOD A bottom row
- **NeTV2**: 1-bit inversion from serial RX pin (E13) to serial TX pin (E14)
- **Fomu EVT**: 4-bit inversion from half-PMOD A to half-PMOD B

No clock domain, CRG, CPU, or bus infrastructure is needed.

### Step 2: RPi Drives and Reads

1. The RPi configures its "drive" GPIO pins as outputs and "read" GPIO pins as inputs.
2. For each test pattern:
   a. RPi writes the pattern to the drive pins (connected to FPGA inputs).
   b. Short delay for signal propagation (~1 ms).
   c. RPi reads the read pins (connected to FPGA outputs).
   d. Verifies: `read_value == ~pattern` (masked to pin width).
3. Reports pass/fail per pattern.

### Test Patterns

Patterns are adapted to the pin width:

| Pattern Type | 4-bit (Arty/Fomu) | 1-bit (NeTV2) |
|-------------|-------------------|---------------|
| All zeros | 0x0 | 0 |
| All ones | 0xF | 1 |
| Walking 1 | 0x1..0x8 | (same as all-ones) |
| Walking 0 | 0xE..0x7 | (same as all-zeros) |
| Alternating | 0xA, 0x5 | N/A |

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| Inversion check | All patterns: `read == ~sent` | Any mismatch |
| All pins tested | Every pin exercised individually via walking patterns | Any pin untested |

## FPGA Design Requirements

| Component | Details |
|-----------|---------|
| Logic | Pure combinational: `output = ~input` |
| Clock | None required |
| CPU | None |
| Firmware | None |
| Toolchain (Arty) | openXC7 (yosys + nextpnr-xilinx) |
| Toolchain (NeTV2) | openXC7 (yosys + nextpnr-xilinx) |
| Toolchain (Fomu) | icestorm (yosys + nextpnr-ice40) |

## Host-Side Test Script

The test harness runs on the Raspberry Pi and requires:

| Dependency | Purpose |
|------------|---------|
| `gpiod` | Drive and read GPIO pins via libgpiod |
| Python 3 | Script runtime |

No `pyserial` or UART communication is needed.

### Usage

```bash
# Build gateware
make gateware-arty
make gateware-netv2
make gateware-fomu

# Program FPGA
make program-arty

# Run test
uv run python host/test_pmod_loopback.py --board arty
uv run python host/test_pmod_loopback.py --board netv2
uv run python host/test_pmod_loopback.py --board fomu
```

## Pin Mapping Reference

### Arty A7

Uses a single PMOD cable from RPi PMOD HAT JA to Arty PMOD A (JA). The top row is input, the bottom row is output, on the same connector.

| RPi PMOD HAT JA (drive) | Arty PMOD A top row (FPGA in) |
|--------------------------|-------------------------------|
| GPIO 6 (JA1)  | pmoda:0 (pin 1) |
| GPIO 13 (JA2) | pmoda:1 (pin 2) |
| GPIO 19 (JA3) | pmoda:2 (pin 3) |
| GPIO 26 (JA4) | pmoda:3 (pin 4) |

| RPi PMOD HAT JA (read) | Arty PMOD A bottom row (FPGA out) |
|-------------------------|-----------------------------------|
| GPIO 12 (JA7)  | pmoda:4 (pin 7)  |
| GPIO 16 (JA8)  | pmoda:5 (pin 8)  |
| GPIO 20 (JA9)  | pmoda:6 (pin 9)  |
| GPIO 21 (JA10) | pmoda:7 (pin 10) |

### NeTV2

| RPi GPIO | FPGA Pin | Direction |
|----------|----------|-----------|
| GPIO 14 (TX) | E13 (serial RX) | RPi drives -> FPGA input |
| GPIO 15 (RX) | E14 (serial TX) | FPGA output -> RPi reads |

### Fomu EVT

| Connector | FPGA Pins | Direction |
|-----------|-----------|-----------|
| pmoda_n | 28, 27, 26, 23 | Input (RPi drives) |
| pmodb_n | 48, 47, 46, 45 | Output (RPi reads) |

RPi GPIO pin mapping depends on physical wiring (TBD).

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

- [LiteX build system](https://github.com/enjoy-digital/litex) (used for platform definitions and build infrastructure)
- [Migen](https://github.com/m-labs/migen) (HDL used for combinational logic)
- [Digilent PMOD Specification](https://digilent.com/reference/pmod/start)
- [libgpiod (gpiod)](https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git/)
