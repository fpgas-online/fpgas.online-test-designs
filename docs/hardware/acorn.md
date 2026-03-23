\[[top](./README.md)\] \[[pinmap](./acorn-pinmap.md)\] \[[wiring](./acorn-wiring-guide.md)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)\]

# Sqrl Acorn CLE-215+ / LiteFury

The Sqrl Acorn CLE-215+ is an M.2 form factor PCIe FPGA accelerator card, pin-compatible with the [NiteFury and LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury) boards. In the fpgas.online infrastructure, it connects to Raspberry Pi 5 hosts via an mPCIe HAT adapter, with JTAG and UART via adapted Pico-EZmate cables to the RPi GPIO header.

See [acorn-pinmap.md](acorn-pinmap.md) for the full RPi GPIO pinmap.

## Key Specifications

| Parameter        | Value                            |
| ---------------- | -------------------------------- |
| FPGA             | Xilinx Artix-7 XC7A200T-FBG484-3 |
| Package          | FBG484 (484-ball BGA)            |
| Logic cells      | 215,360                          |
| CLB flip-flops   | 269,200                          |
| DSP slices       | 740                              |
| Block RAM        | 13,140 Kib                       |
| GTP transceivers | 4 (up to 6.6 Gb/s each)          |
| DDR3 SDRAM       | 1 GiB (MT41K512M16, 32-bit)      |
| SPI Flash        | S25FL256S (256 Mbit, quad SPI)   |
| PCIe             | Gen2 x4 (M.2 M-key)              |
| Form factor      | M.2 2280                         |
| Power            | Via M.2 / mPCIe slot (3.3V)      |
| Process          | 28 nm HPL                        |

Source: [LiteX sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)

## Compatible Boards

All boards share the same PCB layout and pin assignments. The LiteX platform file `sqrl_acorn.py` works for all variants — change only the device string.

| Board          | FPGA            | Speed Grade | DDR3   | PCIe    |
| -------------- | --------------- | ----------- | ------ | ------- |
| LiteFury       | XC7A100T-FBG484 | -2          | 512 MB | Gen2 x4 |
| NiteFury       | XC7A200T-FBG484 | -2          | 512 MB | Gen2 x4 |
| Acorn CLE-101  | XC7A100T-FBG484 | -2          | 512 MB | Gen2 x4 |
| Acorn CLE-215  | XC7A200T-FBG484 | -2          | 1 GB   | Gen2 x4 |
| Acorn CLE-215+ | XC7A200T-FBG484 | -3          | 1 GB   | Gen2 x4 |

Source: [NiteFury and LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury), [LiteX Acorn CLE-215 wiki](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)

The CLE-215+ is equivalent to the RHSResearchLLC NiteFury board but with 1 GB DDR3 (vs 512 MB).

## PCIe Interface

| Parameter       | Value                                    |
| --------------- | ---------------------------------------- |
| Link            | Gen2 x4 (4-lane GTP transceivers)        |
| Connector       | M.2 M-key                                |
| Reference clock | Differential (FPGA pins F6/E6)           |
| Reset           | LVCMOS33 (FPGA pin J1, internal pull-up) |
| Vendor ID       | `10ee` (Xilinx)                          |
| Device ID       | (design-dependent)                       |

On RPi 5, the Acorn connects via an mPCIe HAT and appears on PCIe bus `0001:01:00.0`.

## Clock

| Signal         | FPGA Pins | Standard    | Frequency |
| -------------- | --------- | ----------- | --------- |
| System clock   | J19 / H19 | DIFF_SSTL15 | 200 MHz   |
| PCIe ref clock | F6 / E6   | —           | 100 MHz   |

## User LEDs

| LED | FPGA Pin |
| --- | -------- |
| 0   | G3       |
| 1   | H3       |
| 2   | G4       |
| 3   | H4       |

## Serial (UART)

Available on the P2 connector (active low accent LEDs double as serial adapter pins):

| Signal | FPGA Pin |
| ------ | -------- |
| RX     | J2       |
| TX     | K2       |

## SPI Flash

| Signal | FPGA Pin |
| ------ | -------- |
| CS_n   | T19      |
| MOSI   | P22      |
| MISO   | R22      |
| WP     | P21      |
| HOLD   | R21      |

Flash part: Spansion S25FL256S (256 Mbit). Supports multiboot with separate fallback and operational bitstream regions.

## DDR3 SDRAM

1 GiB MT41K512M16, 32-bit wide with 4 byte lanes. Uses 7-series native DDR PHY (A7DDRPHY).

| Signal Group | FPGA Pins                                               |
| ------------ | ------------------------------------------------------- |
| Address      | M15/L21/M16/L18/K21/M18/M21/N20/M20/N19/J21/M22/K22/N18 |
| Bank         | N22/M21/N19                                             |
| DQ[7:0]      | C2/F1/B1/F3/A1/D2/B2/E2                                 |
| DQ[15:8]     | J5/H3/K1/H2/J1/K2/H1/J3                                 |
| DQ[23:16]    | N2/M6/P1/N5/P2/N4/R1/P6                                 |
| DQ[31:24]    | K3/M2/K4/M3/J6/L3/J4/K6                                 |
| CLK_P/N      | K17/J17                                                 |
| CKE          | J18                                                     |
| ODT          | K19                                                     |
| CS_N         | L19                                                     |
| RAS_N        | L20                                                     |
| CAS_N        | K18                                                     |
| WE_N         | L22                                                     |
| RESET_N      | G17                                                     |

## Programming

### Via JTAG (OpenOCD + FT232H)

Uses an FT232H USB adapter with a BSCAN_SPI proxy bitstream:

```bash
openocd -f openocd_xc7_ft232.cfg -c "init; pld load 0 <bitstream>; exit"
```

### Via SPI Flash

Flash a persistent bitstream using OpenOCD or openFPGALoader. The S25FL256S supports multiboot with fallback.

### Via PCIe (LiteX)

LiteX provides PCIe-based programming via `litepcie_util` when a LiteX bitstream with PCIe support is already loaded.

## Host Inventory

### Welland Site ([site-welland.md](site-welland.md))

| Host | Port   | IP          | RPi Model         | Board          | Status   |
| ---- | ------ | ----------- | ----------------- | -------------- | -------- |
| pi2  | port 2 | 10.21.0.102 | RPi 5 8GB Rev 1.1 | Acorn CLE-215+ | Deployed |
| pi4  | port 4 | 10.21.0.104 | RPi 5 8GB         | Acorn CLE-215+ | Pending  |
| pi6  | port 6 | 10.21.0.106 | RPi 5 8GB         | Acorn CLE-215+ | Pending  |
| pi8  | port 8 | 10.21.0.108 | RPi 5 8GB         | Acorn CLE-215+ | Pending  |
| —    | —      | —           | RPi 5             | Acorn CLE-215+ | Pending  |
| —    | —      | —           | RPi 5             | LiteFury       | Pending  |

### PS1 Site ([site-ps1.md](site-ps1.md))

| Host | Port | IP          | RPi Model    | Board    | Status   |
| ---- | ---- | ----------- | ------------ | -------- | -------- |
| pi14 | e14  | 10.21.0.114 | RPi CM4      | LiteFury | Deployed |
| pi16 | e16  | 10.21.0.116 | RPi CM5 Lite | LiteFury | Deployed |
| —    | —    | —           | —            | LiteFury | Pending  |
| —    | —    | —           | —            | LiteFury | Pending  |
| —    | —    | —           | —            | LiteFury | Pending  |
| —    | —    | —           | —            | LiteFury | Pending  |

### Deployment Summary

| Variant        | FPGA          | DDR3   | Welland (deployed) | Welland (pending) | PS1 (deployed) | PS1 (pending) |
| -------------- | ------------- | ------ | ------------------ | ----------------- | -------------- | ------------- |
| Acorn CLE-215+ | XC7A200T (-3) | 1 GB   | ×1                 | ×4                | —              | —             |
| LiteFury       | XC7A100T (-2) | 512 MB | —                  | ×1                | ×2             | ×4            |

No USB serial devices on any host — JTAG and UART are connected via adapted Pico-EZmate cables to the RPi GPIO header (see [acorn-wiring-guide.md](acorn-wiring-guide.md)). PCIe is via the M.2 HAT.

## LiteX Support

The LiteX target (`litex_boards/targets/sqrl_acorn.py`) provides:

- PCIe Gen2 x4 endpoint with DMA
- DDR3 SDRAM controller (LiteDRAM)
- SPI Flash access (LiteSPI)
- ICAP for warm-boot / multiboot
- Optional Ethernet via PCIe bridge

Build example:

```bash
python3 -m litex_boards.targets.sqrl_acorn --build
```

## References

- LiteX platform: [sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)
- LiteX target: [sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/targets/sqrl_acorn.py)
- LiteX wiki: [Use LiteX on the Acorn CLE-215](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)
- OpenOCD flashing: [NiteFury/Acorn flashing guide](https://github.com/Gbps/nitefury-openocd-flashing-guide)
- Running Linux: [Acorn CLE-215+ blog post](https://spoolqueue.com/new-design/fpga/migen/litex/2020/08/11/acorn-cle-215.html)
