# Test Specifications

Automated boot-time hardware verification tests for the [fpgas.online](https://fpgas.online) platform.

## Purpose

Every FPGA board connected to the fpgas.online infrastructure must be verified as functional before it is made available to users. These tests run automatically during Raspberry Pi boot, programming the attached FPGA with a test design and exercising hardware interfaces to produce a clear pass/fail result.

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│   GitHub Actions     │     │   Raspberry Pi Host   │
│                     │     │                      │
│  LiteX + openXC7/   │────▶│  Pre-built bitstream  │
│  Yosys+nextpnr      │     │  loaded at boot       │
│  build bitstreams    │     │                      │
└─────────────────────┘     │  Test harness script  │
                            │  drives verification  │
                            │         │             │
                            └─────────┼─────────────┘
                                      │
                              ┌───────┴───────┐
                              │  FPGA Board   │
                              │               │
                              │  Test design  │
                              │  responds to  │
                              │  host queries │
                              └───────────────┘
```

**Flow:**

1. GitHub Actions builds bitstreams using open source toolchains (no vendor tools required).
2. Pre-built bitstreams are deployed to Raspberry Pi hosts.
3. On boot, the RPi programs the attached FPGA with the test bitstream.
4. The RPi runs the test harness script, which drives stimulus and reads responses.
5. Test results (pass/fail per test) are collected and reported.

Source: [Project README](../../README.md)

## Test Result Reporting

All FPGA test designs communicate results over UART at 115200 baud (the LiteX default). The host-side test harness script:

1. Opens the serial port connected to the FPGA (device path depends on board — see individual test specs).
2. Waits for the FPGA to boot and emit its identification string.
3. Sends test commands and reads responses.
4. Parses UART output for known pass/fail markers (e.g., `Memtest OK` / `Memtest KO` for DDR tests, JEDEC ID values for SPI flash, echo correctness for UART tests).
5. Aggregates results and reports overall pass/fail status.

For tests that do not use UART as the primary interface (e.g., PCIe enumeration), the host script directly inspects the host OS state (e.g., `lspci` output).

## Test Matrix

| Test | Arty A7 | NeTV2 | Fomu EVT | TT FPGA | Acorn / LiteFury |
|------|---------|-------|----------|---------|------------------|
| [PMOD Loopback](pmod-loopback.md) | Yes | Yes | Yes | Yes | Yes |
| [UART](uart.md) | Yes | Yes | Yes | Yes | Yes |
| [Ethernet](ethernet.md) | Yes | Yes | — | — | — |
| [PCIe Enumeration](pcie-enumeration.md) | — | Yes | — | — | Yes |
| [DDR Memory](ddr-memory.md) | Yes | Yes | — | — | Yes |
| [SPI Flash ID](spi-flash-id.md) | Yes | Yes | Yes | Yes | Yes |

Source: [Project README Test Matrix](../../README.md#test-matrix)

## Test Descriptions

### PMOD Loopback

Verifies PMOD/GPIO pin connectivity between the RPi and the FPGA board using pure combinational gateware (`output = ~input`). The RPi drives known bit patterns on one set of GPIO pins and reads the inverted result on another set. No UART, no CPU, no firmware needed. Supports Arty A7 (8-bit), NeTV2 (1-bit), Fomu EVT (4-bit), TT FPGA (8-bit), and Acorn (1-bit serial loopback).

See: [pmod-loopback.md](pmod-loopback.md)

### UART

Verifies bidirectional UART serial communication between the FPGA and host. The FPGA sends an identification string on boot, then echoes back test patterns sent by the host. Validates basic SoC functionality and serial link integrity.

See: [uart.md](uart.md)

### Ethernet

Verifies Ethernet connectivity by reading the MAC address, responding to ARP requests, and passing ICMP ping tests. Optionally tests TFTP data transfer integrity. Applicable to boards with Ethernet PHYs (Arty A7, NeTV2).

See: [ethernet.md](ethernet.md)

### PCIe Enumeration

Verifies that the FPGA's PCIe endpoint is detected and enumerated by the host. Checks vendor/device ID, link training, and BAR allocation. Applicable to NeTV2 (PCIe Gen2 x1 on RPi5) and Acorn/LiteFury (PCIe Gen2 x4 via mPCIe HAT on RPi5/CM4/CM5).

See: [pcie-enumeration.md](pcie-enumeration.md)

### DDR Memory

Verifies DDR3/SDRAM memory initialization, calibration, and data integrity using LiteX BIOS built-in memory tests (walking 1s, walking 0s, address bus, random data). Applicable to all boards with external DRAM.

See: [ddr-memory.md](ddr-memory.md)

### SPI Flash ID

Verifies the FPGA can communicate with its SPI configuration flash by reading the JEDEC manufacturer/device ID and comparing against expected values. The most universal test — applicable to all boards with SPI flash.

See: [spi-flash-id.md](spi-flash-id.md)

## References

- [LiteX SoC builder](https://github.com/enjoy-digital/litex) — Framework used for all test designs
- [Hardware Reference](../hardware/) — Board specs, pin mappings, host connections
- [Toolchain Guides](../toolchains/) — Building bitstreams with open source tools
