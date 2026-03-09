# SPI Flash ID Test

## Purpose

Verify that the FPGA can communicate with its SPI configuration flash memory by reading the JEDEC manufacturer and device ID. This is the most universal test — it applies to every board that has SPI flash, and validates a fundamental interface required for persistent bitstream storage.

## Target Boards

| Board | SPI Flash | Expected JEDEC ID | Status |
|-------|-----------|-------------------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | Micron/Spansion (board-specific) | To be verified | Active |
| [Kosagi NeTV2](../hardware/netv2.md) | TBD | To be verified | Active |
| [Fomu EVT](../hardware/fomu-evt.md) | TBD | To be verified | Active |
| [TT FPGA Demo Board](../hardware/tt-fpga.md) | TBD | To be verified | Active |
| [Radiona ULX3S](../hardware/ulx3s.md) | TBD | To be verified | Planned |
| [GSG ButterStick](../hardware/butterstick.md) | TBD | To be verified | Planned |

**Note:** Exact JEDEC IDs need to be verified against the specific flash chip populated on each physical board, as different board revisions may use different flash vendors.

## Prerequisites

- FPGA programmed with SPI flash test bitstream (LiteX SoC with SPI flash access)
- UART connection for reading test results
- Knowledge of the expected JEDEC ID for the board revision under test

## How It Works

### Step 1: FPGA Design with SPI Flash Access

The FPGA is loaded with a LiteX SoC that includes SPI flash access via:

- **LiteSPI:** Full-featured SPI flash controller with PHY, or
- **Direct CSR access:** Simple SPI master with bit-banged or hardware-assisted transfers

Source: [LiteSPI library](https://github.com/litex-hub/litespi)

### Step 2: JEDEC ID Read

1. The firmware sends the JEDEC ID read command (`0x9F`) to the SPI flash.
2. The flash responds with 3 bytes:

| Byte | Field | Description |
|------|-------|-------------|
| 1 | Manufacturer ID | Identifies the flash vendor (e.g., `0x20` = Micron, `0x01` = Spansion/Cypress, `0xEF` = Winbond) |
| 2 | Device Type | Memory type code |
| 3 | Capacity | Encoded capacity (e.g., `0x18` = 2^24 = 16 MB) |

3. The firmware prints the JEDEC ID over UART.

### Step 3: Comparison

The host script compares the read JEDEC ID against the expected value for the board's flash chip.

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| SPI communication | JEDEC ID command returns valid data (non-zero, non-0xFF) | Returns `0x000000` or `0xFFFFFF` (no device / bus stuck) |
| Manufacturer ID | Matches expected vendor for the board | Wrong vendor or unknown ID |
| Device type/capacity | Matches expected flash chip model | Wrong device or unexpected capacity |

### Common Failure Modes

| Symptom | Likely Cause |
|---------|-------------|
| Returns `0xFFFFFF` | SPI bus not connected, flash not powered, or wrong CS pin |
| Returns `0x000000` | SPI MISO line stuck low, or flash in reset |
| Wrong manufacturer ID | Different flash chip than expected (check board revision) |
| Correct manufacturer, wrong capacity | Board revision with different flash size |

## JEDEC ID Reference

### Common SPI Flash Manufacturer IDs

| Manufacturer ID | Vendor |
|----------------|--------|
| `0x01` | Spansion / Cypress / Infineon |
| `0x20` | Micron / Numonyx / ST |
| `0xC2` | Macronix (MXIC) |
| `0xEF` | Winbond |
| `0x1F` | Adesto / Atmel |
| `0xBF` | SST / Microchip |

### Capacity Encoding

| Capacity Byte | Flash Size |
|--------------|------------|
| `0x14` | 1 MB (8 Mbit) |
| `0x15` | 2 MB (16 Mbit) |
| `0x16` | 4 MB (32 Mbit) |
| `0x17` | 8 MB (64 Mbit) |
| `0x18` | 16 MB (128 Mbit) |
| `0x19` | 32 MB (256 Mbit) |

Source: [JEDEC JEP106 manufacturer ID standard](https://www.jedec.org/standards-documents/docs/jep-106ab)

### Expected IDs Per Board (To Be Verified)

These values must be confirmed against the actual flash chips on each board:

| Board | Expected Vendor | Expected JEDEC ID | Notes |
|-------|----------------|-------------------|-------|
| Arty A7 | Micron or Spansion | TBD — varies by board revision | Check silkscreen on flash chip |
| NeTV2 | TBD | TBD | To be determined |
| Fomu EVT | TBD | TBD | To be determined |
| TT FPGA | TBD | TBD | To be determined |
| ULX3S | TBD | TBD | To be determined |
| ButterStick | TBD | TBD | To be determined |

## LiteX SPI Flash Details

### LiteSPI Architecture

```
┌──────────────┐
│   LiteX CPU  │
│   (BIOS)     │
│      │       │
│   Wishbone   │
│      │       │
│  ┌───┴─────┐ │
│  │ LiteSPI │ │
│  │         │ │
│  │ ┌─────┐ │ │
│  │ │ PHY │ │ │
│  │ └──┬──┘ │ │
│  └────┼────┘ │
└───────┼──────┘
        │ SPI bus
   ┌────┴────┐
   │  Flash  │
   │  Chip   │
   └─────────┘
```

### SPI Bus Signals

| Signal | Direction | Description |
|--------|-----------|-------------|
| SCK | FPGA -> Flash | Serial clock |
| CS# | FPGA -> Flash | Chip select (active low) |
| MOSI (DI) | FPGA -> Flash | Master Out, Slave In (data to flash) |
| MISO (DO) | Flash -> FPGA | Master In, Slave Out (data from flash) |
| WP# | FPGA -> Flash | Write protect (active low, optional) |
| HOLD# | FPGA -> Flash | Hold (pauses communication, optional) |

For Quad SPI (QSPI) flash, MOSI and MISO are replaced by 4 bidirectional data lines (IO0-IO3).

### JEDEC ID Read Command

| Phase | Data | Direction |
|-------|------|-----------|
| Command | `0x9F` | FPGA -> Flash |
| Response byte 1 | Manufacturer ID | Flash -> FPGA |
| Response byte 2 | Device type | Flash -> FPGA |
| Response byte 3 | Capacity | Flash -> FPGA |

### CSR Register Access

In LiteX, SPI flash can be accessed via CSR registers:

| Register | Function |
|----------|----------|
| `spiflash_bitbang` | Bit-bang SPI signals (SCK, CS#, MOSI, MISO) |
| `spiflash_mmap` | Memory-mapped flash access (for XIP) |

Source: [LiteSPI library](https://github.com/litex-hub/litespi)

## Host-Side Test Script

```python
import serial

ser = serial.Serial('/dev/ttyUSBx', 115200, timeout=10)

# Send JEDEC ID read command via LiteX BIOS console
ser.write(b'spi_flash_id\r\n')

# Parse response
response = ser.readline().decode('utf-8', errors='replace').strip()
# Expected format: "JEDEC ID: 0xXX 0xXX 0xXX"

# Compare against expected values
expected_jedec_id = (0x20, 0xBA, 0x18)  # Example: Micron 128Mbit
# ... validate and report pass/fail
```

## References

- [LiteSPI library](https://github.com/litex-hub/litespi) — SPI flash controller for LiteX
- [LiteX SoC builder](https://github.com/enjoy-digital/litex)
- [JEDEC JEP106 manufacturer ID standard](https://www.jedec.org/standards-documents/docs/jep-106ab)
- [SPI flash command set (JEDEC JESD216)](https://www.jedec.org/standards-documents/docs/jesd216b)
- [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)
