# DDR Memory Test

## Purpose

Verify that DDR3 or SDRAM memory connected to the FPGA is functional and reliable. This test exercises the memory controller, PHY calibration, and data integrity using LiteX BIOS built-in memory tests.

## Target Boards

| Board | Memory Type | Size | Data Width | Status |
|-------|------------|------|------------|--------|
| [Digilent Arty A7](../hardware/arty-a7.md) | DDR3 | 256 MB | 16-bit | Active |
| [Kosagi NeTV2](../hardware/netv2.md) | DDR3 | 512 MB | 32-bit | Active |
| [Sqrl Acorn CLE-215+](../hardware/acorn.md) | DDR3 | 1 GB | 32-bit | Active |
| [LiteFury](../hardware/acorn.md) | DDR3 | 512 MB | 32-bit | Active |

## Prerequisites

- FPGA programmed with DDR memory test bitstream (LiteX SoC with SDRAM enabled)
- UART connection for reading test results
- No other DRAM access during test (test runs at boot before any application firmware)

## How It Works

### Step 1: DRAM Initialization

On boot, the LiteX BIOS automatically initializes the DRAM subsystem:

1. **PHY initialization:** Configures the DDR PHY timing parameters (CAS latency, write leveling delays, etc.)
2. **Read leveling:** Adjusts read DQS delays to center the data eye for each byte lane.
3. **Write leveling:** Adjusts write DQS delays relative to CK for each byte lane.
4. **Calibration:** Fine-tunes all timing parameters for reliable operation at the target frequency.

All calibration results are printed over UART as they complete.

### Step 2: Memory Size Detection

The BIOS probes the memory to determine its size, verifying it matches the expected capacity for the board.

### Step 3: Built-in Memtest

The LiteX BIOS runs its built-in memory test suite, which includes:

| Test Pattern | Description | What It Catches |
|-------------|-------------|-----------------|
| Walking 1s | Shifts a single `1` bit through each position | Stuck-at-0 faults, data line shorts |
| Walking 0s | Shifts a single `0` bit through each position | Stuck-at-1 faults, data line shorts |
| Address bus test | Writes unique patterns to power-of-2 addresses | Address line faults, aliasing |
| Random data | Writes pseudo-random patterns and reads back | Intermittent faults, pattern sensitivity |

The BIOS tests a configurable region of memory (typically the first few MB).

### Step 4: Result Reporting

Results are printed over UART:

- **Pass:** `Memtest OK`
- **Fail:** `Memtest KO` followed by the error count and first failing address

Source: [LiteX BIOS memtest](https://github.com/enjoy-digital/litex/blob/master/litex/soc/software/bios/cmds/cmd_mem.c)

## Pass/Fail Criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| DRAM calibration | Completes successfully (read/write leveling converges) | Calibration fails or times out |
| Memory size | Correct size detected for the board | Wrong size or no memory detected |
| Walking 1s | 0 errors | Any errors |
| Walking 0s | 0 errors | Any errors |
| Address bus test | 0 errors | Any errors |
| Random data test | 0 errors | Any errors |
| Overall result | UART outputs `Memtest OK` | UART outputs `Memtest KO` |

## LiteX DRAM Details

### LiteDRAM Library

LiteDRAM handles all aspects of DRAM interfacing:

| Component | Function |
|-----------|----------|
| PHY | Technology-specific I/O interface (Xilinx 7-Series, ECP5, iCE40, etc.) |
| Controller | Manages DRAM protocol (activate, read, write, precharge, refresh) |
| Calibration | Read/write leveling, DQS centering |
| Crossbar | Arbitrates multiple master access to DRAM |
| Bandwidth | Reports DRAM bandwidth via CSR registers |

Source: [LiteDRAM library](https://github.com/enjoy-digital/litedram)

### Build Configuration

| Flag | Purpose |
|------|---------|
| `--with-sdram` | Enable SDRAM controller (default for boards with DRAM) |
| `--sdram-module` | Specify DRAM chip model (e.g., `MT41K128M16`) |
| `--sdram-rate` | Data rate: `1:1`, `1:2`, or `1:4` |
| `--sdram-size` | Override detected memory size |

### BIOS Memtest Output Format

Example successful output (Arty A7):

```
SDRAM now under software control
Read leveling:
  m0, b0: |00000000000000000000000001111100000| delays: 25+-2
  best: m0, b0 delays: 25+-2
...
Memtest at 0x40000000 (2.0MiB)...
  Write: 0x40000000-0x40200000 2MiB
   Read: 0x40000000-0x40200000 2MiB
Memtest OK
```

Example failed output:

```
Memtest at 0x40000000 (2.0MiB)...
  Write: 0x40000000-0x40200000 2MiB
   Read: 0x40000000-0x40200000 2MiB
Memtest KO: 42 errors
```

## Board-Specific Details

### Arty A7 — DDR3 (256 MB, 16-bit)

| Parameter | Value |
|-----------|-------|
| DRAM chip | Micron MT41K128M16JT-125 (or equivalent) |
| Capacity | 256 MB (2 Gbit) |
| Data width | 16-bit |
| Clock frequency | 100 MHz (DDR3-800 effective) |
| LiteX target | `digilent_arty` |

Source: [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)

### NeTV2 — DDR3 (512 MB, 32-bit)

| Parameter | Value |
|-----------|-------|
| Capacity | 512 MB |
| Data width | 32-bit (2x 16-bit chips) |
| LiteX target | `kosagi_netv2` |

Source: [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)

### ULX3S — SDR SDRAM (32 MB, 16-bit)

| Parameter | Value |
|-----------|-------|
| DRAM type | SDR SDRAM (not DDR) |
| Capacity | 32 MB |
| Data width | 16-bit |
| LiteX target | `radiona_ulx3s` |

Note: SDR SDRAM is simpler than DDR3 — no read/write leveling required.

Source: [ULX3S documentation](https://github.com/emard/ulx3s)

## Host-Side Test Script

The host script monitors UART output for the memtest result:

```python
import serial

ser = serial.Serial('/dev/ttyUSBx', 115200, timeout=30)

# Wait for memtest result (BIOS runs it automatically on boot)
while True:
    line = ser.readline().decode('utf-8', errors='replace').strip()
    if 'Memtest OK' in line:
        print("PASS: DDR memory test passed")
        break
    elif 'Memtest KO' in line:
        print(f"FAIL: {line}")
        break
    elif 'calibration' in line.lower() and 'fail' in line.lower():
        print(f"FAIL: DRAM calibration failed: {line}")
        break
```

## References

- [LiteDRAM library](https://github.com/enjoy-digital/litedram) — DRAM controller, PHY, and calibration
- [LiteX BIOS memtest source](https://github.com/enjoy-digital/litex/blob/master/litex/soc/software/bios/cmds/cmd_mem.c)
- [LiteX SoC builder](https://github.com/enjoy-digital/litex)
- [Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)
- [NeTV2 FPGA repository](https://github.com/AlphamaxMedia/netv2-fpga)
- [ULX3S documentation](https://github.com/emard/ulx3s)
- [Micron DDR3 SDRAM datasheet](https://www.micron.com/products/dram/ddr3-sdram)
