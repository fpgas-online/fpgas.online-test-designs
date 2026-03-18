# Kosagi NeTV2

The NeTV2 is a Xilinx Artix-7 based video overlay/processing board designed by bunnie (Andrew Huang) and produced by Alphamax/Kosagi. In the fpgas.online infrastructure, it connects to Raspberry Pi hosts via GPIO (JTAG + UART) and optionally PCIe.

## Key Specifications

| Parameter            | Value                                             |
| -------------------- | ------------------------------------------------- |
| FPGA (default)       | Xilinx Artix-7 XC7A35T-FGG484-2                   |
| FPGA (large variant) | Xilinx Artix-7 XC7A100T-FGG484-2                  |
| Package              | FGG484 (484-ball BGA)                             |
| System clock         | 50 MHz (pin J19, LVCMOS33)                        |
| DDR3 SDRAM           | 512 MB (32-bit wide, 4 byte lanes)                |
| Ethernet             | RMII PHY, 100Base-T (independent of host network) |
| HDMI                 | 2x HDMI In + 2x HDMI Out (TMDS_33)                |
| PCIe                 | x1 / x2 / x4                                      |
| SD Card              | Full-size SD slot (SPI and 4-bit modes)           |
| SPI Flash            | Quad SPI                                          |
| User LEDs            | 6 (M21, N20, L21, AA21, R19, M16)                 |

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## FPGA Device Variants

| Variant  | Device String       |
| -------- | ------------------- |
| `a7-35`  | `xc7a35t-fgg484-2`  |
| `a7-100` | `xc7a100t-fgg484-2` |

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## Host Connections

The NeTV2 is designed to sit on top of a Raspberry Pi, connecting through the 40-pin GPIO header and optionally through a PCIe link.

### RPi5 Setup (rpi5-netv2.iot.welland.mithis.com)

- **Board type**: Bare developer NeTV2 (unpackaged)
- **GPIO connection**: JTAG (4 signals + SRST) and UART (TX/RX)
- **PCIe connection**: Gen2 x1 via RPi5 PCIe connector
- **lspci**: Xilinx device with vendor `10ee`, device `7011`

### RPi3 Setup (rpi3-netv2.iot.welland.mithis.com)

- **Board type**: Stock packaged NeTV2 (as shipped by bunnie via Crowd Supply)
- **GPIO connection**: JTAG (4 signals + SRST) and UART (TX/RX)
- **PCIe connection**: Not available (RPi3 has no PCIe interface)

## JTAG via RPi GPIO

The NeTV2 JTAG interface is directly wired to specific Raspberry Pi GPIO pins. The GPIO-to-JTAG pin mapping originates from the [alphamax-rpi.cfg](https://github.com/alphamaxmedia/netv2mvp-scripts/blob/master/alphamax-rpi.cfg) OpenOCD configuration in the NeTV2 MVP scripts.

| JTAG Signal | RPi GPIO | RPi Header Pin | Direction (from RPi) |
| ----------- | -------- | -------------- | -------------------- |
| TCK         | GPIO4    | Pin 7          | Output               |
| TMS         | GPIO17   | Pin 11         | Output               |
| TDI         | GPIO27   | Pin 13         | Output               |
| TDO         | GPIO22   | Pin 15         | Input                |
| SRST        | GPIO24   | Pin 18         | Output               |

### Programming with openFPGALoader

openFPGALoader is the primary tool for programming the NeTV2. It supports multiple JTAG transports over the same GPIO wiring.

#### RPi 3B+ (GPIO bitbang — current deployed hosts)

On RPi 3B+ hosts (pi10, pi12, pi14, pi16, pi18), openFPGALoader uses `linuxgpiod_bitbang` to drive the JTAG signals through the Linux GPIO subsystem:

```bash
# Volatile load
openFPGALoader --cable linuxgpiod_bitbang --pins 27:22:4:17 design.bit

# Persistent SPI flash
openFPGALoader --cable linuxgpiod_bitbang --pins 27:22:4:17 --write-flash design.bit
```

Pin order: `TDI:TDO:TCK:TMS`.

This works but is slow (~5 MHz effective JTAG clock) due to GPIO bitbang overhead.

#### RPi 5 (GPIO bitbang — works today, slow)

On RPi 5 hosts, the same `linuxgpiod_bitbang` cable works but is even slower because the RPi 5's RP1 I/O controller adds latency to sysfs GPIO access:

```bash
# Same command as RPi 3B+, works but slow
openFPGALoader --cable linuxgpiod_bitbang --pins 27:22:4:17 design.bit
```

#### RPi 5 (RP1 PIO JTAG — future, fast)

Once the RP1 PIO JTAG support is upstreamed, openFPGALoader can drive JTAG through the RP1's PIO peripheral, which is significantly faster than GPIO bitbang:

```bash
openFPGALoader -c rp1pio --pins 27:22:4:17 design.bit
```

This requires:
- openFPGALoader with RP1 PIO JTAG support (pending upstream): [mithro/openFPGALoader (feature/rp1-jtag-netv2)](https://github.com/mithro/openFPGALoader/tree/feature/rp1-jtag-netv2)
- RP1 JTAG shared library: [mithro/rp1-jtag](https://github.com/mithro/rp1-jtag)

#### Future: NeTV2 board definition in openFPGALoader

Once the NeTV2 board definition is landed upstream in openFPGALoader, the pin mapping will be built-in and the command simplifies to:

```bash
openFPGALoader -b netv2 design.bit
```

This is tracked in the openFPGALoader fork: [mithro/openFPGALoader (feature/rp1-jtag-netv2)](https://github.com/mithro/openFPGALoader/tree/feature/rp1-jtag-netv2)

## Serial / UART

### Primary UART (via RPi GPIO)

| Signal  | FPGA Pin | RPi GPIO     | RPi Header Pin | I/O Standard |
| ------- | -------- | ------------ | -------------- | ------------ |
| FPGA TX | E14      | GPIO15 (RXD) | Pin 10         | LVCMOS33     |
| FPGA RX | E13      | GPIO14 (TXD) | Pin 8          | LVCMOS33     |

The FPGA's TX connects to the RPi's RX (GPIO15) and vice versa. On the RPi, this serial port is available as `/dev/ttyAMA0` or `/dev/serial0`.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

### Secondary UART (via PCIe "hax" pins)

| Signal | FPGA Pin | PCIe Hax Pin | I/O Standard |
| ------ | -------- | ------------ | ------------ |
| TX     | B17      | hax7         | LVCMOS33     |
| RX     | A18      | hax8         | LVCMOS33     |

These auxiliary pins on the PCIe connector provide a second serial channel. They are only usable when the NeTV2 is connected via PCIe (RPi5 setup).

## DDR3 SDRAM

- Capacity: 512 MB (32-bit wide bus, 4 byte lanes)
- I/O Standard: SSTL15_R (1.5V)

| Signal        | FPGA Pins                                      |
| ------------- | ---------------------------------------------- |
| A[13:0]       | U6 V4 W5 V5 AA1 Y2 AB1 AB3 AB2 Y3 W6 Y1 V2 AA3 |
| BA[2:0]       | U5 W4 V7                                       |
| DQ[7:0]       | C2 F1 B1 F3 A1 D2 B2 E2                        |
| DQ[15:8]      | J5 H3 K1 H2 J1 G2 H5 G3                        |
| DQ[23:16]     | N2 M6 P1 N5 P2 N4 R1 P6                        |
| DQ[31:24]     | K3 M2 K4 M3 J6 L5 J4 K6                        |
| DQS_P[3:0]    | E1 K2 P5 M1                                    |
| DQS_N[3:0]    | D1 J2 P4 L1                                    |
| DM[3:0]       | G1 H4 M5 L3                                    |
| CLK_P / CLK_N | R3 / R2                                        |
| CKE           | Y8                                             |
| ODT           | W9                                             |
| CS_N          | V9                                             |
| RAS_N         | Y9                                             |
| CAS_N         | Y7                                             |
| WE_N          | V8                                             |
| RESET_N       | AB5 (LVCMOS15)                                 |

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## PCIe

The NeTV2 supports PCIe x1, x2, and x4 configurations. All share the same clock and reset pins.

| Signal        | FPGA Pins      |
| ------------- | -------------- |
| RST_N         | E18 (LVCMOS33) |
| CLK_P / CLK_N | F10 / E10      |

### Lane assignments

| Config    | RX_P | RX_N | TX_P | TX_N |
| --------- | ---- | ---- | ---- | ---- |
| x1 lane 0 | D11  | C11  | D5   | C5   |
| x2 lane 1 | B10  | A10  | B6   | A6   |
| x4 lane 2 | D9   | C9   | D7   | C7   |
| x4 lane 3 | B8   | A8   | B4   | A4   |

When connected to the RPi5 via PCIe Gen2 x1, the FPGA appears as:
```
Vendor: 10ee (Xilinx)
Device: 7011
```

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## RMII Ethernet

The NeTV2 has its own Ethernet PHY with an RMII interface, providing a 100Base-T network connection independent of the Raspberry Pi's network.

| Signal       | FPGA Pin | I/O Standard |
| ------------ | -------- | ------------ |
| ref_clk      | D17      | LVCMOS33     |
| rst_n        | F16      | LVCMOS33     |
| rx_data[1:0] | A20 B18  | LVCMOS33     |
| crs_dv       | C20      | LVCMOS33     |
| tx_en        | A19      | LVCMOS33     |
| tx_data[1:0] | C18 C19  | LVCMOS33     |
| mdc          | F14      | LVCMOS33     |
| mdio         | F13      | LVCMOS33     |
| rx_er        | B20      | LVCMOS33     |
| int_n        | D21      | LVCMOS33     |

The RMII reference clock runs at 50 MHz (pin D17).

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## HDMI

### HDMI Input 0

| Signal            | FPGA Pins | Notes      |
| ----------------- | --------- | ---------- |
| CLK_P / CLK_N     | L19 / L20 | Inverted   |
| DATA0_P / DATA0_N | K21 / K22 | Inverted   |
| DATA1_P / DATA1_N | J20 / J21 | Inverted   |
| DATA2_P / DATA2_N | J22 / H22 | Inverted   |
| SCL / SDA         | T18 / V18 | I2C (EDID) |

### HDMI Input 1

| Signal            | FPGA Pins   | Notes        |
| ----------------- | ----------- | ------------ |
| CLK_P / CLK_N     | Y18 / Y19   | Inverted     |
| DATA0_P / DATA0_N | AA18 / AB18 | Not inverted |
| DATA1_P / DATA1_N | AA19 / AB20 | Inverted     |
| DATA2_P / DATA2_N | AB21 / AB22 | Inverted     |
| SCL / SDA         | W17 / R17   | SCL inverted |

### HDMI Output 0

| Signal            | FPGA Pins | Notes    |
| ----------------- | --------- | -------- |
| CLK_P / CLK_N     | W19 / W20 | Inverted |
| DATA0_P / DATA0_N | W21 / W22 |          |
| DATA1_P / DATA1_N | U20 / V20 |          |
| DATA2_P / DATA2_N | T21 / U21 |          |

### HDMI Output 1

| Signal            | FPGA Pins | Notes    |
| ----------------- | --------- | -------- |
| CLK_P / CLK_N     | G21 / G22 | Inverted |
| DATA0_P / DATA0_N | E22 / D22 | Inverted |
| DATA1_P / DATA1_N | C22 / B22 | Inverted |
| DATA2_P / DATA2_N | B21 / A21 | Inverted |

All HDMI signals use TMDS_33 I/O standard.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## SPI Flash

| Signal     | FPGA Pin |
| ---------- | -------- |
| CS_N       | T19      |
| MOSI (DQ0) | P22      |
| MISO (DQ1) | R22      |
| VPP (DQ2)  | P21      |
| HOLD (DQ3) | R21      |

Quad SPI mode supported via `spiflash4x`.

## SD Card

| Signal      | FPGA Pin (SPI mode) | FPGA Pin (4-bit mode)       |
| ----------- | ------------------- | --------------------------- |
| CLK         | K18                 | K18                         |
| CS_N / CMD  | M13 / L13           | L13 (CMD)                   |
| MOSI / DATA | L13 / L15           | L15 L16 K14 M13 (DATA[3:0]) |

## Programming

See the [JTAG via RPi GPIO](#jtag-via-rpi-gpio) section above for the full openFPGALoader commands for volatile load and persistent SPI flash programming on RPi 3B+ and RPi 5.

### Quick Reference

```bash
# Volatile load (RPi 3B+ or RPi 5, GPIO bitbang)
openFPGALoader --cable linuxgpiod_bitbang --pins 27:22:4:17 design.bit

# Persistent SPI flash (RPi 3B+ or RPi 5, GPIO bitbang)
openFPGALoader --cable linuxgpiod_bitbang --pins 27:22:4:17 --write-flash design.bit

# Future: with NeTV2 board definition upstream
openFPGALoader -b netv2 design.bit
```

## LiteX Integration

| Property        | Value                                                  |
| --------------- | ------------------------------------------------------ |
| Platform module | `litex_boards.platforms.kosagi_netv2`                  |
| Target module   | `litex_boards.targets.kosagi_netv2`                    |
| Default clock   | `clk50` (50 MHz, pin J19)                              |
| Programmer      | openFPGALoader (`linuxgpiod_bitbang`, pins 27:22:4:17) |
| Toolchain       | Vivado (proprietary) or openXC7 (open source)          |

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## References

- LiteX platform file: <https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py>
- NeTV2 FPGA reference design: <https://github.com/AlphamaxMedia/netv2-fpga>
- NeTV2 MVP scripts (OpenOCD configs): <https://github.com/alphamaxmedia/netv2mvp-scripts>
- bunnie's blog (NeTV2 design): <https://www.bunniestudios.com/blog/?p=4842>
- Crowd Supply campaign: <https://www.crowdsupply.com/alphamax/netv2>
