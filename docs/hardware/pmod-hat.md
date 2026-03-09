# Digilent PMOD HAT Adapter

The Digilent PMOD HAT Adapter connects standard Digilent PMOD modules to a Raspberry Pi's 40-pin GPIO header. In the fpgas.online infrastructure, it enables direct signal connections between a Raspberry Pi host and FPGA boards with PMOD connectors (such as the Arty A7 and TT FPGA Demo Board).

## Key Specifications

| Parameter | Value |
|-----------|-------|
| PMOD ports | 3x 12-pin (JA, JB, JC) |
| Total signal pins | 24 (8 per port) |
| Logic level | 3.3V (matches RPi GPIO) |
| Max current per pin | 16 mA |
| RPi header | 40-pin GPIO (Pi 2/3/4/5 compatible) |
| Unused GPIO | 5 pins available (GPIO22, GPIO23, GPIO24, GPIO25, GPIO27) |

Source: [Digilent PMOD HAT Reference Manual](https://digilent.com/reference/add-ons/pmod-hat/reference-manual)

## PMOD Standard Connector Definition

### 6-Pin PMOD (Half PMOD)

```
┌───────────────────────┐
│ Pin1  Pin2  Pin3  Pin4│  ← 4 signal pins
│ GND               VCC│  ← Power
└───────────────────────┘
```

| Pin | Function |
|-----|----------|
| 1 | Signal (I/O 1) |
| 2 | Signal (I/O 2) |
| 3 | Signal (I/O 3) |
| 4 | Signal (I/O 4) |
| 5 | GND |
| 6 | VCC (3.3V) |

### 12-Pin PMOD (Full PMOD)

```
┌───────────────────────────────────────────┐
│ Pin1  Pin2  Pin3  Pin4   GND   VCC        │  ← Top row
│ Pin7  Pin8  Pin9  Pin10  GND   VCC        │  ← Bottom row
└───────────────────────────────────────────┘
```

| Pin | Function |
|-----|----------|
| 1 | Signal (I/O 1) |
| 2 | Signal (I/O 2) |
| 3 | Signal (I/O 3) |
| 4 | Signal (I/O 4) |
| 5 | GND |
| 6 | VCC (3.3V) |
| 7 | Signal (I/O 5) |
| 8 | Signal (I/O 6) |
| 9 | Signal (I/O 7) |
| 10 | Signal (I/O 8) |
| 11 | GND |
| 12 | VCC (3.3V) |

Source: [Digilent PMOD Specification](https://digilent.com/reference/pmod/specification)

## PMOD Types

The Digilent PMOD specification defines several standard types based on pin function assignment:

| Type | Name | Pin 1 | Pin 2 | Pin 3 | Pin 4 |
|------|------|-------|-------|-------|-------|
| Type 1 | GPIO | I/O 1 | I/O 2 | I/O 3 | I/O 4 |
| Type 2 | SPI | CS | MOSI | MISO | SCK |
| Type 3 | UART | CTS | TX | RX | RTS |
| Type 5 | H-bridge | DIR | EN | SA | SB |
| Type 6 | I2C | INT | RESET | SCL | SDA |

Type 1 (GPIO) is the most common and is used for general-purpose I/O including loopback testing.

Source: [Digilent PMOD Specification](https://digilent.com/reference/pmod/specification)

## RPi GPIO to PMOD Pin Mapping

The PMOD HAT maps Raspberry Pi GPIO pins to three PMOD ports (JA, JB, JC). Each PMOD port has 8 signal pins (top row pins 1-4 and bottom row pins 7-10).

### Port JA

| PMOD Pin | Signal | RPi GPIO | RPi Header Pin | BCM Function |
|----------|--------|----------|----------------|-------------|
| JA1 (top 1) | I/O 1 | GPIO6 | Pin 31 | |
| JA2 (top 2) | I/O 2 | GPIO13 | Pin 33 | |
| JA3 (top 3) | I/O 3 | GPIO19 | Pin 35 | PCM_FS |
| JA4 (top 4) | I/O 4 | GPIO26 | Pin 37 | |
| JA7 (bottom 1) | I/O 5 | GPIO12 | Pin 32 | PWM0 |
| JA8 (bottom 2) | I/O 6 | GPIO16 | Pin 36 | |
| JA9 (bottom 3) | I/O 7 | GPIO20 | Pin 38 | PCM_DIN |
| JA10 (bottom 4) | I/O 8 | GPIO21 | Pin 40 | PCM_DOUT |

### Port JB

| PMOD Pin | Signal | RPi GPIO | RPi Header Pin | BCM Function |
|----------|--------|----------|----------------|-------------|
| JB1 (top 1) | I/O 1 | GPIO5 | Pin 29 | |
| JB2 (top 2) | I/O 2 | GPIO11 | Pin 23 | SPI0_SCLK |
| JB3 (top 3) | I/O 3 | GPIO9 | Pin 21 | SPI0_MISO |
| JB4 (top 4) | I/O 4 | GPIO10 | Pin 19 | SPI0_MOSI |
| JB7 (bottom 1) | I/O 5 | GPIO7 | Pin 26 | SPI0_CE1 |
| JB8 (bottom 2) | I/O 6 | GPIO8 | Pin 24 | SPI0_CE0 |
| JB9 (bottom 3) | I/O 7 | GPIO0 | Pin 27 | I2C0_SDA |
| JB10 (bottom 4) | I/O 8 | GPIO1 | Pin 28 | I2C0_SCL |

### Port JC

| PMOD Pin | Signal | RPi GPIO | RPi Header Pin | BCM Function |
|----------|--------|----------|----------------|-------------|
| JC1 (top 1) | I/O 1 | GPIO17 | Pin 11 | |
| JC2 (top 2) | I/O 2 | GPIO18 | Pin 12 | PWM0 |
| JC3 (top 3) | I/O 3 | GPIO4 | Pin 7 | GPCLK0 |
| JC4 (top 4) | I/O 4 | GPIO14 | Pin 8 | TXD |
| JC7 (bottom 1) | I/O 5 | GPIO2 | Pin 3 | I2C1_SDA |
| JC8 (bottom 2) | I/O 6 | GPIO3 | Pin 5 | I2C1_SCL |
| JC9 (bottom 3) | I/O 7 | GPIO15 | Pin 10 | RXD |
| JC10 (bottom 4) | I/O 8 | GPIO25 | Pin 22 | |

**Important note about JC**: Several JC pins overlap with commonly used RPi functions:
- GPIO14/15 (JC4/JC9) are the default UART TX/RX pins. If using GPIO UART for NeTV2 communication, these pins are not available for PMOD.
- GPIO4 (JC3) is used for JTAG TCK in the NeTV2 OpenOCD configuration.
- GPIO2/3 (JC7/JC8) are the default I2C1 bus pins with hardware pull-ups.

Source: [Digilent PMOD HAT Reference Manual](https://digilent.com/reference/add-ons/pmod-hat/reference-manual)

## Unused GPIO Pins

The following RPi GPIO pins are NOT assigned to any PMOD port and remain available for other uses:

| RPi GPIO | RPi Header Pin | Notes |
|----------|----------------|-------|
| GPIO22 | Pin 15 | Free |
| GPIO23 | Pin 16 | Free |
| GPIO24 | Pin 18 | Used as SRST in NeTV2 OpenOCD config |
| GPIO25 | Pin 22 | Free (but assigned to JC10 in some HAT revisions) |
| GPIO27 | Pin 13 | Used as TDI in NeTV2 OpenOCD config |

Source: [Digilent PMOD HAT Reference Manual](https://digilent.com/reference/add-ons/pmod-hat/reference-manual)

## Electrical Characteristics

| Parameter | Value |
|-----------|-------|
| Logic voltage | 3.3V (supplied by RPi's 3.3V rail) |
| Max current per GPIO pin | 16 mA (RPi BCM2835/BCM2711 limit) |
| Total GPIO current budget | ~50 mA across all pins (RPi limitation) |
| VCC on PMOD connectors | 3.3V (from RPi 3.3V rail) |
| Input threshold (low) | ~0.8V |
| Input threshold (high) | ~1.3V |

The PMOD HAT does not include any level shifters or buffers -- signals pass directly from RPi GPIO to PMOD connectors. This means the 3.3V logic level and current limits of the RPi GPIO apply directly.

## Usage in fpgas.online

### PMOD Loopback Test

The primary use of the PMOD HAT in the test infrastructure is the PMOD loopback test:

1. The RPi drives known patterns out through its GPIO pins to the PMOD HAT
2. The PMOD HAT connector is plugged into a PMOD port on the FPGA board (e.g., Arty A7's JA)
3. The FPGA design echoes/loops back the signals (or the signals are looped back externally)
4. The RPi reads back the signals and verifies correctness

This tests the end-to-end signal path: RPi GPIO -> PMOD HAT -> cable -> FPGA PMOD port -> FPGA fabric -> (loopback) -> FPGA PMOD port -> cable -> PMOD HAT -> RPi GPIO.

### Connecting to Arty A7

When connecting the PMOD HAT to an Arty A7 PMOD port, the RPi GPIO pins map to FPGA pins as follows (example using PMOD HAT port JA connected to Arty PMODA):

| PMOD Pin | RPi GPIO | Arty PMODA FPGA Pin |
|----------|----------|---------------------|
| Pin 1 | GPIO6 | G13 |
| Pin 2 | GPIO13 | B11 |
| Pin 3 | GPIO19 | A11 |
| Pin 4 | GPIO26 | D12 |
| Pin 7 | GPIO12 | D13 |
| Pin 8 | GPIO16 | B18 |
| Pin 9 | GPIO20 | A18 |
| Pin 10 | GPIO21 | K16 |

## References

- Digilent PMOD HAT Reference Manual: <https://digilent.com/reference/add-ons/pmod-hat/reference-manual>
- Digilent PMOD Specification: <https://digilent.com/reference/pmod/specification>
- Digilent PMOD HAT Product Page: <https://digilent.com/shop/pmod-hat-adapter/>
