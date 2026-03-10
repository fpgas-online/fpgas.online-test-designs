# Infrastructure Overview

This document describes the physical host machines, FPGA boards, programming methods, and communication interfaces used in the fpgas.online test infrastructure.

## Network Topology

```
                          ┌─────────────────────────────┐
                          │  tweed.welland.mithis.com    │
Internet ─── eth-uplink ──│  Debian 12 (bookworm)        │
 (10.99.21.2)             │  x86_64, kernel 6.1.0-34     │
                          │  Intel 3rd Gen Core           │
                          │                               │
                          │  dnsmasq (DHCP/DNS/TFTP/PXE)  │
              eth-local ──│  10.21.0.1/16                 │
             (PoE switch) │  domain: fpgas.welland.       │
                          │          mithis.com           │
                          └───────────┬───────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
              ┌─────┴─────┐   ┌──────┴──────┐   ┌──────┴──────┐
              │ RPi 4B     │   │ RPi 3B+     │   │ RPi 3B+     │
              │ + Arty A7  │   │ + Fomu EVT  │   │ + TT08      │
              │ + PMOD HAT │   │ + OpenVizsla│   │ (RP2040)    │
              └────────────┘   └─────────────┘   └─────────────┘
                  (×3)             (×1)              (×2)
```

All Raspberry Pis netboot via PXE/TFTP from tweed. They connect to a PoE switch with numbered ports. Each RPi has a USB Ethernet adapter for the Arty board's Ethernet PHY testing.

Source: dnsmasq configuration on tweed (`/etc/dnsmasq.d/rpi.conf`), verified via SSH 2026-03-09.

## Gateway: tweed.welland.mithis.com

| Property | Value |
|----------|-------|
| Role | Network gateway, DHCP/DNS/TFTP/PXE server |
| Hardware | Intel 3rd Gen Core (QM77 chipset) |
| OS | Debian 12 (bookworm) |
| Kernel | 6.1.0-34-amd64 |
| eth-uplink | 10.99.21.2/30 (internet-facing) |
| eth-local | 10.21.0.1/16 (RPi network) |
| Domain | fpgas.welland.mithis.com |
| PCI | 2× Intel 82574L GbE, Tundra PCI bridge, Matrox G200eW |
| SSH access | `ssh root@tweed.welland.mithis.com` (via WireGuard `wg-desktop`, route to 10.21.0.1) |

Tweed does **not** host any FPGA boards directly. It serves as the network gateway and PXE boot server for the RPi fleet. The RPis are on the `eth-local` (10.21.0.0/16) network.

**SSH to RPis**: Direct SSH from external machines requires WireGuard VPN (`wg-desktop` interface routes 10.21.0.0/16). Alternatively, use nested SSH through tweed: `ssh root@tweed.welland.mithis.com "ssh root@<rpi-ip> '<command>'"`. The RPis only accept root's SSH key from tweed itself.

## FPGA Board Inventory

All data verified via SSH on 2026-03-09 from live hardware.

### Arty A7-35T Boards (×4, on RPi 4B hosts with PMOD HATs)

| Host | Switch Port | IP | RPi Model | Arty Serial | Arty DNA | USB Ethernet | Serial Devices |
|------|------------|-----|-----------|-------------|----------|-------------|----------------|
| pi3 | port 3 | 10.21.0.103 | RPi 4B Rev 1.5 | 210319B3E5C5 | 0x002c8d02251ea854 | DM9601 (00:e0:4c:53:44:58) | ttyUSB0, ttyUSB1 |
| pi5 | port 5 | 10.21.0.105 | RPi 4B Rev 1.5 | 210319B0C238 | 0x0144cd2a47442854 | Linksys GbE (60:38:e0:e3:56:4f) | ttyUSB0, ttyUSB1 |
| pi9 | port 9 | 10.21.0.109 | RPi 4B Rev 1.5 | 210319B301DE | 0x00628502251ea85c | ASIX AX88179 (f8:e4:3b:0f:c1:e6) | ttyUSB0, ttyUSB1 |
| pi11 | port 11 | 10.21.0.111 | RPi 3B+ Rev 1.3 | (FTDI disconnected) | - | Apple Eth (48:d7:05:e9:40:52) | **none** |

Each working Arty A7 connects via FTDI FT2232C/D/H (USB VID:PID `0403:6010`, labelled "Digilent USB Device"). The FT2232 provides two interfaces:
- **if00** → `/dev/ttyUSB0` — JTAG (used by openFPGALoader)
- **if01** → `/dev/ttyUSB1` — UART serial console (115200 baud)

The serial device path is: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SERIAL>-if01-port0`

Each RPi also has a separate USB Ethernet adapter connected to the Arty's Ethernet port for network testing.

**pi11 note**: FTDI is disconnected — no USB serial devices present. This board cannot be programmed or tested until the USB connection is restored.

Source: `lsusb` and `ls /dev/serial/by-id/` output from each RPi.

### Fomu EVT (×1, on RPi 3B+)

| Host | Switch Port | IP | RPi Model | USB VID:PID | DFU Version |
|------|------------|-----|-----------|-------------|-------------|
| pi17 | port 17 | 10.21.0.117 | RPi 3B+ Rev 1.3 | 1209:5bf0 | v2.0.4 |

The Fomu EVT appears as "Generic Fomu EVT running DFU Bootloader v2.0.4". No serial devices — the Fomu uses native USB for communication.

Also on pi17: **OpenVizsla USB sniffer/analyzer** (VID:PID `1d50:607c`).

Source: `lsusb` output from pi17.

### Tiny Tapeout Boards (×2, on RPi 3B+ hosts)

| Host | Switch Port | IP | RPi Model | Board | USB VID:PID | Serial Device |
|------|------------|-----|-----------|-------|-------------|---------------|
| pi23 | port 23 | 10.21.0.123 | RPi 3B+ Rev 1.3 | TT08 | 2e8a:0005 | /dev/ttyACM0 |
| pi25 | port 25 | 10.21.0.125 | RPi 3B+ Rev 1.3 | TT06 | 2e8a:0005 | /dev/ttyACM0 |

The Tiny Tapeout boards appear as "MicroPython Board in FS mode" (RP2040, VID:PID `2e8a:0005`). Each presents a serial console on `/dev/ttyACM0`.

Serial device paths:
- pi23 (TT08): `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_de641070db5b2d27-if00`
- pi25 (TT06): `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_de640cb1d3357125-if00`

Source: `lsusb` and `ls /dev/serial/by-id/` output from pi23, pi25.

### Other Hosts on the Network

| Host | Switch Port | IP | RPi Model | Notes |
|------|------------|-----|-----------|-------|
| pi7 | port 7 | 10.21.0.107 | RPi 4 | PoE fault — offline |
| pi19 | port 19 | 10.21.0.119 | RPi 3B+ | Tiny Tapeout ASIC board |
| pi21 | port 21 | 10.21.0.121 | RPi 3B+ | Fomu EVT (iCE40UP5K) |
| pi27 | port 27 | 10.21.0.127 | RPi 3B+ | Tiny Tapeout FPGA Demo Board + PMOD HAT |
| pi29 | port 29 | 10.21.0.129 | RPi 3B+ | Tiny Tapeout FPGA Demo Board + PMOD HAT |
| pi31 | port 31 | 10.21.0.131 | RPi 3B+ | Tiny Tapeout FPGA Demo Board + PMOD HAT |
| pi33 | port 33 | 10.21.0.133 | RPi 3B+ | Tiny Tapeout FPGA Demo Board + PMOD HAT |

Source: dnsmasq DHCP configuration on tweed.

### NeTV2 Boards (separate network)

The NeTV2 boards are on a **separate network** from the tweed-managed RPi fleet, accessible via different hostnames:

| Host | IP (via DNS) | RPi Model | Board | Connections | SSH |
|------|-------------|-----------|-------|-------------|-----|
| rpi5-netv2.iot.welland.mithis.com | 10.1.90.210/211 | RPi 5 Model B Rev 1.0 | NeTV2 (bare developer) | GPIO + PCIe Gen2 x1 | `tim@rpi5-netv2.iot.welland.mithis.com` (via `wg-desktop`) |
| rpi3-netv2.iot.welland.mithis.com | 10.1.90.212/213 | RPi 3 | NeTV2 (stock packaged) | GPIO only | Auth issues (key not accepted) |

**rpi5-netv2** details (verified via SSH):
- OS: Debian 13 (Trixie), kernel 6.12.47+rpt-rpi-2712 aarch64
- Software: OpenOCD installed, no openFPGALoader, no LiteX
- USB: ASIX AX88179 Gigabit Ethernet adapter only (no FTDI/JTAG adapter)
- PCIe: Only RP1 south bridge visible — NeTV2 FPGA not currently enumerating on PCIe bus
- No USB serial devices present

**rpi3-netv2**: SSH authentication denied — OS details not confirmed.

### PMOD HAT Hosts (separate network)

Additional PMOD-related RPi hosts were discovered in known_hosts (on a separate `iot.welland.mithis.com` network):

| Host | RPi Model | Notes |
|------|-----------|-------|
| rpi5-pmod.iot.welland.mithis.com | RPi 5 | PMOD HAT host (details TBD) |
| rpi4-pmod.iot.welland.mithis.com | RPi 4 | PMOD HAT host (details TBD) |

These may be additional test infrastructure or development machines. SSH connectivity not yet verified.

## Programming Methods

### openFPGALoader (via USB FTDI)

Used for: **Arty A7** boards (via FTDI FT2232 USB on each RPi)

openFPGALoader programs the Arty through the FTDI FT2232's JTAG interface (ttyUSB0/if00):

```bash
# Volatile load (lost on power cycle)
openFPGALoader -b arty design.bit

# Persistent flash
openFPGALoader -b arty --write-flash design.bit
```

Source: [openFPGALoader](https://github.com/trabucayre/openFPGALoader)

### OpenOCD (GPIO Bitbang JTAG)

Used for: **NeTV2** (both RPi3 and RPi5 hosts)

OpenOCD drives JTAG signals through the Raspberry Pi GPIO header using the `bcm2835gpio` interface. The configuration file `alphamax-rpi.cfg` defines the GPIO-to-JTAG mapping:

| JTAG Signal | RPi GPIO | RPi Header Pin | Direction |
|-------------|----------|----------------|-----------|
| TCK | GPIO4 | Pin 7 | Output |
| TMS | GPIO17 | Pin 11 | Output |
| TDI | GPIO27 | Pin 13 | Output |
| TDO | GPIO22 | Pin 15 | Input |
| SRST | GPIO24 | Pin 18 | Output |

Two programming modes:

1. **Direct bitstream load** (volatile):
   ```bash
   openocd -f alphamax-rpi.cfg -c "pld load 0 top.bit; exit"
   ```

2. **SPI Flash via BSCAN_SPI** (persistent):
   ```bash
   openocd -f alphamax-rpi.cfg -c "init; jtagspi_init 0 bscan_spi_xc7a35t.bit; jtagspi_program top.bin 0x0; exit"
   ```

Source: [alphamax-rpi.cfg](https://github.com/alphamaxmedia/netv2mvp-scripts/blob/master/alphamax-rpi.cfg)

### USB DFU (dfu-util)

Used for: **Fomu EVT** (on pi17)

The Fomu is in DFU bootloader mode (v2.0.4) and is programmed via USB:

```bash
dfu-util -D design.dfu
```

Source: [workshop.fomu.im](https://workshop.fomu.im)

### RP2040 USB (MicroPython)

Used for: **Tiny Tapeout** boards (TT06 on pi25, TT08 on pi23)

The TT boards use an RP2040 running MicroPython firmware. The FPGA bitstream is loaded through the RP2040 via `/dev/ttyACM0`.

Source: [TinyTapeout firmware](https://github.com/TinyTapeout/tt-micropython-firmware)

## Communication Interfaces

### USB-UART (FTDI FT2232)

Used for: **Arty A7** boards

The FTDI FT2232 provides two USB interfaces. Interface 1 (`-if01-port0`) is the UART:
- Serial device: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SN>-if01-port0` → `/dev/ttyUSB1`
- Baud rate: 115200 (LiteX default)
- FPGA pins: TX=D10, RX=A9

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

### GPIO UART

Used for: **NeTV2** (primary serial)

| Signal | FPGA Pin | RPi GPIO | RPi Header Pin |
|--------|----------|----------|----------------|
| FPGA TX | E14 | GPIO15 (RXD) | Pin 10 |
| FPGA RX | E13 | GPIO14 (TXD) | Pin 8 |

The RPi's `/dev/ttyAMA0` or `/dev/serial0` connects to the FPGA's serial port.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

### Secondary UART via PCIe "hax" Pins

Used for: **NeTV2** (RPi5 only)

| Signal | FPGA Pin | PCIe Hax Pin |
|--------|----------|-------------|
| TX | B17 | hax7 |
| RX | A18 | hax8 |

### PCIe

Used for: **NeTV2** (RPi5 only)

The NeTV2 supports PCIe x1/x2/x4. On RPi5, it connects as PCIe Gen2 x1. The FPGA appears with vendor ID `10ee` (Xilinx) and device ID `7011`.

**Note**: As of 2026-03-09, the NeTV2 FPGA is not currently enumerating on the RPi5's PCIe bus (only the RP1 south bridge is visible in `lspci`).

### USB (Native)

Used for: **Fomu EVT** (ValentyUSB on pi17), **Tiny Tapeout** (RP2040 on pi23/pi25)

### PMOD HAT

Used for: **Arty A7** boards (RPi 4B hosts have PMOD HATs installed)

The PMOD HAT provides 3 PMOD ports (JA, JB, JC) connecting RPi GPIO pins to standard 12-pin PMOD connectors. See [pmod-hat.md](pmod-hat.md) for the full pin mapping.

## Test Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│ 1. BOOT                                                      │
│    RPi PXE-boots from tweed (TFTP)                           │
│                                                              │
│ 2. PROGRAM FPGA                                              │
│    - openFPGALoader (Arty): -b arty design.bit               │
│    - dfu-util (Fomu): -D design.dfu                          │
│    - OpenOCD (NeTV2): pld load 0 top.bit                     │
│    - RP2040/MicroPython (TT): via /dev/ttyACM0               │
│                                                              │
│ 3. RUN TEST HARNESS                                          │
│    - Open serial port (ttyUSB1/ttyAMA0/ttyACM0)             │
│    - Send test commands to FPGA                              │
│    - Read responses and validate                             │
│                                                              │
│ 4. COLLECT RESULTS                                           │
│    - Parse UART output for PASS/FAIL                         │
│    - Check PCIe enumeration (NeTV2)                          │
│    - Verify PMOD loopback signals (Arty)                     │
│    - Report results                                          │
└──────────────────────────────────────────────────────────────┘
```

## Known Issues

- **pi11** (port 11): Arty A7 FTDI USB disconnected — board cannot be programmed or tested.
- **pi7** (port 7): PoE fault — RPi is offline.
- **rpi5-netv2**: NeTV2 FPGA not currently visible on PCIe bus (may need bitstream loaded first).
- **rpi3-netv2**: SSH authentication denied — cannot verify hardware state.
- **rpi5-pmod / rpi4-pmod**: Discovered in known_hosts but not yet explored.
