\[[top](./README.md)\] \[[pinmap](./acorn-pinmap.md)\] \[[wiring](./acorn-pinmap.md)\] \[[pcie programming](./acorn-pcie-programming.md)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)\]

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
| Vendor:Device   | `1e24:021f` Squirrels Research Labs "Acorn CLE-215+" with the factory (mining) firmware in flash; `1e24:0101` for a CLE-101; `10ee:7011` (Xilinx) once a LiteX/Vivado design is in flash |

On RPi 5, the Acorn connects via an mPCIe HAT and appears on PCIe bus `0001:01:00.0` (the RP1 south bridge is `0002:01:00.0`). Reconfiguring the FPGA over JTAG while that endpoint is enumerated crashes a Pi 5 host — detach it first, see [acorn-pcie-programming.md](acorn-pcie-programming.md#detach-the-pcie-endpoint-before-any-jtag-reconfiguration).

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

### Via GPIO JTAG (openFPGALoader) — what the fleet uses

P1 is wired to the Pi's SPI0 pins; openFPGALoader bit-bangs JTAG through libgpiod
(about 16 s for a full XC7A200T bitstream). The load goes to SRAM only and is
lost at power cycle, which is what makes it safe to experiment with.

```bash
echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # MUST detach the endpoint first on a Pi 5
sudo ln -sfn /dev/gpiochip15 /dev/gpiochip0                   # openFPGALoader 0.10.0 on a Pi 5 only
openFPGALoader --cable libgpiod --pins 10:9:11:8 <bitstream.bit>
```

Pin order, the Pi 5 `gpiochip15` trap, the PCIe detach rule and the
`overlayroot=tmpfs` gotcha are all in [acorn-pinmap.md](acorn-pinmap.md).
Prebuilt Vivado bitstreams for every test design and Acorn variant are on the
`vivado-bitstreams-v0.0-496-gf162f60` release — see
[acorn-pcie-programming.md](acorn-pcie-programming.md#prebuilt-vivado-bitstreams).

### Via JTAG (OpenOCD + FT232H)

Alternative for a bench setup — uses an FT232H USB adapter with a BSCAN_SPI proxy bitstream:

```bash
openocd -f openocd_xc7_ft232.cfg -c "init; pld load 0 <bitstream>; exit"
```

### Via SPI Flash

Flash a persistent bitstream using OpenOCD or openFPGALoader. The S25FL256S supports multiboot with fallback. `openFPGALoader --write-flash` does **not** currently work over the GPIO JTAG wiring (the open-source spiOverJtag bridge never toggles CCLK after configuration); see [acorn-pcie-programming.md](acorn-pcie-programming.md).

### Via PCIe (LiteX)

LiteX provides PCIe-based programming via `litepcie_util` when a LiteX bitstream with PCIe support is already loaded. Only pi-sw2-p44 currently boots such a design; the other Welland boards still carry the Sqrl factory firmware.

## Host Inventory

### Welland Site ([site-welland.md](site-welland.md))

Six Acorn CLE-215+ hosts, all Raspberry Pi 5 Rev 1.1, all on the S3300 switch
(switch index 2) under the [VLAN-per-port scheme](site-welland.md#network-topology):
hostname `pi-sw2-p<port>`, IP `10.21.2.<port>`. Probed live 2026-09-03; JTAG /
P2 columns from the 2026-08-31 pin-ID survey in
[acorn-pinmap.md](acorn-pinmap.md#measured-p2-wiring-welland-2026-08-31).

| Host       | Port | IP         | RPi MAC           | RPi (rev)          | Flash contents        | JTAG (P1)          | P2 serial            | Camera | Old name |
| ---------- | ---- | ---------- | ----------------- | ------------------ | --------------------- | ------------------ | -------------------- | ------ | -------- |
| pi-sw2-p29 | 29   | 10.21.2.29 | 88:a2:9e:45:dd:be | Pi 5 2 GB (b04171) | Sqrl `1e24:021f`      | OK                 | OK (J5 wire dead)    | ov5647 | pi4      |
| pi-sw2-p43 | 43   | 10.21.2.43 | 98:fe:54:13:e0:75 | Pi 5 1 GB (a04171) | Sqrl `1e24:021f`      | **empty chain**    | untestable           | ov5647 | —        |
| pi-sw2-p44 | 44   | 10.21.2.44 | 98:fe:54:13:e0:f5 | Pi 5 1 GB (a04171) | LiteX `10ee:7011`     | **empty chain**    | untestable           | ov5647 | —        |
| pi-sw2-p46 | 46   | 10.21.2.46 | 88:a2:9e:45:85:77 | Pi 5 2 GB (b04171) | Sqrl `1e24:021f`      | OK                 | OK                   | ov5647 | pi6      |
| pi-sw2-p47 | 47   | 10.21.2.47 | 98:fe:54:13:f5:75 | Pi 5 1 GB (a04171) | Sqrl `1e24:021f`      | OK                 | **reversed** (K2↔J2) | ov5647 | —        |
| pi-sw2-p48 | 48   | 10.21.2.48 | 88:a2:9e:45:c6:87 | Pi 5 2 GB (b04171) | Sqrl `1e24:021f`      | OK                 | OK                   | ov5647 | pi2      |

All six run the shared bookworm NFS root (kernel 6.12.96, `overlayroot=tmpfs`),
have `/dev/ttyAMA0` enabled with the kernel console on `ttyAMA10`, and publish a
camera feed. The earlier revision of this table listed the first three as
"RPi 5 8GB"; the revision codes say 2 GB.

### PS1 Site ([site-ps1.md](site-ps1.md))

Four Compute Blades (val2 gateway, legacy `10.21.0.1xx` addressing). Probed
2026-08-31.

| Host | Port | IP          | Module               | Flash contents                                   | JTAG (P1)                     | P2 serial                   |
| ---- | ---- | ----------- | -------------------- | ------------------------------------------------ | ----------------------------- | --------------------------- |
| pi14 | e14  | 10.21.0.114 | CM4 Rev 1.1 4 GB     | Sqrl Acorn CLE-101 `1e24:0101`                   | no response — P1 unmated      | untested                    |
| pi16 | e16  | 10.21.0.116 | CM5 Lite Rev 1.0 8 GB| Sqrl Acorn CLE-101 `1e24:0101`                   | no response — P1 unmated      | untested                    |
| pi18 | e18  | 10.21.0.118 | CM4 Rev 1.1 4 GB     | none — M.2 slot empty                            | n/a                           | n/a                         |
| pi20 | e20  | 10.21.0.120 | CM5 Lite Rev 1.0 8 GB| XC7A100T design `10ee:7011`, DNA `0x0028e5c45e304854` | OK (openFPGALoader 0.13.1) | OK, crossover present       |

These boards have been documented as LiteFury; the factory PCI ID on pi14/pi16
identifies them as Sqrl Acorn CLE-101 (same PCB family, XC7A100T, 512 MB).

### Deployment Summary

| Variant                  | FPGA          | DDR3   | Welland (deployed) | Welland (pending) | PS1 (deployed) | PS1 (pending)        |
| ------------------------ | ------------- | ------ | ------------------ | ----------------- | -------------- | -------------------- |
| Acorn CLE-215+           | XC7A200T (-3) | 1 GB   | ×6                 | —                 | —              | —                    |
| LiteFury / Acorn CLE-101 | XC7A100T (-2) | 512 MB | —                  | —                 | ×3             | ×1 host (pi18) empty |

No USB serial devices on any host — JTAG and UART are connected via adapted Pico-EZmate cables to the RPi GPIO header (see [acorn-pinmap.md](acorn-pinmap.md)). PCIe is via the M.2 HAT.

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
