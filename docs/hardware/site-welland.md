# Site: Welland, Australia

[welland.fpgas.online](https://welland.fpgas.online) — fpgas.online site at Welland, South Australia. This document describes the physical host machines, FPGA boards, programming methods, and communication interfaces at this site.

## Network Topology

```
                          ┌────────────────────────────────────┐
                          │  tweed.welland.mithis.com          │
Internet ─── eth-uplink ──│  Debian 13 (trixie)                │
 (10.99.21.2, via ten64)  │  x86_64, kernel 6.12.105           │
                          │  Intel Core i5-3610ME              │
                          │                                    │
                          │  dnsmasq (DHCP/DNS/TFTP/PXE)       │
              eth-local ──│  10.21.0.1/16, one VLAN per port   │
        (GSM7252PS "sw1"  │  domain: fpgas.welland.mithis.com  │
         + S3300 "sw2")   └───────────┬────────────────────────┘
                                      │
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        │              │              │              │              │
  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐
  │ RPi 4/3B+ │  │ RPi 3B+   │  │ RPi 5     │  │ RPi 4/3B+ │  │ RPi 4     │
  │ +Arty A7  │  │ +NeTV2    │  │ +M.2 HAT  │  │ +TT ASIC  │  │ +TT FPGA  │
  │ +PMOD HAT │  │ (GPIO     │  │ +Acorn    │  │ demo board│  │ Demo Board│
  │ +USB Eth  │  │  JTAG)    │  │  CLE-215+ │  │ +PMOD HAT │  │ +PMOD HAT │
  └───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
   (sw2 p38 +…)   (sw1 ×4)      (sw2 ×6)       (sw2 p3–p8)     (sw2 p33–36)
                                            + Fomu EVT on sw1 p17
```

All Raspberry Pis netboot via PXE/TFTP from tweed. Since **2026-08-23** the
site runs the **VLAN-per-port** scheme (fpgas.online-infra PR #10): every
Pi-facing switch port is an untagged access port in its own VLAN, tweed
isolates Pi↔Pi traffic with nftables, and a Pi's identity is derived from the
port it is plugged into, not from its MAC:

| Switch (index)                    | Mgmt IP    | Role                                                       |
|-----------------------------------|------------|------------------------------------------------------------|
| Netgear GSM7252PS-s2 (**sw1**)    | 10.1.5.23  | Head switch: tweed eth-local on 1/0/47, eth-uplink on 1/0/48 |
| Netgear S3300-52X-PoE+ (**sw2**)  | 10.1.5.11  | Downstream via GSM 1/0/50 ↔ S3300 1/xg51; carries the TT and Acorn boards |

Switch `s`, port `p` → VLAN `2000 + 100·s + p`, IPv4 `10.21.s.p`, IPv6
`2404:e80:a137:210s::p`, hostname `pi-sw<s>-p<p>`. Gateway 10.21.0.1. Moving a
Pi to another port renames and re-addresses it. The old flat `piNN` /
`10.21.0.1NN` names in earlier revisions of this page (and in
`site-welland-pibs.conf`) are retired; the "Old name" columns below map them.
On the S3300, Tim's rule is **port N carries Tiny Tapeout N** (ports 1–10), the
TT FPGA emulation boards sit on 33–36, and the Acorn Pi 5s on 29 and 43–48.

Source: `ansible/inventory/host_vars/fpgas.online.yml` in fpgas.online-infra
(the `switches:` block and the `tt_boards` catalogue), the switches' LLDP
tables, and live probes of every host below on 2026-09-03.

## Gateway: tweed.welland.mithis.com

| Property   | Value                                                                                |
| ---------- | ------------------------------------------------------------------------------------ |
| Role       | Network gateway, DHCP/DNS/TFTP/PXE server, NFS root server, web tier (welland.fpgas.online + tinytapeout.fpgas.online) |
| Hardware   | Intel Core i5-3610ME (3rd Gen, QM77 chipset)                                         |
| OS         | Debian 13 (trixie) — fresh install 2026-08-30                                        |
| Kernel     | 6.12.105+deb13-amd64                                                                 |
| eth-uplink | 10.99.21.2/30 + 2404:e80:a137:9921::2/126, point-to-point to ten64 (10.99.21.1), which publishes tweed's web names |
| eth-local  | 10.21.0.1/16 trunk to the switches (per-port VLAN sub-interfaces)                    |
| Domain     | fpgas.welland.mithis.com                                                             |
| PCI        | 2× Intel 82574L GbE, Tundra PCI bridge, Matrox G200eW                                |
| NFS roots  | `/srv/nfs/rpi/bookworm/{boot,root}` (armhf + arm64 kernels, `overlayroot=tmpfs`); apt packages `fpgas-online-tt` 0.0.post52, `fpgas-online-tt-demos` 0.0.post21, `fpgas-online-cam` 0.0.post43, `openfpgaloader` 0.10.0 |
| SSH access | from ten64: `ssh -i ~/.ssh/fpgas.online-ansible -o IdentitiesOnly=yes -o IdentityAgent=none ansible@10.99.21.2` (the automation key; verified 2026-09-03) |

Tweed does **not** host any FPGA boards directly. It serves as the network gateway and PXE boot server for the RPi fleet. The RPis are on the `eth-local` (10.21.0.0/16) network.

**SSH to RPis**: the Pis are not routable from outside tweed (per-port VLANs;
they do not even answer pings from ten64). Jump through tweed as the `ansible`
user with `ProxyCommand`, then `pi@10.21.<switch>.<port>` (the shared Pi
password is printed in the ssh banner and is public by design):

```bash
ssh -o ProxyCommand='ssh -i ~/.ssh/fpgas.online-ansible -o IdentityAgent=none -W %h:%p ansible@10.99.21.2' \
    pi@10.21.2.29
```

The old restricted `pi@tweed.welland.mithis.com` jump account (rbash) did not
survive the 2026-08-30 reinstall of tweed. For a scripted example see the
probe used for this page's 2026-09-03 refresh (`tmp/probe.py` in the PR that
made it) or the `sh()` helpers in the repo's host scripts.

**Public access** (for end users): `ssh pi@fpgas.mithis.com -p 13422` provides port-forwarded access to individual RPis. See [Getting Started](https://github.com/CarlFK/pici/wiki/Getting-Started).

## FPGA Board Inventory

The **Acorn**, **Tiny Tapeout ASIC** and **Tiny Tapeout FPGA** sections were
re-verified live on 2026-09-03 under the VLAN-per-port scheme. The Arty A7,
NeTV2 and Fomu sections below still carry the pre-2026-08-23 names and
`10.21.0.1xx` addresses from the 2026-03-17 survey; the 2026-08-30 hardware
inventory sheet places those Pis at sw1 p10/p12/p14/p16 (NeTV2, same MACs as
pi10/pi12/pi14/pi16), sw1 p17 (Fomu + OpenVizsla, was pi17) and sw2 p38 (Arty
`210319B3E5C5`, was pi11), but they have not been re-probed for this page.

### Infrastructure Host

| Host | Switch Port | IP          | RPi MAC           | RPi Model   | Role                                         |
| ---- | ----------- | ----------- | ----------------- | ----------- | -------------------------------------------- |
| pi1  | port 1      | 10.21.0.101 | b8:27:eb:ec:c2:c9 | RPi 3B+ 1GB | Always-on NFS maintenance system (RW access) |

### Arty A7-35T Boards (×5, on RPi 4/3B+ hosts with PMOD HATs)

| Host | Switch Port | IP          | RPi MAC           | RPi Model   | Arty Serial         | Arty DNA           | USB Ethernet                     | Serial Devices   |
| ---- | ----------- | ----------- | ----------------- | ----------- | ------------------- | ------------------ | -------------------------------- | ---------------- |
| [pi7](https://welland.fpgas.online/fpgas/pi7.html)   | port 7      | 10.21.0.107 | e4:5f:01:96:f8:a5 | RPi 4 2GB   | 210319B301DE        | 0x00628502251ea85c | ASIX AX88179 (f8:e4:3b:0f:c1:e6) | ttyUSB0, ttyUSB1 |
| pi9  | port 9      | 10.21.0.109 | b8:27:eb:86:39:63 | RPi 3B+ 1GB | (FTDI disconnected) | —                  | Apple Eth (48:d7:05:e9:40:52)    | **none**         |
| [pi11](https://welland.fpgas.online/fpgas/pi11.html) | port 11     | 10.21.0.111 | e4:5f:01:8d:f7:17 | RPi 4 8GB   | 210319B3E5C5        | 0x002c8d02251ea854 | DM9601 (00:e0:4c:53:44:58)       | ttyUSB0, ttyUSB1 |
| [pi13](https://welland.fpgas.online/fpgas/pi13.html) | port 13     | 10.21.0.113 | b8:27:eb:6d:27:f6 | RPi 3B+ 1GB | 210319A43ADB        | 0x0002f54832290854 | ASIX (8a:ce:4c:ff:ae:83)         | ttyUSB0, ttyUSB1 |
| [pi26](https://welland.fpgas.online/fpgas/pi26.html) | port 26     | 10.21.0.126 | e4:5f:01:97:1f:7e | RPi 4 2GB   | 210319B0C238        | 0x0144cd2a47442854 | Linksys GbE (60:38:e0:e3:56:4f)  | ttyUSB0, ttyUSB1 |

Each working Arty A7 connects via FTDI FT2232C/D/H (USB VID:PID `0403:6010`, labelled "Digilent USB Device"). The FT2232 provides two interfaces:
- **if00** → `/dev/ttyUSB0` — JTAG (used by openFPGALoader)
- **if01** → `/dev/ttyUSB1` — UART serial console (115200 baud)

The serial device path is: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SERIAL>-if01-port0`

Each RPi also has a separate USB Ethernet adapter connected to the Arty's Ethernet port for network testing.

**pi9 note**: FTDI is disconnected — no USB serial devices present. This board cannot be programmed or tested until the USB connection is restored.

Source: `lsusb` and `ls /dev/serial/by-id/` output from each RPi, dnsmasq pibs.conf.

### NeTV2 Boards (×5, on RPi 3B+ hosts with GPIO JTAG)

| Host | Switch Port | IP          | RPi MAC           | RPi Model   | FPGA    | FPGA DNA           |
| ---- | ----------- | ----------- | ----------------- | ----------- | ------- | ------------------ |
| pi10 | port 10     | 10.21.0.110 | b8:27:eb:e3:e7:e4 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662251c6f |
| pi12 | port 12     | 10.21.0.112 | b8:27:eb:eb:5d:bf | RPi 3B+ 1GB | XC7A35T | 0x3a11a4c662372a6b |
| pi14 | port 14     | 10.21.0.114 | b8:27:eb:e3:7c:3c | RPi 3B+ 1GB | XC7A35T | 0x3a11dcc864222e93 |
| pi16 | port 16     | 10.21.0.116 | b8:27:eb:c6:29:79 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662372a53 |
| pi18 | port 18     | 10.21.0.118 | b8:27:eb:2c:e8:de | RPi 3B+ 1GB | XC7A35T | 0x3a11dcc864241c0b |


Each NeTV2 is programmed via OpenOCD GPIO bitbang JTAG through the RPi's GPIO header. No USB serial devices — the NeTV2 uses GPIO UART for communication (FPGA TX→GPIO15/RXD, FPGA RX→GPIO14/TXD via `/dev/ttyAMA0`).

Source: dnsmasq pibs.conf, `lsusb` on pi10.

### Sqrl Acorn CLE-215+ (×6 deployed, on RPi 5 hosts with M.2 HAT)

| Host       | Switch Port | IP         | RPi MAC           | RPi Model (rev)          | PCIe Device at `0001:01:00.0`                          | JTAG          | P2 serial            | Old name |
| ---------- | ----------- | ---------- | ----------------- | ------------------------ | ------------------------------------------------------ | ------------- | -------------------- | -------- |
| pi-sw2-p29 | sw2 p29     | 10.21.2.29 | 88:a2:9e:45:dd:be | RPi 5 Rev 1.1 2 GB (b04171) | Squirrels Research Labs Acorn CLE-215+ `1e24:021f` | OK            | OK (J5 wire dead)    | pi4      |
| pi-sw2-p43 | sw2 p43     | 10.21.2.43 | 98:fe:54:13:e0:75 | RPi 5 Rev 1.1 1 GB (a04171) | Squirrels Research Labs Acorn CLE-215+ `1e24:021f` | empty chain   | untestable           | —        |
| pi-sw2-p44 | sw2 p44     | 10.21.2.44 | 98:fe:54:13:e0:f5 | RPi 5 Rev 1.1 1 GB (a04171) | Xilinx 7-Series FPGA Hard PCIe block `10ee:7011`   | empty chain   | untestable           | —        |
| pi-sw2-p46 | sw2 p46     | 10.21.2.46 | 88:a2:9e:45:85:77 | RPi 5 Rev 1.1 2 GB (b04171) | Squirrels Research Labs Acorn CLE-215+ `1e24:021f` | OK            | OK                   | pi6      |
| pi-sw2-p47 | sw2 p47     | 10.21.2.47 | 98:fe:54:13:f5:75 | RPi 5 Rev 1.1 1 GB (a04171) | Squirrels Research Labs Acorn CLE-215+ `1e24:021f` | OK            | reversed (K2↔J2)     | —        |
| pi-sw2-p48 | sw2 p48     | 10.21.2.48 | 88:a2:9e:45:c6:87 | RPi 5 Rev 1.1 2 GB (b04171) | Squirrels Research Labs Acorn CLE-215+ `1e24:021f` | OK            | OK                   | pi2      |

The Sqrl Acorn CLE-215+ is an M.2 PCIe FPGA accelerator card containing a
Xilinx Artix-7 XC7A200T FPGA (215K logic cells). It connects to the RPi 5 via
an M.2 HAT and enumerates at `0001:01:00.0` alongside the RPi 5's RP1 south
bridge on `0002:01:00.0`. Five boards still boot the Sqrl factory (mining)
firmware; pi-sw2-p44 boots a LiteX/Vivado design. Every host also has an
ov5647 camera and publishes a feed.

No USB serial devices — **JTAG and UART go over the 40-pin header** (P1 → SPI0
pins for openFPGALoader bit-bang, P2 → GPIO14/15 with a null-modem crossover)
and PCIe over the M.2 slot; see [acorn-pinmap.md](acorn-pinmap.md). All six
have `/dev/ttyAMA0` enabled (`[pi5] dtoverlay=uart0-pi5`, infra PR #32), the
kernel console on `ttyAMA10`, `serial-getty@ttyAMA0` inactive, and
openFPGALoader 0.10.0 (which needs the `gpiochip15 → gpiochip0` symlink on a
Pi 5). **Detach the PCIe endpoint before any JTAG load** or the Pi crashes.
p43/p44 need a physical check of their P1 cable; p47's P2 connector is
reversed; p29's J5 wire is open. Device DNA is not readable until openFPGALoader
is upgraded (infra PR #48). A wedged Pi 5 draws ~0.4 W on PoE instead of ~8 W
and needs a PoE cycle (> 90 s to return).

Source: live probe of all six hosts 2026-09-03 (`/proc/device-tree/model`,
`/proc/cpuinfo`, `lspci -nn`, `/proc/cmdline`, `openFPGALoader --Version`);
JTAG/P2 columns from the 2026-08-31 pin-ID survey.

### Fomu EVT (×2, on RPi 3B+ hosts)

| Host | Switch Port | IP          | RPi MAC           | RPi Model   | Fomu USB VID:PID | DFU Version | USB Analyzer             |
| ---- | ----------- | ----------- | ----------------- | ----------- | ---------------- | ----------- | ------------------------ |
| [pi17](https://welland.fpgas.online/fpgas/pi17.html) | port 17     | 10.21.0.117 | b8:27:eb:47:9f:d1 | RPi 3B+ 1GB | 1209:5bf0        | v2.0.4      | OpenVizsla (1d50:607c)   |
| [pi21](https://welland.fpgas.online/fpgas/pi21.html) | port 21     | 10.21.0.121 | b8:27:eb:fc:4d:f8 | RPi 3B+ 1GB | 1209:5bf0        | v2.0.4      | Cythion/LUNA (16d0:05a5) |

Each Fomu EVT appears as "Generic Fomu EVT running DFU Bootloader v2.0.4". No serial devices — the Fomu uses native USB (ValentyUSB) for communication.

Each host also has a USB protocol analyzer connected for sniffing/analyzing the Fomu's USB traffic:
- **pi17**: OpenVizsla USB sniffer/analyzer (VID:PID `1d50:607c`)
- **pi21**: Cythion/LUNA USB analyzer (VID:PID `16d0:05a5`)

Source: `lsusb` output from pi17, dnsmasq pibs.conf.

### Tiny Tapeout ASIC Boards (×6, on S3300 ports 3–8, RPi 4 / 3B+ hosts with PMOD HATs)

These boards contain **real fabricated TT ASIC silicon** on a TT demo board
(RP2040, MicroPython TT SDK). They are the public boards on
[tinytapeout.fpgas.online](https://tinytapeout.fpgas.online) (live since
2026-08-23): S3300 port N carries TTN, the board page is
`https://tinytapeout.fpgas.online/board/<slug>/` and its `status.json` is the
liveness check.

| Host      | Slug     | Switch Port | IP        | RPi MAC           | RPi Model (rev)               | Chip / firmware                          | RP2040 serial      | Old name |
| --------- | -------- | ----------- | --------- | ----------------- | ----------------------------- | ---------------------------------------- | ------------------ | -------- |
| pi-sw2-p3 | [tt03p5](https://tinytapeout.fpgas.online/board/tt03p5/) | sw2 p3 | 10.21.2.3 | 98:fe:54:1b:7f:de | RPi 4 2 GB Rev 1.5 (b03115) | TT03p5 (sky130), demo-board fw **1.2.2** (last release supporting tt03p5) | de636c65c34d6a25 | — |
| pi-sw2-p4 | [tt04](https://tinytapeout.fpgas.online/board/tt04/)     | sw2 p4 | 10.21.2.4 | 98:fe:54:1b:7f:57 | RPi 4 2 GB Rev 1.5 (b03115) | TT04, TT SDK 2.0.4                        | de637061074b1838 | — |
| pi-sw2-p5 | [tt05](https://tinytapeout.fpgas.online/board/tt05/)     | sw2 p5 | 10.21.2.5 | 98:fe:54:1b:80:11 | RPi 4 2 GB Rev 1.5 (b03115) | TT05, TT SDK 2.0.4                        | de637061071e5439 | — |
| pi-sw2-p6 | [tt06](https://tinytapeout.fpgas.online/board/tt06/)     | sw2 p6 | 10.21.2.6 | b8:27:eb:71:78:cc | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT06, TT SDK 2.0.4                      | de640cb1d3357125 | pi23 |
| pi-sw2-p7 | [tt07](https://tinytapeout.fpgas.online/board/tt07/)     | sw2 p7 | 10.21.2.7 | b8:27:eb:19:43:cd | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT07, TT SDK 2.0.4                      | de641070db746f27 | pi19 |
| pi-sw2-p8 | [tt08](https://tinytapeout.fpgas.online/board/tt08/)     | sw2 p8 | 10.21.2.8 | b8:27:eb:44:46:e9 | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT08, TT SDK 2.0.4                      | de641070db5b2d27 | pi25 |

Ports 9 and 10 (tt09, tt10) are reserved in the catalogue but have no Pi yet.
The TT ASIC boards appear as "MicroPython Board in FS mode" (RP2040, VID:PID
`2e8a:0005`) at `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_<serial>-if00`,
with a udev symlink `/dev/ttboard → ttyACM0`. Every host runs the `fpgas-tt`
daemon (0.1.0), which **owns the serial port** and exposes it as a WebSocket
bridge on port 8765 for the web Commander; stop it before using `mpremote`.
Every host also has a Digilent Pmod HAT and an ov5647 camera.

Firmware notes (2026-08-23/24): tt04/tt05/tt07 were reflashed to TT SDK 2.0.4
(the last RP2040 build; 3.x is RP2350-only), tt06/tt08 already had it. The
tt03p5 chip is not supported by SDK ≥ 2.0, so that board runs demo-board
firmware 1.2.2 with a hand-pushed `/shuttles/tt03p5.json` and
`rom_fallback.txt` (TT03p5 has no chip ROM); the web Commander needs the
upstream `legacy` branch port (fpgas-online/tt-commander-app#9/#10) to drive
it, so its page is camera-first for now. The RP2 bootloader's mass-storage
path stalls on Pi 3B+ hosts (dwc_otg resets every ~35 s) — flash from those
with PICOBOOT, and run flashes detached (`setsid nohup … &`).

Source: live probe 2026-09-03 (`lsusb`, `/dev/serial/by-id`, `fuser
/dev/ttyACM0`, daemon `/health`); firmware versions from the 2026-08-23
reflash session; catalogue = `tt_boards` in infra `host_vars/fpgas.online.yml`.

### Tiny Tapeout FPGA Demo Boards (×4, on S3300 ports 33–36, RPi 4 hosts with PMOD HATs)

These boards contain an **iCE40UP5K FPGA** (FabricFox breakout) that emulates
Tiny Tapeout designs, on a TT demo board **v3 (RP2350B)** running TT SDK
**3.1.0** (reflashed 2026-08-23). They are **not** ASIC boards. Public as
`fpga-1` … `fpga-4` on tinytapeout.fpgas.online since 2026-08-24, where users
can run bundled demos or upload their own bitstream.

| Host       | Slug   | Switch Port | IP         | RPi MAC           | RPi Model (rev)              | USB VID:PID | RP2350 Serial    | Old name |
| ---------- | ------ | ----------- | ---------- | ----------------- | ---------------------------- | ----------- | ---------------- | -------- |
| pi-sw2-p33 | [fpga-1](https://tinytapeout.fpgas.online/board/fpga-1/) | sw2 p33 | 10.21.2.33 | e4:5f:01:97:0e:77 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | 4df39a7a6856f86f | pi27 |
| pi-sw2-p34 | [fpga-2](https://tinytapeout.fpgas.online/board/fpga-2/) | sw2 p34 | 10.21.2.34 | e4:5f:01:97:27:f2 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | fd1a167bd863a198 | pi29 |
| pi-sw2-p35 | [fpga-3](https://tinytapeout.fpgas.online/board/fpga-3/) | sw2 p35 | 10.21.2.35 | e4:5f:01:97:0c:e3 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | 8c46329b33590ecb | pi31 |
| pi-sw2-p36 | [fpga-4](https://tinytapeout.fpgas.online/board/fpga-4/) | sw2 p36 | 10.21.2.36 | e4:5f:01:8e:02:27 | RPi 4 8 GB Rev 1.5 (d03115) | 2e8a:0005 | a2961e5cac65b25f | pi33 |

Like the ASIC boards, these appear as "MicroPython Board in FS mode" (VID:PID
`2e8a:0005`) with the `/dev/ttboard` symlink, and the `fpgas-tt` daemon owns
the port. See [tt-fpga.md](tt-fpga.md) for the firmware history and the
consequences for this repo's `mpremote`-based tooling.

Source: live probe 2026-09-03 (`lsusb`, `/dev/serial/by-id`, daemon `/health`).

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

| Host                             | RPi Model | Notes             |
| -------------------------------- | --------- | ----------------- |
| rpi5-pmod.iot.welland.mithis.com | RPi 5     | PMOD HAT dev host |
| rpi4-pmod.iot.welland.mithis.com | RPi 4     | PMOD HAT dev host |

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

**Sqrl Acorn CLE-215+** (via RPi 5 GPIO bitbang JTAG):

```bash
echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # detach the endpoint or the Pi 5 crashes
sudo ln -sfn /dev/gpiochip15 /dev/gpiochip0                   # openFPGALoader 0.10.0 opens gpiochip0
openFPGALoader --cable libgpiod --pins 10:9:11:8 design.bit   # TDI:TDO:TCK:TMS, ~16 s, SRAM only
```

PCIe-based flash programming (`litepcie_util`) needs a LiteX design already in
flash, which only pi-sw2-p44 has; see
[acorn-pcie-programming.md](acorn-pcie-programming.md).

**Fomu EVT** (via USB DFU):

The Fomu is currently in DFU bootloader mode (v2.0.4) and can be programmed via `dfu-util -D design.dfu` as a fallback. openFPGALoader also supports DFU-based programming.

Source: [openFPGALoader](https://github.com/trabucayre/openFPGALoader), [workshop.fomu.im](https://workshop.fomu.im), [alphamax-rpi.cfg](https://github.com/alphamaxmedia/netv2mvp-scripts/blob/master/alphamax-rpi.cfg)

### RP2040 USB (MicroPython)

Used for: **Tiny Tapeout ASIC boards** (tt03p5–tt08 on pi-sw2-p3…p8) and **Tiny Tapeout FPGA Demo Boards** (fpga-1…fpga-4 on pi-sw2-p33…p36)

Both TT ASIC and FPGA Demo Boards use an RP2040 (v2 demo board) or RP2350B (v3) running the MicroPython TT SDK. The microcontroller presents a serial console on `/dev/ttyACM0` (`/dev/ttboard`), which the `fpgas-tt` daemon holds open and republishes as a WebSocket for the web Commander. On FPGA Demo Boards the RP2350 also loads bitstreams to the iCE40 FPGA, driven through the daemon's `/designs` and `/bitstream` endpoints.

Source: [TinyTapeout firmware](https://github.com/TinyTapeout/tt-micropython-firmware), [fpgas.online-tt](https://github.com/fpgas-online/fpgas.online-tt)

## Communication Interfaces

### USB-UART (FTDI FT2232)

Used for: **Arty A7** boards

The FTDI FT2232 provides two USB interfaces. Interface 1 (`-if01-port0`) is the UART:
- Serial device: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SN>-if01-port0` → `/dev/ttyUSB1`
- Baud rate: 115200 (LiteX default)
- FPGA pins: TX=D10, RX=A9

Source: [digilent_arty.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py)

### GPIO UART

Used for: **NeTV2** (primary serial), **Acorn CLE-215+** (P2 connector)

| Board | Signal  | FPGA Pin | RPi GPIO     | RPi Header Pin |
| ----- | ------- | -------- | ------------ | -------------- |
| NeTV2 | FPGA TX | E14      | GPIO15 (RXD) | Pin 10         |
| NeTV2 | FPGA RX | E13      | GPIO14 (TXD) | Pin 8          |
| Acorn | FPGA TX | K2       | GPIO15 (RXD) | Pin 10         |
| Acorn | FPGA RX | J2       | GPIO14 (TXD) | Pin 8          |

The RPi's `/dev/ttyAMA0` or `/dev/serial0` connects to the FPGA's serial port. On the Pi 5 Acorn hosts `/dev/ttyAMA0` only exists because the NFS root's `config.txt` carries `[pi5] dtoverlay=uart0-pi5`, and the kernel console is kept off it (`console=ttyAMA10`) so FPGA output cannot trigger SysRq.

Source: [kosagi_netv2.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py), [acorn-pinmap.md](acorn-pinmap.md)

### Secondary UART via PCIe "hax" Pins

Used for: **NeTV2** (RPi5 only)

| Signal | FPGA Pin | PCIe Hax Pin |
| ------ | -------- | ------------ |
| TX     | B17      | hax7         |
| RX     | A18      | hax8         |

### PCIe

Used for: **Acorn CLE-215+** (all six RPi 5 hosts), **NeTV2** (RPi5 only)

The Acorn enumerates at `0001:01:00.0` as `1e24:021f` (Sqrl factory firmware) or `10ee:7011` (a LiteX design, pi-sw2-p44). Reconfiguring the FPGA over JTAG while the endpoint is enumerated is a surprise removal that crashes the Pi 5 — remove the device from the bus first and rescan afterwards ([acorn-pcie-programming.md](acorn-pcie-programming.md#detach-the-pcie-endpoint-before-any-jtag-reconfiguration)).

The NeTV2 supports PCIe x1/x2/x4. On RPi5, it connects as PCIe Gen2 x1. The FPGA appears with vendor ID `10ee` (Xilinx) and device ID `7011`.

**Note**: As of 2026-03-09, the NeTV2 FPGA is not currently enumerating on the RPi5's PCIe bus (only the RP1 south bridge is visible in `lspci`).

### USB (Native)

Used for: **Fomu EVT** (ValentyUSB on pi17/pi21), **Tiny Tapeout ASIC** (RP2040 on pi-sw2-p3…p8), **Tiny Tapeout FPGA Demo Board** (RP2350 on pi-sw2-p33…p36). USB analyzers (OpenVizsla on pi17, Cythion/LUNA on pi21) are also connected for Fomu USB traffic analysis.

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
│    - openFPGALoader (Acorn): RPi GPIO bitbang JTAG,          │
│      PCIe endpoint detached first                            │
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

### Disconnected Hosts

| Host | MAC               | IP          | Notes                                   |
| ---- | ----------------- | ----------- | --------------------------------------- |
| pi44 | dc:a6:32:b4:5e:c9 | 10.21.0.144 | Not connected (old MAC, may be reassigned) |

Source: `pibs.conf` on tweed.

## Known Issues

- **pi-sw2-p43 / pi-sw2-p44** (Acorn): `openFPGALoader --detect` finds an empty JTAG chain although PCIe enumerates — P1 cable/wiring needs a physical check. Until then nothing can be loaded on them.
- **pi-sw2-p47** (Acorn): P2 connector reversed (K2↔J2 and J5↔H5) — transpose both pairs, not a 180° re-seat.
- **pi-sw2-p29** (Acorn): J5 (spare GPIO 0) wire is open; serial pair fine.
- **All Acorn hosts**: openFPGALoader 0.10.0 cannot read Device DNA and needs the `gpiochip15` symlink on a Pi 5 (infra PR #48 upgrades it).
- **pi-sw2-p3** (tt03p5): the web Commander does not support demo-board firmware 1.2.x yet — camera-only until fpgas-online/tt-commander-app#10 lands.
- **Stale NFS handles after package upgrades in the shared NFS root**: on 2026-08-30 upgrading `fpgas-online-cam` under running Pis left them with `ESTALE` on the replaced files (cameras off air, 11 boards); on 2026-09-03 the TT hosts still show `dpkg-query … Stale file handle`. Only a reboot fixes it — expect it after any NFS-root package update.
- **Legacy entries from the 2026-03-17 survey** (not re-checked): pi9 Arty A7 FTDI disconnected; pi18 NeTV2 offline; pi21 Cythion/LUNA + Fomu offline. The former "pi19 TT ASIC (version unconfirmed)" is TT07, now pi-sw2-p7 and online.
- **rpi5-netv2**: NeTV2 FPGA not visible on PCIe bus — needs bitstream loaded first.
- **rpi3-netv2**: SSH access via `pi@rpi3-netv2.iot.welland.mithis.com`.
