\[[top](./README.md)\] \[[pinmap](./arty-a7-pin-mapping.md)\] \[[pmod hat](./rpi-hat-pmod.md)\] \[[buy](https://digilent.com/shop/arty-a7-artix-7-fpga-development-board/)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)\]

# Digilent Arty A7

The Digilent Arty A7 is a Xilinx Artix-7 development board used in the fpgas.online test infrastructure. It connects to the host via USB (FTDI FT2232HQ providing both JTAG and UART) and optionally through PMOD connectors via a PMOD HAT adapter on a Raspberry Pi.

## Installing the Arty Packages

Add the fpgas.online APT repository first ([README: Installing the Packages](../../README.md#installing-the-packages)), then on the Arty's Pi:

```bash
sudo apt install fpgas-online-arty
```

| Package | Installs |
|---------|----------|
| `fpgas-online-arty` | sets the host up as having an Arty, and enables `fpgas-verify.service` |
| `fpgas-online-arty-tools` | the Arty's module of `fpgas_online_verify`, and `fpgas-arty-verify`; with `python3-serial` and openFPGALoader |
| `fpgas-online-arty-bitstreams` | the Arty A7-35T test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/arty/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

At boot the check finds the Arty by its FT2232H on USB (`0403:6010`). It then loads the UART, DDR and SPI flash test designs into SRAM with openFPGALoader, one at a time, and runs each one's host test on `/dev/ttyUSB1`. Last, it reads back the flash's boot image region (the first 2.1 MiB) through openFPGALoader's SPI-over-JTAG bridge. The FTDI serial number, the flash's JEDEC ID and that region's sha256 are what `changed` compares. The Arty is left running the SPI-over-JTAG bridge, and comes back to its flash image at the next power cycle. The PMOD loopback, pin identification and Ethernet tests need the PMOD HAT or a USB Ethernet adapter, so only `fpgas-arty-debug` runs them.

For the fpgas.online openFPGALoader build, add the [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf) **before** installing; otherwise apt installs Debian's `openfpgaloader`, which also works for the Arty.

The Arty's check has not yet been run on an Arty.

**Check the board now**, and see what each test printed:

```bash
sudo fpgas-verify                          # what the boot unit runs: report, publish, exit 0 only for pass
sudo fpgas-arty-verify --no-publish --report -   # this board only, the JSON report on stdout
```

The results are in the [README](../../README.md#installing-the-packages). `changed` means the board, or its flash, differs from what was recorded last time; after flashing or swapping it on purpose, `sudo fpgas-verify --update` records the new state.

**When a check fails**, `sudo apt install fpgas-online-arty-debug` for step-by-step tools:

```bash
sudo fpgas-arty-debug detect           # is the board there, and what was found
fpgas-arty-debug list                  # every test, whether the boot check runs it, and its bitstream
sudo fpgas-arty-debug check            # the installed bitstreams against their manifest
sudo fpgas-arty-debug test ddr   # load one test's design and run its test, output live
```

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

In the fpgas.online setup, the Arty A7's PMOD connectors can be connected to a Raspberry Pi via a [Digilent PMOD HAT adapter](rpi-hat-pmod.md). This enables PMOD loopback testing where the RPi drives signals through the PMOD HAT to the Arty's PMOD connectors and verifies correct signal propagation.

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

### Which flash part a board has

Digilent has fitted three different 128 Mbit parts over the Arty A7's life,
and they are not interchangeable in software: the S25FL127S answers the Read
SFDP command (5Ah) and drops the DDR read commands, and its sector layout
differs (255 × 64 KB + 16 × 4 KB against 254 × 64 KB + 32 × 4 KB). Table 5.2.1
"Flash memory part loaded" in section 5.2 of the
[Arty A7 Reference Manual](https://digilent.com/reference/programmable-logic/arty-a7/reference-manual)
gives the part by PCB revision and by whether a sticker with the part number
is on the board:

| Manufacturer | P/N | PCB revision | Package marking |
|---|---|---|---|
| Micron | `N25Q128A13ESF40` | ≤ C, no sticker | none |
| Spansion/Infineon | `S25FL128SAG[M\|N]FI00` | > C and ≤ E with no sticker, or ≥ E with a sticker | `FL128SAIF00` |
| Spansion/Infineon | `S25FL127SABMFx00` | ≥ E with a sticker | `FL127SxF00` |

The manual's own advice is "check the PCB revision and any stickers placed on
the PCB with the flash part number printed on it". Vivado's
`s25fl128s-3.3v-qspi-x4-single` configuration works for both Spansion parts,
and `mt25ql128` is an alias for the Micron one.

**Reading it from the board.** openFPGALoader 1.1 and later loads its
spiOverJtag bridge into the FPGA and asks the flash for its JEDEC id:

```bash
sudo openFPGALoader -b arty_a7_35t --detect -f      # or arty_a7_100t
# ...
# JEDEC ID: 0x012018
# Detected: spansion S25FL128S 256 sectors size: 128Mb
```

Two caveats. Loading the bridge replaces whatever design was in the fabric
until the next power cycle reloads it from flash, so do this on a rig nobody
is using. And **the S25FL128S and the S25FL127S both answer JEDEC `0x012018`**,
so what openFPGALoader names S25FL128S is either Spansion part; the read rules
the Micron part in or out and no more. Telling the two Spansion parts apart
takes the package marking or the sticker, read by eye, or an SFDP probe
(5Ah), which only the S25FL127S answers. openFPGALoader needs the bridge
bitstream at `/usr/share/openFPGALoader/spiOverJtag_xc7a35tcsg324.bit.gz`
(and the `xc7a100t` one for a -100); the rp1-jtag build of openFPGALoader
on the welland pool image does not ship them, so they were fetched from
[upstream](https://github.com/trabucayre/openFPGALoader/tree/master/spiOverJtag)
by hand.

**What the welland pool has.** Read on 2026-09-09 through each board's own
FT2232 on `pi-sw2-p16`, `p37`, `p38` and `p42`: every one is an XC7A35T
(idcode `0x362d093`) with a Spansion part at JEDEC `0x012018`, so none has the
Micron flash. The other three signals worth reading at the same time, since
neither the serial nor the model badge gives them:

```bash
sudo openFPGALoader -c digilent --detect        # idcode -> 35T or 100T
sudo openFPGALoader -c digilent --read-dna      # the die's Device DNA
```

The Digilent serial (`210319…`, from the FT2232's iSerialNumber and on the
sticker) identifies the *board*; the DNA identifies the *die*; the idcode
says which die it is. The rpi-hdcp-output repository's
`tools/read_arty_identity.py` reads all four in one pass, and its
`tools/hardware_identity.py` records the result per serial.

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
