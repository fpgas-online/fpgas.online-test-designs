# Infrastructure Overview

This document describes the physical host machines, FPGA boards, programming methods, and communication interfaces used in the fpgas.online test infrastructure.

## Network Topology

```
                          ┌────────────────────────────────────┐
                          │  tweed.welland.mithis.com          │
Internet ─── eth-uplink ──│  Debian 12 (bookworm)              │
 (10.99.21.2)             │  x86_64, kernel 6.1.0-34           │
                          │  Intel 3rd Gen Core                │
                          │                                    │
                          │  dnsmasq (DHCP/DNS/TFTP/PXE)       │
              eth-local ──│  10.21.0.1/16                      │
          (S3300 PoE sw.) │  domain: fpgas.welland.mithis.com  │
                          └───────────┬────────────────────────┘
                                      │
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        │              │              │              │              │
  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐
  │ RPi 4/3B+ │  │ RPi 3B+   │  │ RPi 5     │  │ RPi 3B+   │  │ RPi 4     │
  │ +Arty A7  │  │ +NeTV2    │  │ +mPCIe HAT│  │ +Fomu EVT │  │ +TT FPGA  │
  │ +PMOD HAT │  │ (GPIO     │  │ +Acorn    │  │ +USB Anlzr│  │ Demo Board│
  │ +USB Eth  │  │  JTAG)    │  │  CLE-215+ │  │ +TT ASIC  │  │ +PMOD HAT │
  └───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
      (×5)           (×5)        (×1+3 TBD)      (various)        (×4)
```

All Raspberry Pis netboot via PXE/TFTP from tweed. They connect to a Netgear S3300 PoE switch with numbered ports. IP addresses follow the convention `10.21.0.1XX` where `XX` is the switch port number.

Source: dnsmasq configuration on tweed (`/etc/dnsmasq.d/pibs.conf`), verified via SSH 2026-03-17.

## Gateway: tweed.welland.mithis.com

| Property   | Value                                                                                |
| ---------- | ------------------------------------------------------------------------------------ |
| Role       | Network gateway, DHCP/DNS/TFTP/PXE server                                            |
| Hardware   | Intel 3rd Gen Core (QM77 chipset)                                                    |
| OS         | Debian 12 (bookworm)                                                                 |
| Kernel     | 6.1.0-34-amd64                                                                       |
| eth-uplink | 10.99.21.2/30 (internet-facing)                                                      |
| eth-local  | 10.21.0.1/16 (RPi network)                                                           |
| Domain     | fpgas.welland.mithis.com                                                             |
| PCI        | 2× Intel 82574L GbE, Tundra PCI bridge, Matrox G200eW                                |
| SSH access | `ssh root@tweed.welland.mithis.com` (via WireGuard `wg-desktop`, route to 10.21.0.1) |

Tweed does **not** host any FPGA boards directly. It serves as the network gateway and PXE boot server for the RPi fleet. The RPis are on the `eth-local` (10.21.0.0/16) network.

**SSH to RPis**: Direct SSH from external machines requires WireGuard VPN (`wg-desktop` interface routes 10.21.0.0/16). Alternatively, use nested SSH through tweed: `ssh root@tweed.welland.mithis.com "ssh root@<rpi-ip> '<command>'"`. The RPis only accept root's SSH key from tweed itself.

## FPGA Board Inventory

All data verified via SSH on 2026-03-17 from live hardware and dnsmasq configuration (`/etc/dnsmasq.d/pibs.conf`) on tweed.

### Infrastructure Host

| Host | Switch Port | IP          | RPi Model   | Role                                         |
| ---- | ----------- | ----------- | ----------- | -------------------------------------------- |
| pi1  | port 1      | 10.21.0.101 | RPi 3B+ 1GB | Always-on NFS maintenance system (RW access) |

### Arty A7-35T Boards (×5, on RPi 4/3B+ hosts with PMOD HATs)

| Host | Switch Port | IP          | RPi Model   | Arty Serial         | Arty DNA           | USB Ethernet                     | Serial Devices   |
| ---- | ----------- | ----------- | ----------- | ------------------- | ------------------ | -------------------------------- | ---------------- |
| pi3  | port 3      | 10.21.0.103 | RPi 4 8GB   | 210319B3E5C5        | 0x002c8d02251ea854 | DM9601 (00:e0:4c:53:44:58)       | ttyUSB0, ttyUSB1 |
| pi5  | port 5      | 10.21.0.105 | RPi 4 2GB   | 210319B0C238        | 0x0144cd2a47442854 | Linksys GbE (60:38:e0:e3:56:4f)  | ttyUSB0, ttyUSB1 |
| pi9  | port 9      | 10.21.0.109 | RPi 4 2GB   | 210319B301DE        | 0x00628502251ea85c | ASIX AX88179 (f8:e4:3b:0f:c1:e6) | ttyUSB0, ttyUSB1 |
| pi11 | port 11     | 10.21.0.111 | RPi 3B+ 1GB | (FTDI disconnected) | —                  | Apple Eth (48:d7:05:e9:40:52)    | **none**         |
| pi13 | port 13     | 10.21.0.113 | RPi 3B+ 1GB | 210319A43ADB        | 0x0002f54832290854 | ASIX (8a:ce:4c:ff:ae:83)         | ttyUSB0, ttyUSB1 |

Each working Arty A7 connects via FTDI FT2232C/D/H (USB VID:PID `0403:6010`, labelled "Digilent USB Device"). The FT2232 provides two interfaces:
- **if00** → `/dev/ttyUSB0` — JTAG (used by openFPGALoader)
- **if01** → `/dev/ttyUSB1` — UART serial console (115200 baud)

The serial device path is: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SERIAL>-if01-port0`

Each RPi also has a separate USB Ethernet adapter connected to the Arty's Ethernet port for network testing.

**pi11 note**: FTDI is disconnected — no USB serial devices present. This board cannot be programmed or tested until the USB connection is restored.

Source: `lsusb` and `ls /dev/serial/by-id/` output from each RPi, dnsmasq pibs.conf.

### NeTV2 Boards (×5, on RPi 3B+ hosts with GPIO JTAG)

| Host | Switch Port | IP          | RPi Model   | FPGA    | FPGA DNA           |
| ---- | ----------- | ----------- | ----------- | ------- | ------------------ |
| pi10 | port 10     | 10.21.0.110 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662251c6f |
| pi12 | port 12     | 10.21.0.112 | RPi 3B+ 1GB | XC7A35T | 0x3a11a4c662372a6b |
| pi14 | port 14     | 10.21.0.114 | RPi 3B+ 1GB | XC7A35T | 0x3a11dcc864222e93 |
| pi16 | port 16     | 10.21.0.116 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662372a53 |
| pi18 | port 18     | 10.21.0.118 | RPi 3B+ 1GB | XC7A35T | 0x3a11dcc864241c0b |

Each NeTV2 is programmed via OpenOCD GPIO bitbang JTAG through the RPi's GPIO header. No USB serial devices — the NeTV2 uses GPIO UART for communication (FPGA TX→GPIO15/RXD, FPGA RX→GPIO14/TXD via `/dev/ttyAMA0`).

Source: dnsmasq pibs.conf, `lsusb` on pi10.

### Sqrl Acorn CLE-215+ (×1 active + 3 pending, on RPi 5 hosts with mPCIe HAT)

| Host | Switch Port | IP          | RPi Model         | Status        | PCIe Device                                                                    |
| ---- | ----------- | ----------- | ----------------- | ------------- | ------------------------------------------------------------------------------ |
| pi2  | port 2      | 10.21.0.102 | RPi 5 8GB Rev 1.1 | **Active**    | `0001:01:00.0 Processing accelerators: Squirrels Research Labs Acorn CLE-215+` |
| pi4  | port 4      | 10.21.0.104 | RPi 5 8GB         | Acorn pending | —                                                                              |
| pi6  | port 6      | 10.21.0.106 | RPi 5 8GB         | Acorn pending | —                                                                              |
| pi8  | port 8      | 10.21.0.108 | RPi 5 8GB         | Acorn pending | —                                                                              |

The Sqrl Acorn CLE-215+ is a PCIe FPGA accelerator card containing a Xilinx Kintex UltraScale KU115 FPGA. It connects to the RPi 5 via an mPCIe HAT. On pi2, the Acorn is visible on PCIe bus `0001:01:00.0` alongside the RPi 5's RP1 south bridge on bus `0002:01:00.0`.

No USB serial devices — programming and communication is via PCIe.

Source: `lspci` and `lsusb` on pi2, dnsmasq pibs.conf.

### Fomu EVT (×2, on RPi 3B+ hosts)

| Host | Switch Port | IP          | RPi Model   | Fomu USB VID:PID | DFU Version | USB Analyzer             |
| ---- | ----------- | ----------- | ----------- | ---------------- | ----------- | ------------------------ |
| pi17 | port 17     | 10.21.0.117 | RPi 3B+ 1GB | 1209:5bf0        | v2.0.4      | OpenVizsla (1d50:607c)   |
| pi21 | port 21     | 10.21.0.121 | RPi 3B+ 1GB | 1209:5bf0        | v2.0.4      | Cythion/LUNA (16d0:05a5) |

Each Fomu EVT appears as "Generic Fomu EVT running DFU Bootloader v2.0.4". No serial devices — the Fomu uses native USB (ValentyUSB) for communication.

Each host also has a USB protocol analyzer connected for sniffing/analyzing the Fomu's USB traffic:
- **pi17**: OpenVizsla USB sniffer/analyzer (VID:PID `1d50:607c`)
- **pi21**: Cythion/LUNA USB analyzer (VID:PID `16d0:05a5`)

Source: `lsusb` output from pi17, dnsmasq pibs.conf.

### Tiny Tapeout ASIC Boards (×2–3, on RPi 3B+ hosts with PMOD HATs)

These boards contain **real fabricated TT ASIC silicon** on a carrier board with an RP2040 microcontroller running MicroPython firmware.

| Host | Switch Port | IP          | RPi Model   | Board | USB VID:PID | Serial Device |
| ---- | ----------- | ----------- | ----------- | ----- | ----------- | ------------- |
| pi23 | port 23     | 10.21.0.123 | RPi 3B+ 1GB | TT08  | 2e8a:0005   | /dev/ttyACM0  |
| pi25 | port 25     | 10.21.0.125 | RPi 3B+ 1GB | TT06  | 2e8a:0005   | /dev/ttyACM0  |
| pi19 | port 19     | 10.21.0.119 | RPi 3B+ 1GB | (TBD) | 2e8a:0005   | /dev/ttyACM0  |

The TT ASIC boards appear as "MicroPython Board in FS mode" (RP2040, VID:PID `2e8a:0005`). Each presents a serial console on `/dev/ttyACM0`.

Serial device paths:
- pi23 (TT08): `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_de641070db5b2d27-if00`
- pi25 (TT06): `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_de640cb1d3357125-if00`

Source: `lsusb` and `ls /dev/serial/by-id/` output from pi23, pi25. dnsmasq pibs.conf.

### Tiny Tapeout FPGA Demo Boards (×4, on RPi 4 hosts with PMOD HATs)

These boards contain an **iCE40 FPGA** that emulates Tiny Tapeout designs, paired with an RP2040 microcontroller running MicroPython firmware. They are **not** ASIC boards.

| Host | Switch Port | IP          | RPi Model         | USB VID:PID | Serial Device | RP2040 Serial    |
| ---- | ----------- | ----------- | ----------------- | ----------- | ------------- | ---------------- |
| pi27 | port 27     | 10.21.0.127 | RPi 4 2GB Rev 1.5 | 2e8a:0005   | /dev/ttyACM0  | 4df39a7a6856f86f |
| pi29 | port 29     | 10.21.0.129 | RPi 4 2GB Rev 1.5 | 2e8a:0005   | /dev/ttyACM0  | fd1a167bd863a198 |
| pi31 | port 31     | 10.21.0.131 | RPi 4 2GB Rev 1.5 | 2e8a:0005   | /dev/ttyACM0  | 8c46329b33590ecb |
| pi33 | port 33     | 10.21.0.133 | RPi 4 8GB Rev 1.5 | 2e8a:0005   | /dev/ttyACM0  | a2961e5cac65b25f |

Like the ASIC boards, these appear as "MicroPython Board in FS mode" (RP2040, VID:PID `2e8a:0005`). The serial device path is `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_<RP2040_SERIAL>-if00`.

Source: `lsusb` and `ls /dev/serial/by-id/` output from pi27, pi29, pi31, pi33 (verified 2026-03-17).

### NeTV2 Boards (separate network — development/debug hosts)

In addition to the 5 NeTV2 boards on the tweed network above, there are two NeTV2 development hosts on a **separate network** accessible via different hostnames:

| Host                              | IP (via DNS)    | RPi Model             | Board                  | Connections         | SSH                                                        |
| --------------------------------- | --------------- | --------------------- | ---------------------- | ------------------- | ---------------------------------------------------------- |
| rpi5-netv2.iot.welland.mithis.com | 10.1.90.210/211 | RPi 5 Model B Rev 1.0 | NeTV2 (bare developer) | GPIO + PCIe Gen2 x1 | `tim@rpi5-netv2.iot.welland.mithis.com` (via `wg-desktop`) |
| rpi3-netv2.iot.welland.mithis.com | 10.1.90.212/213 | RPi 3                 | NeTV2 (stock packaged) | GPIO only           | `pi@rpi3-netv2.iot.welland.mithis.com` (via `wg-desktop`)  |

**rpi5-netv2** details (verified via SSH 2026-03-09):
- OS: Debian 13 (Trixie), kernel 6.12.47+rpt-rpi-2712 aarch64
- Software: OpenOCD installed, no openFPGALoader, no LiteX
- USB: ASIX AX88179 Gigabit Ethernet adapter only (no FTDI/JTAG adapter)
- PCIe: Only RP1 south bridge visible — NeTV2 FPGA not currently enumerating on PCIe bus
- No USB serial devices present

**rpi3-netv2**: Accessible via `pi@rpi3-netv2.iot.welland.mithis.com`.

### PMOD HAT Hosts (separate network)

Additional PMOD-related RPi hosts on a separate `iot.welland.mithis.com` network:

| Host                             | RPi Model | Notes                       |
| -------------------------------- | --------- | --------------------------- |
| rpi5-pmod.iot.welland.mithis.com | RPi 5     | PMOD HAT host (details TBD) |
| rpi4-pmod.iot.welland.mithis.com | RPi 4     | PMOD HAT host (details TBD) |

These may be additional test infrastructure or development machines. SSH connectivity not yet verified.

## Programming Methods

### openFPGALoader

[openFPGALoader](https://github.com/trabucayre/openFPGALoader) is the primary JTAG programming tool used across almost all boards. It supports multiple JTAG transports and FPGA families. Where a device is not yet supported, support is being added upstream.

**Arty A7** (via USB FTDI FT2232):
```bash
# Volatile load (lost on power cycle)
openFPGALoader -b arty design.bit

# Persistent flash
openFPGALoader -b arty --write-flash design.bit
```

**NeTV2** (via RPi GPIO bitbang JTAG):

openFPGALoader can drive JTAG signals through the Raspberry Pi GPIO header. The GPIO-to-JTAG mapping (from the `alphamax-rpi.cfg` OpenOCD config) is:

| JTAG Signal | RPi GPIO | RPi Header Pin | Direction |
| ----------- | -------- | -------------- | --------- |
| TCK         | GPIO4    | Pin 7          | Output    |
| TMS         | GPIO17   | Pin 11         | Output    |
| TDI         | GPIO27   | Pin 13         | Output    |
| TDO         | GPIO22   | Pin 15         | Input     |
| SRST        | GPIO24   | Pin 18         | Output    |

**Sqrl Acorn CLE-215+** (via PCIe mPCIe HAT):

The Acorn CLE-215+ connects to the RPi 5 via an mPCIe HAT and appears as a PCIe device. openFPGALoader support for PCIe-based programming is being added.

**Fomu EVT** (via USB DFU):

The Fomu is currently in DFU bootloader mode (v2.0.4) and can be programmed via `dfu-util -D design.dfu` as a fallback. openFPGALoader also supports DFU-based programming.

Source: [openFPGALoader](https://github.com/trabucayre/openFPGALoader), [workshop.fomu.im](https://workshop.fomu.im), [alphamax-rpi.cfg](https://github.com/alphamaxmedia/netv2mvp-scripts/blob/master/alphamax-rpi.cfg)

### RP2040 USB (MicroPython)

Used for: **Tiny Tapeout ASIC boards** (TT08 on pi23, TT06 on pi25, pi19) and **Tiny Tapeout FPGA Demo Boards** (pi27, pi29, pi31, pi33)

Both TT ASIC and FPGA Demo Boards use an RP2040 running MicroPython firmware. The RP2040 presents a serial console on `/dev/ttyACM0`. On FPGA Demo Boards, the RP2040 also loads bitstreams to the iCE40 FPGA.

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

| Signal  | FPGA Pin | RPi GPIO     | RPi Header Pin |
| ------- | -------- | ------------ | -------------- |
| FPGA TX | E14      | GPIO15 (RXD) | Pin 10         |
| FPGA RX | E13      | GPIO14 (TXD) | Pin 8          |

The RPi's `/dev/ttyAMA0` or `/dev/serial0` connects to the FPGA's serial port.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py)

### Secondary UART via PCIe "hax" Pins

Used for: **NeTV2** (RPi5 only)

| Signal | FPGA Pin | PCIe Hax Pin |
| ------ | -------- | ------------ |
| TX     | B17      | hax7         |
| RX     | A18      | hax8         |

### PCIe

Used for: **NeTV2** (RPi5 only)

The NeTV2 supports PCIe x1/x2/x4. On RPi5, it connects as PCIe Gen2 x1. The FPGA appears with vendor ID `10ee` (Xilinx) and device ID `7011`.

**Note**: As of 2026-03-09, the NeTV2 FPGA is not currently enumerating on the RPi5's PCIe bus (only the RP1 south bridge is visible in `lspci`).

### USB (Native)

Used for: **Fomu EVT** (ValentyUSB on pi17/pi21), **Tiny Tapeout ASIC** (RP2040 on pi23/pi25/pi19), **Tiny Tapeout FPGA Demo Board** (RP2040 on pi27/pi29/pi31/pi33). USB analyzers (OpenVizsla on pi17, Cythion/LUNA on pi21) are also connected for Fomu USB traffic analysis.

### PMOD HAT

Used for: **Arty A7** boards (RPi 4B hosts have PMOD HATs installed)

The PMOD HAT provides 3 PMOD ports (JA, JB, JC) connecting RPi GPIO pins to standard 12-pin PMOD connectors. See [rpi-hat-pmod.md](rpi-hat-pmod.md) for the full pin mapping.

## Test Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│ 1. BOOT                                                      │
│    RPi PXE-boots from tweed (TFTP)                           │
│                                                              │
│ 2. PROGRAM FPGA                                              │
│    - openFPGALoader (Arty): USB FTDI JTAG                    │
│    - openFPGALoader (NeTV2): RPi GPIO bitbang JTAG           │
│    - openFPGALoader (Acorn): PCIe via mPCIe HAT              │
│    - openFPGALoader (Fomu): USB DFU                          │
│    - RP2040/MicroPython (TT ASIC + FPGA Demo): /dev/ttyACM0  │
│                                                              │
│ 3. RUN TEST HARNESS                                          │
│    - Open serial port (ttyUSB1/ttyAMA0/ttyACM0)              │
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
- **pi4, pi6, pi8** (ports 4, 6, 8): RPi 5s with mPCIe HATs installed but Sqrl Acorn cards not yet connected.
- **pi19** (port 19): Listed as "Pmod HAT, MicroPython" in dnsmasq — specific TT ASIC version not yet confirmed.
- **rpi5-netv2**: NeTV2 FPGA not currently visible on PCIe bus (may need bitstream loaded first).
- **rpi3-netv2**: Accessible via `pi@rpi3-netv2.iot.welland.mithis.com` (previously had auth issues — resolved by using `pi` user instead of `tim`).
- **rpi5-pmod / rpi4-pmod**: Discovered in known_hosts but not yet explored.
