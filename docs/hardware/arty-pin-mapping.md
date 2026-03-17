# Arty A7 Pin Mapping

Pin mapping for the Digilent Arty A7-35T as connected in the fpgas.online test infrastructure. Three hosts: pi3 (10.21.0.103), pi5 (10.21.0.105), pi9 (10.21.0.109).

## FPGA Device

| Parameter | Value |
|-----------|-------|
| FPGA | Xilinx Artix-7 XC7A35T-CPG236-1 |
| Package | CPG236 |
| System clock | 100 MHz (pin E3, LVCMOS33) |
| Toolchain | openXC7 (open source) or Vivado |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

## Programming Interface

The Arty has an on-board FTDI FT2232H providing both JTAG and UART over a single USB connection.

| Parameter | Value |
|-----------|-------|
| Interface | USB JTAG (FTDI FT2232H, channel A) |
| Tool | `openFPGALoader -b arty <bitstream>` |
| USB device | Appears as two `/dev/ttyUSB*` devices (JTAG + UART) |
| Bitstream type | `.bit` (volatile SRAM load) |

## UART Interface

The FPGA's UART connects to the host RPi via the FTDI FT2232H (channel B), appearing as a USB serial device. This is NOT a GPIO connection — it goes through USB.

| Signal | FPGA Pin | Direction | IO Standard |
|--------|----------|-----------|-------------|
| TX (FPGA → RPi) | D10 | Output | LVCMOS33 |
| RX (RPi → FPGA) | A9 | Input | LVCMOS33 |

| Parameter | Value |
|-----------|-------|
| RPi device | `/dev/ttyUSB1` (channel B of FTDI) |
| Baud rate | 115200 |
| Flow control | None |
| Test args | `--port /dev/ttyUSB1 --board arty` |

Note: `/dev/ttyUSB0` is the JTAG channel, `/dev/ttyUSB1` is the UART channel.

## PMOD Connectors (FPGA Side)

The Arty has four PMOD connectors. The GPIO loopback test uses PMODA (input) and PMODB (output).

### PMODA

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
|----------|-------------|----------|-------------|
| 1 | pmoda:0 | G13 | LVCMOS33 |
| 2 | pmoda:1 | B11 | LVCMOS33 |
| 3 | pmoda:2 | A11 | LVCMOS33 |
| 4 | pmoda:3 | D12 | LVCMOS33 |
| 7 | pmoda:4 | D13 | LVCMOS33 |
| 8 | pmoda:5 | B18 | LVCMOS33 |
| 9 | pmoda:6 | A18 | LVCMOS33 |
| 10 | pmoda:7 | K16 | LVCMOS33 |

### PMODB

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
|----------|-------------|----------|-------------|
| 1 | pmodb:0 | E15 | LVCMOS33 |
| 2 | pmodb:1 | E16 | LVCMOS33 |
| 3 | pmodb:2 | D15 | LVCMOS33 |
| 4 | pmodb:3 | C15 | LVCMOS33 |
| 7 | pmodb:4 | J17 | LVCMOS33 |
| 8 | pmodb:5 | J18 | LVCMOS33 |
| 9 | pmodb:6 | K15 | LVCMOS33 |
| 10 | pmodb:7 | J15 | LVCMOS33 |

### PMODC

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
|----------|-------------|----------|-------------|
| 1 | pmodc:0 | U12 | LVCMOS33 |
| 2 | pmodc:1 | V12 | LVCMOS33 |
| 3 | pmodc:2 | V10 | LVCMOS33 |
| 4 | pmodc:3 | V11 | LVCMOS33 |
| 7 | pmodc:4 | U14 | LVCMOS33 |
| 8 | pmodc:5 | V14 | LVCMOS33 |
| 9 | pmodc:6 | T13 | LVCMOS33 |
| 10 | pmodc:7 | U13 | LVCMOS33 |

### PMODD

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
|----------|-------------|----------|-------------|
| 1 | pmodd:0 | D4 | LVCMOS33 |
| 2 | pmodd:1 | D3 | LVCMOS33 |
| 3 | pmodd:2 | F4 | LVCMOS33 |
| 4 | pmodd:3 | F3 | LVCMOS33 |
| 7 | pmodd:4 | E2 | LVCMOS33 |
| 8 | pmodd:5 | D2 | LVCMOS33 |
| 9 | pmodd:6 | H2 | LVCMOS33 |
| 10 | pmodd:7 | G2 | LVCMOS33 |

Source: `_connectors` in digilent_arty.py

## PMOD HAT Ports (RPi Side)

The Digilent PMOD HAT has three 12-pin PMOD ports. Each port connects to one Arty PMOD connector via a single cable.

### PMOD HAT Port JA

| PMOD Pin | RPi GPIO | RPi Header Pin | BCM Alt Function |
|----------|----------|----------------|-----------------|
| 1 (top) | GPIO6 | 31 | — |
| 2 (top) | GPIO13 | 33 | — |
| 3 (top) | GPIO19 | 35 | PCM_FS |
| 4 (top) | GPIO26 | 37 | — |
| 7 (bottom) | GPIO12 | 32 | PWM0 |
| 8 (bottom) | GPIO16 | 36 | — |
| 9 (bottom) | GPIO20 | 38 | PCM_DIN |
| 10 (bottom) | GPIO21 | 40 | PCM_DOUT |

### PMOD HAT Port JB

| PMOD Pin | RPi GPIO | RPi Header Pin | BCM Alt Function |
|----------|----------|----------------|-----------------|
| 1 (top) | GPIO5 | 29 | — |
| 2 (top) | GPIO11 | 23 | SPI0_SCLK |
| 3 (top) | GPIO9 | 21 | SPI0_MISO |
| 4 (top) | GPIO10 | 19 | SPI0_MOSI |
| 7 (bottom) | GPIO7 | 26 | SPI0_CE1 |
| 8 (bottom) | GPIO8 | 24 | SPI0_CE0 |
| 9 (bottom) | GPIO0 | 27 | I2C0_SDA |
| 10 (bottom) | GPIO1 | 28 | I2C0_SCL |

Note: GPIO7-11 overlap with SPI0. The SPI kernel modules must be unloaded (`rmmod spidev spi_bcm2835`) before GPIO access. GPIO0/1 are I2C0 with hardware pull-ups.

### PMOD HAT Port JC

| PMOD Pin | RPi GPIO | RPi Header Pin | BCM Alt Function |
|----------|----------|----------------|-----------------|
| 1 (top) | GPIO17 | 11 | — |
| 2 (top) | GPIO18 | 12 | PWM0 |
| 3 (top) | GPIO4 | 7 | GPCLK0 |
| 4 (top) | GPIO14 | 8 | TXD (UART) |
| 7 (bottom) | GPIO2 | 3 | I2C1_SDA |
| 8 (bottom) | GPIO3 | 5 | I2C1_SCL |
| 9 (bottom) | GPIO15 | 10 | RXD (UART) |
| 10 (bottom) | GPIO25 | 22 | — |

Note: GPIO14/15 overlap with UART. GPIO2/3 are I2C1 with hardware pull-ups. GPIO4 is used as JTAG TCK in the NeTV2 configuration.

### Unused RPi GPIOs

These GPIOs are NOT assigned to any PMOD HAT port:

| RPi GPIO | RPi Header Pin | Notes |
|----------|----------------|-------|
| GPIO22 | 15 | Free |
| GPIO23 | 16 | Free |
| GPIO24 | 18 | Free (SRST in NeTV2 JTAG config) |
| GPIO27 | 13 | Free (TDI in NeTV2 JTAG config) |

## PMOD Cable Routing: HAT ↔ Arty

Determined automatically using the `pmod-pin-id` design, which transmits each FPGA pin's ball name as 1200-baud UART. The RPi reads each GPIO and decodes the pin name. Two independent scans were run: v1 (transmitting PMOD connector names like "JA01") and v2 (transmitting FPGA pin names like "G13"). All v2 results match the v1-derived FPGA pin names, cross-validating the mapping.

Cables do NOT route HAT ports to Arty PMODs 1:1 — the mapping is non-trivial. Arty JD is not connected (HAT has only 3 ports for 4 Arty PMODs).

### Pi9 (21 of 24 pins confirmed, 2026-03-17)

| RPi GPIO | HAT Port:Pin | FPGA Pin | Arty PMOD Pin | Verification |
|----------|-------------|----------|---------------|--------------|
| GPIO6    | JA:01       | U13      | JC10          | both scans   |
| GPIO13   | JA:02       | J18      | JB08          | both scans   |
| GPIO19   | JA:03       | D13      | JA07          | both scans   |
| GPIO26   | JA:04       | J17      | JB07          | both scans   |
| GPIO12   | JA:07       | V14      | JC08          | both scans   |
| GPIO16   | JA:08       | V12      | JC02          | both scans   |
| GPIO20   | JA:09       | A18      | JA09          | both scans   |
| GPIO21   | JA:10       | B18      | JA08          | both scans   |
| GPIO5    | JB:01       | T13      | JC09          | both scans   |
| GPIO11   | JB:02       | C15      | JB04          | v1 + derived |
| GPIO9    | JB:03       | D15      | JB03          | both scans   |
| GPIO10   | JB:04       | E16      | JB02          | both scans   |
| GPIO7    | JB:07       | E15      | JB01          | v1 + derived |
| GPIO8    | JB:08       | G13      | JA01          | both scans   |
| GPIO0    | JB:09       | B11/A11/D12 | JA02/03/04 | unreadable   |
| GPIO1    | JB:10       | B11/A11/D12 | JA02/03/04 | unreadable   |
| GPIO17   | JC:01       | V11      | JC04          | both scans   |
| GPIO18   | JC:02       | K16      | JA10          | both scans   |
| GPIO4    | JC:03       | U14      | JC07          | both scans   |
| GPIO14   | JC:04       | U12      | JC01          | v1 + derived |
| GPIO2    | JC:07       | J15      | JB10          | both scans   |
| GPIO3    | JC:08       | K15      | JB09          | v1 + derived |
| GPIO15   | JC:09       | V10      | JC03          | both scans   |
| GPIO25   | JC:10       | —        | —             | no signal    |

GPIO0/1: I2C0 hardware pull-ups (~1.8kΩ) hold lines high, preventing FPGA signal readout. The three missing FPGA pins (B11=JA02, A11=JA03, D12=JA04) map to GPIO0, GPIO1, and GPIO25 in unknown order.

GPIO25: No signal detected — either not connected or weak drive.

### Pi3 (12 of 24 pins confirmed, 2026-03-17)

| RPi GPIO | HAT Port:Pin | FPGA Pin | Arty PMOD Pin | Verification |
|----------|-------------|----------|---------------|--------------|
| GPIO13   | JA:02       | J18      | JB08          | both scans   |
| GPIO19   | JA:03       | D13      | JA07          | both scans   |
| GPIO26   | JA:04       | J17      | JB07          | both scans   |
| GPIO20   | JA:09       | A18      | JA09          | both scans   |
| GPIO21   | JA:10       | B18      | JA08          | both scans   |
| GPIO11   | JB:02       | C15      | JB04          | both scans   |
| GPIO9    | JB:03       | D15      | JB03          | v2 corrected |
| GPIO10   | JB:04       | E16      | JB02          | both scans   |
| GPIO7    | JB:07       | E15      | JB01          | v1 + derived |
| GPIO8    | JB:08       | G13      | JA01          | both scans   |
| GPIO2    | JC:07       | J15      | JB10          | both scans   |
| GPIO3    | JC:08       | K15      | JB09          | both scans   |

Pi3 has fewer reachable pins — likely fewer PMOD cables connected. The 12 confirmed pins all match pi9's mapping (same cable routing for the connected ports). GPIO9 was misread as JC03 in v1 but correctly reads D15 (=JB03) in v2.

### Pi5 (offline, 2026-03-17)

Pi5 (10.21.0.105) was unreachable during scanning — host appears powered off.

## GPIO Loopback Test

The loopback gateware computes `pmodb = ~pmoda` (per-bit inversion). The RPi drives PMODA pins and reads the inverted result on PMODB pins. The loopback pairs can be derived from the per-host PMOD cable routing tables above.

### Pre-test Requirements

`rmmod spidev spi_bcm2835` — The SPI kernel modules claim GPIO7-11 (PMOD HAT port JB pins). Unloading them frees these GPIOs for the loopback test.

## MII Ethernet

The Arty has an on-board Ethernet PHY (TI DP83848) connected to the FPGA via MII.

| Signal | FPGA Pin | IO Standard |
|--------|----------|-------------|
| ref_clk | G18 | LVCMOS33 |
| tx_clk | H16 | LVCMOS33 |
| rx_clk | F15 | LVCMOS33 |
| rst_n | C16 | LVCMOS33 |
| mdio | K13 | LVCMOS33 |
| mdc | F16 | LVCMOS33 |
| rx_dv | G16 | LVCMOS33 |
| rx_er | C17 | LVCMOS33 |
| rx_data[3:0] | D18 E17 E18 G17 | LVCMOS33 |
| tx_en | H15 | LVCMOS33 |
| tx_data[3:0] | H14 J14 J13 H17 | LVCMOS33 |
| col | D17 | LVCMOS33 |
| crs | G14 | LVCMOS33 |

The Ethernet test uses a USB Ethernet adapter on the RPi connected to the Arty's RJ45 jack (independent of the PMOD HAT and RPi's own Ethernet).

## SPI Flash

On-board SPI flash for persistent bitstream storage.

| Signal | FPGA Pin | IO Standard |
|--------|----------|-------------|
| cs_n | L13 | LVCMOS33 |
| clk | L16 | LVCMOS33 |
| mosi (DQ0) | K17 | LVCMOS33 |
| miso (DQ1) | K18 | LVCMOS33 |
| wp (DQ2) | L14 | LVCMOS33 |
| hold (DQ3) | M14 | LVCMOS33 |

Quad SPI mode supported via `spiflash4x` resource.

There is also a secondary SPI resource (directly accessible header):

| Signal | FPGA Pin | IO Standard |
|--------|----------|-------------|
| clk | F1 | LVCMOS33 |
| cs_n | C1 | LVCMOS33 |
| mosi | H1 | LVCMOS33 |
| miso | G1 | LVCMOS33 |

## DDR3 SDRAM

On-board DDR3L SDRAM (256 MB, 16-bit wide).

| Signal | FPGA Pins | IO Standard |
|--------|-----------|-------------|
| A[13:0] | R2 M6 N4 T1 N6 R7 V6 U7 R8 V7 R6 U6 T6 T8 | SSTL135 |
| BA[2:0] | R1 P4 P2 | SSTL135 |
| DQ[7:0] | K5 L3 K3 L6 M3 M1 L4 M2 | SSTL135 |
| DQ[15:8] | V4 T5 U4 V5 V1 T3 U3 R3 | SSTL135 |
| DQS_P[1:0] | N2 U2 | DIFF_SSTL135 |
| DQS_N[1:0] | N1 V2 | DIFF_SSTL135 |
| DM[1:0] | L1 U1 | SSTL135 |
| CLK_P / CLK_N | U9 / V9 | DIFF_SSTL135 |
| CKE | N5 | SSTL135 |
| ODT | R5 | SSTL135 |
| CS_N | U8 | SSTL135 |
| RAS_N | P3 | SSTL135 |
| CAS_N | M4 | SSTL135 |
| WE_N | P5 | SSTL135 |
| RESET_N | K6 | SSTL135 |

## References

- LiteX platform file: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)
- Digilent Arty Reference Manual: [reference.digilentinc.com](https://reference.digilentinc.com/reference/programmable-logic/arty-a7/reference-manual)
- PMOD HAT Documentation: [pmod-hat.md](pmod-hat.md)
