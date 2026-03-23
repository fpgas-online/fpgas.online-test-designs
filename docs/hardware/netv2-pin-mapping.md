\[[top](./README.md)\] \[[spec](./netv2.md)\]

# NeTV2 Pin Mapping

Pin mapping for the Kosagi NeTV2 as connected in the fpgas.online test infrastructure. Two hosts with different FPGA variants:

| Host | FPGA Variant | JTAG IDCODE | Tool |
|------|-------------|-------------|------|
| rpi5-netv2 | XC7A100T-FGG484-2 | `0x03631093` | openFPGALoader (rp1pio) |
| rpi3-netv2 | XC7A35T-FGG484-2 | `0x0362D093` | OpenOCD (bcm2835gpio) |

Both variants share the same FGG484 package and identical pin assignments.

## FPGA Device

| Parameter | Value |
|-----------|-------|
| FPGA (rpi5) | Xilinx Artix-7 XC7A100T-FGG484-2 |
| FPGA (rpi3) | Xilinx Artix-7 XC7A35T-FGG484-2 |
| Package | FGG484 (484-ball BGA) |
| System clock | 50 MHz (pin J19, LVCMOS33) |
| Toolchain | openXC7 (open source) or Vivado |

CI builds variant-specific bitstreams: `*-netv2-a7-35t` and `*-netv2-a7-100t`.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

## Programming Interface (JTAG)

The NeTV2 is programmed via JTAG through RPi GPIO pins on the 40-pin header. The two hosts use different tools due to their RPi models.

### JTAG Pin Mapping (RPi → FPGA)

| JTAG Signal | RPi GPIO | RPi Header Pin | Direction |
|-------------|----------|----------------|-----------|
| TCK | GPIO4 | Pin 7 | Output |
| TMS | GPIO17 | Pin 11 | Output |
| TDI | GPIO27 | Pin 13 | Output |
| TDO | GPIO22 | Pin 15 | Input |
| SRST | GPIO24 | Pin 18 | Output |

### rpi5-netv2 (RPi 5)

```
sudo openFPGALoader -c rp1pio --pins 27:22:4:17 <bitstream>
```

Pin argument order: `TDI:TDO:TCK:TMS`. Uses the RPi 5's RP1 GPIO peripheral for JTAG bitbang.

### rpi3-netv2 (RPi 3)

```
sudo openocd -f ~/netv2/alphamax-rpi.cfg -c 'init; pld load 0 <bitstream>; exit'
```

Uses OpenOCD 0.10.x with `bcm2835gpio` interface. Config: `bcm2835gpio_jtag_nums 4 17 27 22`, `bcm2835gpio_srst_num 24`, peripheral base `0x3F000000`.

Note: `pld load 0` uses device index (OpenOCD 0.10.x syntax), not device name.

## UART Interface

The FPGA's UART pins connect to the RPi's GPIO UART via the 40-pin stacking header. This is a direct GPIO connection.

| Signal | FPGA Pin | RPi GPIO | RPi Header Pin | IO Standard |
|--------|----------|----------|----------------|-------------|
| TX (FPGA → RPi) | E14 | GPIO15 (RXD) | Pin 10 | LVCMOS33 |
| RX (RPi → FPGA) | E13 | GPIO14 (TXD) | Pin 8 | LVCMOS33 |

### Serial Device by Host

| Host | RPi GPIO UART Device | Symlink | Reason |
|------|---------------------|---------|--------|
| rpi5-netv2 | `/dev/ttyAMA0` | — | RP1 PL011 UART on GPIO14/15 |
| rpi3-netv2 | `/dev/ttyS0` | `/dev/serial0` | Mini UART (Bluetooth claims PL011) |

### rpi5-netv2 Specifics

- After stopping `serial-getty`, GPIO14/15 revert to plain GPIO mode. Must run `pinctrl set 14 a4; pinctrl set 15 a4` to restore UART function (ALT4 = TXD0/RXD0).

### rpi3-netv2 Specifics

- `netv2-status.js` (a pm2-managed Node.js monitoring app) continuously sends `json on` commands to the FPGA via the serial port. Must be stopped with `pm2 stop all` (binary at `/home/pi/n/bin/node /home/pi/n/lib/node_modules/pm2/bin/pm2`).
- `serial-getty` must also be stopped.
- Bluetooth (`hciattach`) uses `/dev/ttyAMA0` (PL011), so the GPIO UART is the mini UART at `/dev/ttyS0`.

### UART Test Parameters

| Parameter | Value |
|-----------|-------|
| Baud rate | 115200 |
| Test args | `--port /dev/ttyAMA0 --board netv2 --skip-banner` |
| `--skip-banner` | Required because OpenOCD programming takes ~10s; BIOS banner is missed |

## PMOD / GPIO Loopback

The NeTV2 GPIO loopback uses FPGA pins E13 (input) and E14 (output) — the same pins as UART. This is a 1-bit loopback through the RPi's GPIO14/15.

| Drive RPi GPIO | FPGA Pin (Input) | Read RPi GPIO | FPGA Pin (Output) |
|---------------|-------------------|---------------|-------------------|
| GPIO14 | E13 | GPIO15 | E14 |

## RMII Ethernet

The NeTV2 has an on-board Ethernet PHY with RMII interface, providing 100Base-T independent of the RPi's network.

| Signal | FPGA Pin | IO Standard |
|--------|----------|-------------|
| ref_clk | D17 | LVCMOS33 |
| rst_n | F16 | LVCMOS33 |
| rx_data[1:0] | A20 B18 | LVCMOS33 |
| crs_dv | C20 | LVCMOS33 |
| tx_en | A19 | LVCMOS33 |
| tx_data[1:0] | C18 C19 | LVCMOS33 |
| mdc | F14 | LVCMOS33 |
| mdio | F13 | LVCMOS33 |
| rx_er | B20 | LVCMOS33 |
| int_n | D21 | LVCMOS33 |

The RMII reference clock runs at 50 MHz.

## PCIe

The NeTV2 supports PCIe x1, x2, and x4. Only rpi5-netv2 has a PCIe connection (RPi 3 has no PCIe).

| Signal | FPGA Pin(s) | Notes |
|--------|-------------|-------|
| RST_N | E18 | LVCMOS33 |
| CLK_P / CLK_N | F10 / E10 | Reference clock |

### Lane Assignments

| Config | RX_P | RX_N | TX_P | TX_N |
|--------|------|------|------|------|
| x1 lane 0 | D11 | C11 | D5 | C5 |
| x2 lane 1 | B10 | A10 | B6 | A6 |
| x4 lane 2 | D9 | C9 | D7 | C7 |
| x4 lane 3 | B8 | A8 | B4 | A4 |

### PCIe Detection (rpi5-netv2)

| Parameter | Value |
|-----------|-------|
| Vendor ID | `10ee` (Xilinx) |
| Device ID | `7011` |
| Link | Gen2 x1 |
| Command | `lspci -d 10ee:7011` |

## SPI Flash

On-board quad SPI flash for persistent bitstream storage.

| Signal | FPGA Pin | IO Standard |
|--------|----------|-------------|
| CS_N | T19 | LVCMOS33 |
| MOSI (DQ0) | P22 | LVCMOS33 |
| MISO (DQ1) | R22 | LVCMOS33 |
| VPP (DQ2) | P21 | LVCMOS33 |
| HOLD (DQ3) | R21 | LVCMOS33 |

## DDR3 SDRAM

512 MB DDR3 (32-bit wide, 4 byte lanes).

| Signal | FPGA Pins | IO Standard |
|--------|-----------|-------------|
| A[13:0] | U6 V4 W5 V5 AA1 Y2 AB1 AB3 AB2 Y3 W6 Y1 V2 AA3 | SSTL15_R |
| BA[2:0] | U5 W4 V7 | SSTL15_R |
| DQ[7:0] | C2 F1 B1 F3 A1 D2 B2 E2 | SSTL15_R |
| DQ[15:8] | J5 H3 K1 H2 J1 G2 H5 G3 | SSTL15_R |
| DQ[23:16] | N2 M6 P1 N5 P2 N4 R1 P6 | SSTL15_R |
| DQ[31:24] | K3 M2 K4 M3 J6 L5 J4 K6 | SSTL15_R |
| DQS_P[3:0] | E1 K2 P5 M1 | DIFF_SSTL15_R |
| DQS_N[3:0] | D1 J2 P4 L1 | DIFF_SSTL15_R |
| DM[3:0] | G1 H4 M5 L3 | SSTL15_R |
| CLK_P / CLK_N | R3 / R2 | DIFF_SSTL15_R |
| CKE | Y8 | SSTL15_R |
| ODT | W9 | SSTL15_R |
| CS_N | V9 | SSTL15_R |
| RAS_N | Y9 | SSTL15_R |
| CAS_N | Y7 | SSTL15_R |
| WE_N | V8 | SSTL15_R |
| RESET_N | AB5 | LVCMOS15 |

## HDMI

The NeTV2 has 2 HDMI inputs and 2 HDMI outputs. All use TMDS_33 IO standard.

### HDMI Input 0

| Signal | FPGA Pins | Notes |
|--------|-----------|-------|
| CLK_P / CLK_N | L19 / L20 | Inverted |
| DATA0_P / DATA0_N | K21 / K22 | Inverted |
| DATA1_P / DATA1_N | J20 / J21 | Inverted |
| DATA2_P / DATA2_N | J22 / H22 | Inverted |
| SCL / SDA | T18 / V18 | I2C (EDID) |

### HDMI Input 1

| Signal | FPGA Pins | Notes |
|--------|-----------|-------|
| CLK_P / CLK_N | Y18 / Y19 | Inverted |
| DATA0_P / DATA0_N | AA18 / AB18 | Not inverted |
| DATA1_P / DATA1_N | AA19 / AB20 | Inverted |
| DATA2_P / DATA2_N | AB21 / AB22 | Inverted |
| SCL / SDA | W17 / R17 | SCL inverted |

### HDMI Output 0

| Signal | FPGA Pins | Notes |
|--------|-----------|-------|
| CLK_P / CLK_N | W19 / W20 | Inverted |
| DATA0_P / DATA0_N | W21 / W22 | |
| DATA1_P / DATA1_N | U20 / V20 | |
| DATA2_P / DATA2_N | T21 / U21 | |

### HDMI Output 1

| Signal | FPGA Pins | Notes |
|--------|-----------|-------|
| CLK_P / CLK_N | G21 / G22 | Inverted |
| DATA0_P / DATA0_N | E22 / D22 | Inverted |
| DATA1_P / DATA1_N | C22 / B22 | Inverted |
| DATA2_P / DATA2_N | B21 / A21 | Inverted |

## SD Card

Full-size SD slot supporting SPI and 4-bit modes.

### SPI Mode

| Signal | FPGA Pin |
|--------|----------|
| CLK | K18 |
| CS_N | M13 |
| MOSI | L13 (PULLUP) |
| MISO | L15 (PULLUP) |

### 4-bit Mode

| Signal | FPGA Pin |
|--------|----------|
| CLK | K18 |
| CMD | L13 (PULLUP) |
| DATA[3:0] | L15 L16 K14 M13 (PULLUP) |

## User LEDs

| LED | FPGA Pin | IO Standard |
|-----|----------|-------------|
| 0 | M21 | LVCMOS33 |
| 1 | N20 | LVCMOS33 |
| 2 | L21 | LVCMOS33 |
| 3 | AA21 | LVCMOS33 |
| 4 | R19 | LVCMOS33 |
| 5 | M16 | LVCMOS33 |

## References

- LiteX platform file: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)
- NeTV2 schematic: `artifacts/netv2-schematic.pdf`
- OpenOCD config: `tmp/alphamax-rpi3.cfg`
- NeTV2 MVP scripts: [github.com/alphamaxmedia/netv2mvp-scripts](https://github.com/alphamaxmedia/netv2mvp-scripts)
- bunnie's blog: [bunniestudios.com](https://www.bunniestudios.com/blog/?p=4842)
