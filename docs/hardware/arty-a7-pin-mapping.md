# Arty A7 Pin Mapping

Pin mapping for the Digilent Arty A7-35T as connected in the fpgas.online test infrastructure. Three hosts: pi3 (10.21.0.103), pi5 (10.21.0.105), pi9 (10.21.0.109).

## FPGA Device

| Parameter    | Value                           |
| ------------ | ------------------------------- |
| FPGA         | Xilinx Artix-7 XC7A35T-CPG236-1 |
| Package      | CPG236                          |
| System clock | 100 MHz (pin E3, LVCMOS33)      |
| Toolchain    | openXC7 (open source) or Vivado |

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

## Programming Interface

The Arty has an on-board FTDI FT2232H providing both JTAG and UART over a single USB connection.

| Parameter      | Value                                               |
| -------------- | --------------------------------------------------- |
| Interface      | USB JTAG (FTDI FT2232H, channel A)                  |
| Tool           | `openFPGALoader -b arty <bitstream>`                |
| USB device     | Appears as two `/dev/ttyUSB*` devices (JTAG + UART) |
| Bitstream type | `.bit` (volatile SRAM load)                         |

## UART Interface

The FPGA's UART connects to the host RPi via the FTDI FT2232H (channel B), appearing as a USB serial device. This is NOT a GPIO connection — it goes through USB.

| Signal          | FPGA Pin | Direction | IO Standard |
| --------------- | -------- | --------- | ----------- |
| TX (FPGA → RPi) | D10      | Output    | LVCMOS33    |
| RX (RPi → FPGA) | A9       | Input     | LVCMOS33    |

| Parameter    | Value                              |
| ------------ | ---------------------------------- |
| RPi device   | `/dev/ttyUSB1` (channel B of FTDI) |
| Baud rate    | 115200                             |
| Flow control | None                               |
| Test args    | `--port /dev/ttyUSB1 --board arty` |

Note: `/dev/ttyUSB0` is the JTAG channel, `/dev/ttyUSB1` is the UART channel.

## PMOD Connectors (FPGA Side)

The Arty has four PMOD connectors. The GPIO loopback test uses PMODA (input) and PMODB (output).

### PMODA

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
| -------- | ------------ | -------- | ----------- |
| 1        | pmoda:0      | G13      | LVCMOS33    |
| 2        | pmoda:1      | B11      | LVCMOS33    |
| 3        | pmoda:2      | A11      | LVCMOS33    |
| 4        | pmoda:3      | D12      | LVCMOS33    |
| 7        | pmoda:4      | D13      | LVCMOS33    |
| 8        | pmoda:5      | B18      | LVCMOS33    |
| 9        | pmoda:6      | A18      | LVCMOS33    |
| 10       | pmoda:7      | K16      | LVCMOS33    |

### PMODB

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
| -------- | ------------ | -------- | ----------- |
| 1        | pmodb:0      | E15      | LVCMOS33    |
| 2        | pmodb:1      | E16      | LVCMOS33    |
| 3        | pmodb:2      | D15      | LVCMOS33    |
| 4        | pmodb:3      | C15      | LVCMOS33    |
| 7        | pmodb:4      | J17      | LVCMOS33    |
| 8        | pmodb:5      | J18      | LVCMOS33    |
| 9        | pmodb:6      | K15      | LVCMOS33    |
| 10       | pmodb:7      | J15      | LVCMOS33    |

### PMODC

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
| -------- | ------------ | -------- | ----------- |
| 1        | pmodc:0      | U12      | LVCMOS33    |
| 2        | pmodc:1      | V12      | LVCMOS33    |
| 3        | pmodc:2      | V10      | LVCMOS33    |
| 4        | pmodc:3      | V11      | LVCMOS33    |
| 7        | pmodc:4      | U14      | LVCMOS33    |
| 8        | pmodc:5      | V14      | LVCMOS33    |
| 9        | pmodc:6      | T13      | LVCMOS33    |
| 10       | pmodc:7      | U13      | LVCMOS33    |

### PMODD

| PMOD Pin | Signal Index | FPGA Pin | IO Standard |
| -------- | ------------ | -------- | ----------- |
| 1        | pmodd:0      | D4       | LVCMOS33    |
| 2        | pmodd:1      | D3       | LVCMOS33    |
| 3        | pmodd:2      | F4       | LVCMOS33    |
| 4        | pmodd:3      | F3       | LVCMOS33    |
| 7        | pmodd:4      | E2       | LVCMOS33    |
| 8        | pmodd:5      | D2       | LVCMOS33    |
| 9        | pmodd:6      | H2       | LVCMOS33    |
| 10       | pmodd:7      | G2       | LVCMOS33    |

Source: `_connectors` in digilent_arty.py

## PMOD HAT Ports (RPi Side)

The Digilent PMOD HAT has three 12-pin PMOD ports. Each port connects to one Arty PMOD connector via a single cable.

See [rpi-hat-pmod.md](rpi-hat-pmod.md) for the full PMOD HAT pin mapping. Summary:

### PMOD HAT Port JA (SPI [Type 2](pmod.md#type-2--spi-6-pin), CE0)

| PMOD Pin | RPi GPIO | BCM Alt Function |
| -------- | -------- | ---------------- |
| 1        | GPIO8    | SPI0_CE0         |
| 2        | GPIO10   | SPI0_MOSI (\*)   |
| 3        | GPIO9    | SPI0_MISO (\*)   |
| 4        | GPIO11   | SPI0_SCLK (\*)   |
| 7        | GPIO19   | PCM_FS           |
| 8        | GPIO21   | PCM_DOUT         |
| 9        | GPIO20   | PCM_DIN          |
| 10       | GPIO18   | PCM_CLK / PWM0   |

### PMOD HAT Port JB (SPI [Type 2](pmod.md#type-2--spi-6-pin), CE1)

| PMOD Pin | RPi GPIO | BCM Alt Function |
| -------- | -------- | ---------------- |
| 1        | GPIO7    | SPI0_CE1         |
| 2        | GPIO10   | SPI0_MOSI (\*)   |
| 3        | GPIO9    | SPI0_MISO (\*)   |
| 4        | GPIO11   | SPI0_SCLK (\*)   |
| 7        | GPIO26   |                  |
| 8        | GPIO13   | PWM1             |
| 9        | GPIO3    | I2C1_SCL         |
| 10       | GPIO2    | I2C1_SDA         |

(\*) JA pins 2-4 and JB pins 2-4 are the **same GPIOs** (SPI bus). `rmmod spidev spi_bcm2835` required before GPIO access.

### PMOD HAT Port JC (UART [Type 4](pmod.md#type-4--uart-6-pin))

| PMOD Pin | RPi GPIO | BCM Alt Function |
| -------- | -------- | ---------------- |
| 1        | GPIO16   | CTS0             |
| 2        | GPIO14   | TXD0             |
| 3        | GPIO15   | RXD0             |
| 4        | GPIO17   | RTS0             |
| 7        | GPIO4    | GPCLK0           |
| 8        | GPIO12   | PWM0             |
| 9        | GPIO5    |                  |
| 10       | GPIO6    |                  |

### Unused RPi GPIOs

These GPIOs are NOT assigned to any PMOD HAT port:

| RPi GPIO | RPi Header Pin | Notes                 |
| -------- | -------------- | --------------------- |
| GPIO0    | 27             | I2C0_SDA (HAT EEPROM) |
| GPIO1    | 28             | I2C0_SCL (HAT EEPROM) |
| GPIO22   | 15             | Free                  |
| GPIO23   | 16             | Free                  |
| GPIO24   | 18             | Free                  |
| GPIO25   | 22             | Free                  |
| GPIO27   | 13             | Free                  |

## PMOD Cable Routing: HAT ↔ Arty

Ribbon cables connect straight through: **HAT JA → Arty JA**, **HAT JB → Arty JB**, **HAT JC → Arty JC**. Arty JD is not connected (HAT has only 3 ports).

Verified using the `pmod-pin-id` design which transmits each FPGA pin's ball name as 1200-baud UART on every PMOD pin. Two independent scans (PMOD names and FPGA pin names) cross-validated.

### Pi9 (21 of 24 unique GPIOs scanned, 2026-03-17)

#### HAT JA → Arty JA

| HAT Pin | RPi GPIO | Scanned FPGA Pin | Expected (Arty JA) | Match |
| ------- | -------- | ---------------- | ------------------ | ----- |
| 1       | GPIO8    | G13              | G13                | yes   |
| 2       | GPIO10   | E16              | B11 (but shared\*) | (\*)  |
| 3       | GPIO9    | D15              | A11 (but shared\*) | (\*)  |
| 4       | GPIO11   | C15              | D12 (but shared\*) | (\*)  |
| 7       | GPIO19   | D13              | D13                | yes   |
| 8       | GPIO21   | B18              | B18                | yes   |
| 9       | GPIO20   | A18              | A18                | yes   |
| 10      | GPIO18   | K16              | K16                | yes   |

(\*) Pins 2-4 share GPIOs with JB pins 2-4. The scan reads Arty JB's pins (E16, D15, C15) because both cables drive the same GPIO lines. Arty JA pins 2-4 (B11, A11, D12) cannot be independently verified.

#### HAT JB → Arty JB (all 8 pins verified)

| HAT Pin | RPi GPIO | Scanned FPGA Pin | Expected (Arty JB) | Match |
| ------- | -------- | ---------------- | ------------------ | ----- |
| 1       | GPIO7    | E15              | E15                | yes   |
| 2       | GPIO10   | E16              | E16                | yes   |
| 3       | GPIO9    | D15              | D15                | yes   |
| 4       | GPIO11   | C15              | C15                | yes   |
| 7       | GPIO26   | J17              | J17                | yes   |
| 8       | GPIO13   | J18              | J18                | yes   |
| 9       | GPIO3    | K15              | K15                | yes   |
| 10      | GPIO2    | J15              | J15                | yes   |

#### HAT JC → Arty JC (pins 1↔2 swapped in cable)

| HAT Pin | RPi GPIO | Scanned FPGA Pin | Expected (Arty JC) | Match |
| ------- | -------- | ---------------- | ------------------ | ----- |
| 1       | GPIO16   | V12              | U12                | SWAP  |
| 2       | GPIO14   | U12              | V12                | SWAP  |
| 3       | GPIO15   | V10              | V10                | yes   |
| 4       | GPIO17   | V11              | V11                | yes   |
| 7       | GPIO4    | U14              | U14                | yes   |
| 8       | GPIO12   | V14              | V14                | yes   |
| 9       | GPIO5    | T13              | T13                | yes   |
| 10      | GPIO6    | U13              | U13                | yes   |

HAT JC pins 1 and 2 are swapped relative to Arty JC pins 1 and 2. This is a physical cable crossover — GPIO16 connects to Arty JC pin 2 (V12) and GPIO14 connects to Arty JC pin 1 (U12). All other pins match 1:1.

### Pi3 (2026-03-17)

Pi3 detected fewer pins (12 of 21 unique GPIOs). All detected pins match pi9's results exactly, confirming the same cable routing. HAT JC top-row and some JA/JB pins showed no signal — likely loose cables or missing connections on this host.

### Pi5 (offline, 2026-03-17)

Pi5 (10.21.0.105) was unreachable during scanning — host appears powered off.

## GPIO Loopback Test

The loopback gateware computes `pmodb = ~pmoda` (per-bit inversion). The RPi drives PMODA pins and reads the inverted result on PMODB pins. The loopback pairs can be derived from the per-host PMOD cable routing tables above.

### Pre-test Requirements

`rmmod spidev spi_bcm2835` — The SPI kernel modules claim GPIO7-11 (PMOD HAT port JB pins). Unloading them frees these GPIOs for the loopback test.

## MII Ethernet

The Arty has an on-board Ethernet PHY (TI DP83848) connected to the FPGA via MII.

| Signal       | FPGA Pin        | IO Standard |
| ------------ | --------------- | ----------- |
| ref_clk      | G18             | LVCMOS33    |
| tx_clk       | H16             | LVCMOS33    |
| rx_clk       | F15             | LVCMOS33    |
| rst_n        | C16             | LVCMOS33    |
| mdio         | K13             | LVCMOS33    |
| mdc          | F16             | LVCMOS33    |
| rx_dv        | G16             | LVCMOS33    |
| rx_er        | C17             | LVCMOS33    |
| rx_data[3:0] | D18 E17 E18 G17 | LVCMOS33    |
| tx_en        | H15             | LVCMOS33    |
| tx_data[3:0] | H14 J14 J13 H17 | LVCMOS33    |
| col          | D17             | LVCMOS33    |
| crs          | G14             | LVCMOS33    |

The Ethernet test uses a USB Ethernet adapter on the RPi connected to the Arty's RJ45 jack (independent of the PMOD HAT and RPi's own Ethernet).

## SPI Flash

On-board SPI flash for persistent bitstream storage.

| Signal     | FPGA Pin | IO Standard |
| ---------- | -------- | ----------- |
| cs_n       | L13      | LVCMOS33    |
| clk        | L16      | LVCMOS33    |
| mosi (DQ0) | K17      | LVCMOS33    |
| miso (DQ1) | K18      | LVCMOS33    |
| wp (DQ2)   | L14      | LVCMOS33    |
| hold (DQ3) | M14      | LVCMOS33    |

Quad SPI mode supported via `spiflash4x` resource.

There is also a secondary SPI resource (directly accessible header):

| Signal | FPGA Pin | IO Standard |
| ------ | -------- | ----------- |
| clk    | F1       | LVCMOS33    |
| cs_n   | C1       | LVCMOS33    |
| mosi   | H1       | LVCMOS33    |
| miso   | G1       | LVCMOS33    |

## DDR3 SDRAM

On-board DDR3L SDRAM (256 MB, 16-bit wide).

| Signal        | FPGA Pins                                 | IO Standard  |
| ------------- | ----------------------------------------- | ------------ |
| A[13:0]       | R2 M6 N4 T1 N6 R7 V6 U7 R8 V7 R6 U6 T6 T8 | SSTL135      |
| BA[2:0]       | R1 P4 P2                                  | SSTL135      |
| DQ[7:0]       | K5 L3 K3 L6 M3 M1 L4 M2                   | SSTL135      |
| DQ[15:8]      | V4 T5 U4 V5 V1 T3 U3 R3                   | SSTL135      |
| DQS_P[1:0]    | N2 U2                                     | DIFF_SSTL135 |
| DQS_N[1:0]    | N1 V2                                     | DIFF_SSTL135 |
| DM[1:0]       | L1 U1                                     | SSTL135      |
| CLK_P / CLK_N | U9 / V9                                   | DIFF_SSTL135 |
| CKE           | N5                                        | SSTL135      |
| ODT           | R5                                        | SSTL135      |
| CS_N          | U8                                        | SSTL135      |
| RAS_N         | P3                                        | SSTL135      |
| CAS_N         | M4                                        | SSTL135      |
| WE_N          | P5                                        | SSTL135      |
| RESET_N       | K6                                        | SSTL135      |

## References

- LiteX platform file: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)
- Digilent Arty Reference Manual: [reference.digilentinc.com](https://reference.digilentinc.com/reference/programmable-logic/arty-a7/reference-manual)
- PMOD Interface Specification: [pmod.md](pmod.md)
- PMOD HAT Adapter (RPi): [rpi-hat-pmod.md](rpi-hat-pmod.md)
