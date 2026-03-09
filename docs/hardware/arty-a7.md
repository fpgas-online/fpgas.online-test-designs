# Digilent Arty A7

The Digilent Arty A7 is a Xilinx Artix-7 development board used in the fpgas.online test infrastructure. It connects to the host via USB (FTDI FT2232HQ providing both JTAG and UART) and optionally through PMOD connectors via a PMOD HAT adapter on a Raspberry Pi.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA (A7-35 variant) | Xilinx Artix-7 XC7A35T**I**CSG324-1L |
| FPGA (A7-100 variant) | Xilinx Artix-7 XC7A100TCSG324-1 |
| Package | CSG324 (324-ball BGA) |
| System clock | 100 MHz (pin E3, LVCMOS33) |
| DDR3 SDRAM | 256 MB, MT41K128M16JT-125 (16-bit bus) |
| Ethernet PHY | TI DP83848J, MII interface (100Base-T) |
| USB-UART/JTAG | FTDI FT2232HQ (dual-channel) |
| SPI Flash | Quad SPI (pins L13, L16, K17, K18, L14, M14) |
| User LEDs | 4 green (H5, J5, T9, T10) + 4 RGB |
| User switches | 4 (A8, C11, C10, A10) |
| User buttons | 4 (D9, C9, B9, B8) |
| PMOD connectors | 4x 12-pin (JA, JB, JC, JD) |
| I/O standard | LVCMOS33 (3.3V) for most I/O |
| Power | USB or external 7-15V |

Source: [Digilent Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)

## FPGA Device Variants

The LiteX platform file defines two variants:

| Variant | Device String | Notes |
|---------|--------------|-------|
| `a7-35` | `xc7a35ticsg324-1L` | Industrial temp, low power |
| `a7-100` | `xc7a100tcsg324-1` | Larger fabric, commercial temp |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

## Serial (UART)

The primary serial port uses the FTDI FT2232HQ USB-to-UART bridge:

| Signal | FPGA Pin | I/O Standard |
|--------|----------|-------------|
| TX | D10 | LVCMOS33 |
| RX | A9 | LVCMOS33 |

The FTDI chip provides two channels: Channel A for JTAG and Channel B for UART. The UART typically appears as `/dev/ttyUSB1` on Linux (the second of two USB serial devices created by the FT2232HQ).

## DDR3 SDRAM

- Part: MT41K128M16JT-125 (Micron, 128M x 16-bit = 256 MB)
- Interface: 16-bit data bus (DQ[15:0]), 2 byte lanes (DM/DQS pairs)
- I/O Standard: SSTL135 (1.35V)
- FPGA I/O bank 34 has INTERNAL_VREF set to 0.675V

| Signal | FPGA Pins |
|--------|-----------|
| A[13:0] | R2 M6 N4 T1 N6 R7 V6 U7 R8 V7 R6 U6 T6 T8 |
| BA[2:0] | R1 P4 P2 |
| DQ[7:0] | K5 L3 K3 L6 M3 M1 L4 M2 |
| DQ[15:8] | V4 T5 U4 V5 V1 T3 U3 R3 |
| DQS_P[1:0] | N2 U2 |
| DQS_N[1:0] | N1 V2 |
| DM[1:0] | L1 U1 |
| CLK_P / CLK_N | U9 / V9 |
| CKE | N5 |
| ODT | R5 |
| CS_N | U8 |
| RAS_N | P3 |
| CAS_N | M4 |
| WE_N | P5 |
| RESET_N | K6 |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

## MII Ethernet

The Arty uses a TI DP83848J Ethernet PHY with a standard MII (Media Independent Interface), supporting 10/100 Mbps.

| Signal | FPGA Pin | Direction |
|--------|----------|-----------|
| ref_clk | G18 | Output (25 MHz) |
| tx_clk | H16 | Input |
| rx_clk | F15 | Input |
| rst_n | C16 | Output |
| mdio | K13 | Bidirectional |
| mdc | F16 | Output |
| rx_dv | G16 | Input |
| rx_er | C17 | Input |
| rx_data[3:0] | D18 E17 E18 G17 | Input |
| tx_en | H15 | Output |
| tx_data[3:0] | H14 J14 J13 H17 | Output |
| col | D17 | Input |
| crs | G14 | Input |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py), [Digilent Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)

## PMOD Connectors

The Arty A7 has four 12-pin PMOD connectors (JA through JD). Each connector provides 8 signal pins plus power (VCC) and ground (GND). All PMOD I/O use LVCMOS33 (3.3V) standard.

### PMOD Pin Numbering

Standard 12-pin PMOD connector layout:

```
           ┌─────────────────────────────────────┐
Top row:   │ Pin1  Pin2  Pin3  Pin4  GND   VCC   │
Bottom row:│ Pin5  Pin6  Pin7  Pin8  GND   VCC   │
           └─────────────────────────────────────┘
```

Pins 1-4 are the top row, pins 5-8 are the bottom row (numbered 0-7 in LiteX, where 0-3 = top, 4-7 = bottom).

### PMOD FPGA Pin Assignments

| LiteX Index | PMODA (JA) | PMODB (JB) | PMODC (JC) | PMODD (JD) |
|-------------|-----------|-----------|-----------|-----------|
| 0 (top pin 1) | G13 | E15 | U12 | D4 |
| 1 (top pin 2) | B11 | E16 | V12 | D3 |
| 2 (top pin 3) | A11 | D15 | V10 | F4 |
| 3 (top pin 4) | D12 | C15 | V11 | F3 |
| 4 (bottom pin 7) | D13 | J17 | U14 | E2 |
| 5 (bottom pin 8) | B18 | J18 | V14 | D2 |
| 6 (bottom pin 9) | A18 | K15 | T13 | H2 |
| 7 (bottom pin 10) | K16 | J15 | U13 | G2 |

Source: [digilent_arty.py `_connectors`](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

### PMOD Usage in Test Infrastructure

In the fpgas.online setup, the Arty A7's PMOD connectors can be connected to a Raspberry Pi via a [Digilent PMOD HAT adapter](pmod-hat.md). This enables PMOD loopback testing where the RPi drives signals through the PMOD HAT to the Arty's PMOD connectors and verifies correct signal propagation.

## SPI Flash

| Signal | FPGA Pin |
|--------|----------|
| CS_N | L13 |
| CLK | L16 |
| MOSI (DQ0) | K17 |
| MISO (DQ1) | K18 |
| WP (DQ2) | L14 |
| HOLD (DQ3) | M14 |

Quad SPI (4x) mode is supported. The bitstream configuration enables SPI_BUSWIDTH=4.

## LiteX Integration

| Property | Value |
|----------|-------|
| Platform module | `litex_boards.platforms.digilent_arty` |
| Target module | `litex_boards.targets.digilent_arty` |
| Default clock | `clk100` (100 MHz, pin E3) |
| Programmer | OpenOCD with `openocd_xc7_ft2232.cfg` |
| BSCAN SPI bitstream | `bscan_spi_xc7a35t.bit` or `bscan_spi_xc7a100t.bit` |
| Toolchain | Vivado (proprietary) or openXC7 (open source) |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

## Programming

### Via openFPGALoader (USB-JTAG)

```bash
# Volatile load (lost on power cycle)
openFPGALoader -b arty design.bit

# Write to SPI flash (persistent)
openFPGALoader -b arty --write-flash design.bit
```

### Via OpenOCD (USB-JTAG)

```bash
openocd -f openocd_xc7_ft2232.cfg -c "init; pld load 0 design.bit; exit"
```

## References

- LiteX platform file: <https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py>
- Digilent Arty A7 Reference Manual: <https://digilent.com/reference/programmable-logic/arty-a7/reference-manual>
- Digilent Arty A7 Product Page: <https://digilent.com/shop/arty-a7-artix-7-fpga-development-board/>
