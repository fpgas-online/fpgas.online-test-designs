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
  │ RPi 4     │  │ RPi 3B+   │  │ RPi 5     │  │ RPi 4/3B+ │  │ RPi 4     │
  │ +Arty A7  │  │ +NeTV2    │  │ +M.2 HAT  │  │ +TT ASIC  │  │ +TT FPGA  │
  │ +PMOD HAT │  │ (GPIO     │  │ +Acorn    │  │ demo board│  │ Demo Board│
  │ +USB Eth  │  │  JTAG)    │  │  CLE-215+ │  │ +PMOD HAT │  │ +PMOD HAT │
  └───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
   (sw2 ×4)       (sw1 ×5)      (sw2 ×7)       (sw2 p3–p8)     (sw2 p33–36)
                                            + Fomu EVT on sw1 p17
```

All Raspberry Pis netboot via PXE/TFTP from tweed. The site runs the
**VLAN-per-port** scheme: every
Pi-facing switch port is an untagged access port in its own VLAN, tweed
isolates Pi↔Pi traffic with nftables, and a Pi's identity is derived from the
port it is plugged into, not from its MAC:

| Switch (index)                    | Mgmt IP    | Role                                                       |
|-----------------------------------|------------|------------------------------------------------------------|
| Netgear GSM7252PS-s2 (**sw1**)    | 10.1.5.23  | Head switch: tweed eth-local on 1/0/47, eth-uplink on 1/0/48 |
| Netgear S3300-52X-PoE+ (**sw2**)  | 10.1.5.11  | Downstream via GSM 1/0/50 ↔ S3300 1/xg51; carries the TT and Acorn boards |

Switch `s`, port `p` → VLAN `2000 + 100·s + p`, IPv4 `10.21.s.p`, IPv6
`2404:e80:a137:210s::p`, hostname `pi-sw<s>-p<p>`. Gateway 10.21.0.1. Moving a
Pi to another port renames and re-addresses it.
On the S3300, Tim's rule is **port N carries Tiny Tapeout N** (ports 1–10), the
TT FPGA emulation boards sit on 33–36, and the Acorn Pi 5s on 29, 37 and 43–48.

Source: `ansible/inventory/host_vars/fpgas.online.yml` in fpgas.online-infra
(the `switches:` block and the `tt_boards` catalogue) and the switches' LLDP
tables.

## Gateway: tweed.welland.mithis.com

| Property   | Value                                                                                |
| ---------- | ------------------------------------------------------------------------------------ |
| Role       | Network gateway, DHCP/DNS/TFTP/PXE server, NFS root server, web tier (welland.fpgas.online + tinytapeout.fpgas.online) |
| Hardware   | Intel Core i5-3610ME (3rd Gen, QM77 chipset)                                         |
| OS         | Debian 13 (trixie)                                                                   |
| Kernel     | 6.12.105+deb13-amd64                                                                 |
| eth-uplink | 10.99.21.2/30 + 2404:e80:a137:9921::2/126, point-to-point to ten64 (10.99.21.1), which publishes tweed's web names |
| eth-local  | 10.21.0.1/16 trunk to the switches (per-port VLAN sub-interfaces)                    |
| Domain     | fpgas.welland.mithis.com                                                             |
| PCI        | 2× Intel 82574L GbE, Tundra PCI bridge, Matrox G200eW                                |
| NFS roots  | `/srv/nfs/rpi/bookworm/{boot,root}` (armhf + arm64 kernels, `overlayroot=tmpfs`); apt packages `fpgas-online-tt` 0.0.post52, `fpgas-online-tt-demos` 0.0.post21, `fpgas-online-cam` 0.0.post43 |
| SSH access | operators: `ssh tim@10.21.0.1` / `ssh carl@…` over WireGuard (infra `operators` role, passwordless sudo). Automation from ten64: `ssh -i ~/.ssh/fpgas.online-ansible -o IdentitiesOnly=yes -o IdentityAgent=none ansible@10.99.21.2`. Jump only: `pi@tweed.welland.mithis.com` (below) |

Tweed does **not** host any FPGA boards directly. It serves as the network gateway and PXE boot server for the RPi fleet. The RPis are on the `eth-local` (10.21.0.0/16) network.

**SSH to RPis**: the Pis are not routable from outside tweed (per-port VLANs;
they do not even answer pings from ten64). Jump through tweed's restricted
`pi` account with `ProxyJump`, then `pi@10.21.<switch>.<port>` (the shared Pi
password is printed in the ssh banner and is public by design; your own key
is what the Pi checks — the jump account only forwards):

```bash
ssh -o ProxyJump=pi@tweed.welland.mithis.com pi@10.21.2.29
```

The jump account is `/bin/rbash` with a PATH of only `ssh` and `ssh-keyscan`,
an sshd `ForceCommand` wrapper that refuses anything else, and no sudo. It is
fpgas.online-infra `roles/jump`, applied to every gateway.
Two DNS caveats (checked 2026-09-03): the name's SSHFP records do not match
tweed's host keys, and one of its two AAAA records
(`2404:e80:a137:9921::2`, the uplink /126) accepts TCP 22 but never answers,
so an IPv6 client may hang; over WireGuard the `10.21.0.1` A record works.

**Public access** (for end users): `ssh pi@fpgas.mithis.com -p 13422` provides port-forwarded access to individual RPis. See [Getting Started](https://github.com/CarlFK/pici/wiki/Getting-Started).

## FPGA Board Inventory

What each board runs and whether it passes its boot check is in the
[current verify results](../verify/current-results.md#current-results) (and, for the Acorns,
[#53](https://github.com/fpgas-online/fpgas.online-test-designs/issues/53)).
The tables here hold what is recorded nowhere else: the Pis' MACs and revision
codes, and the FPGAs' serials and DNAs.

### Arty A7-35T Boards (on RPi 4 hosts with PMOD HATs, sw2 p9, p10, p12, p15)

Each Arty A7 connects via FTDI FT2232C/D/H (USB VID:PID `0403:6010`, labelled "Digilent USB Device"). The FT2232 provides two interfaces:
- **if00** → `/dev/ttyUSB0` — JTAG (used by openFPGALoader)
- **if01** → `/dev/ttyUSB1` — UART serial console (115200 baud)

The serial device path is: `/dev/serial/by-id/usb-Digilent_Digilent_USB_Device_<SERIAL>-if01-port0`

Each RPi also has a separate USB Ethernet adapter connected to the Arty's Ethernet port for network testing.

### NeTV2 Boards (on RPi 3B+ hosts with GPIO JTAG, sw1 p10, p12, p14, p16, p18)

| Host       | IP         | RPi MAC           | RPi Model   | FPGA    | FPGA DNA           |
| ---------- | ---------- | ----------------- | ----------- | ------- | ------------------ |
| pi-sw1-p10 | 10.21.1.10 | b8:27:eb:e3:e7:e4 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662251c6f |
| pi-sw1-p12 | 10.21.1.12 | b8:27:eb:eb:5d:bf | RPi 3B+ 1GB | XC7A35T | 0x3a11a4c662372a6b |
| pi-sw1-p14 | 10.21.1.14 | b8:27:eb:e3:7c:3c | RPi 3B+ 1GB | XC7A35T | 0x3a11dcc864222e93 |
| pi-sw1-p16 | 10.21.1.16 | b8:27:eb:c6:29:79 | RPi 3B+ 1GB | XC7A35T | 0x2a11a4c662372a53 |

Each NeTV2 is programmed via OpenOCD GPIO bitbang JTAG through the RPi's GPIO header. No USB serial devices — the NeTV2 uses GPIO UART for communication (FPGA TX→GPIO15/RXD, FPGA RX→GPIO14/TXD via `/dev/ttyAMA0`).

### Sqrl Acorn CLE-215+

On RPi 5 hosts with an M.2 HAT, on sw2 p29, p37 and p43–p48.

| Host       | IP         | RPi MAC           | RPi Model (rev)             |
| ---------- | ---------- | ----------------- | --------------------------- |
| pi-sw2-p29 | 10.21.2.29 | 88:a2:9e:45:dd:be | RPi 5 Rev 1.1 2 GB (b04171) |
| pi-sw2-p37 | 10.21.2.37 | not recorded      | RPi 5                       |
| pi-sw2-p43 | 10.21.2.43 | 98:fe:54:13:e0:75 | RPi 5 Rev 1.1 1 GB (a04171) |
| pi-sw2-p44 | 10.21.2.44 | 98:fe:54:13:e0:f5 | RPi 5 Rev 1.1 1 GB (a04171) |
| pi-sw2-p46 | 10.21.2.46 | 88:a2:9e:45:85:77 | RPi 5 Rev 1.1 2 GB (b04171) |
| pi-sw2-p47 | 10.21.2.47 | 98:fe:54:13:f5:75 | RPi 5 Rev 1.1 1 GB (a04171) |
| pi-sw2-p48 | 10.21.2.48 | 88:a2:9e:45:c6:87 | RPi 5 Rev 1.1 2 GB (b04171) |

The Sqrl Acorn CLE-215+ is an M.2 PCIe FPGA accelerator card containing a
Xilinx Artix-7 XC7A200T FPGA (215K logic cells). It connects to the RPi 5 via
an M.2 HAT and enumerates at `0001:01:00.0` alongside the RPi 5's RP1 south
bridge on `0002:01:00.0`. p29 and p43–p48 also have an ov5647 camera.

No USB serial devices — **JTAG and UART go over the 40-pin header** (P1 → SPI0
pins for openFPGALoader bit-bang, P2 → GPIO14/15 with a null-modem crossover)
and PCIe over the M.2 slot; see [acorn-pinmap.md](acorn-pinmap.md). The NFS
root enables `/dev/ttyAMA0` (`[pi5] dtoverlay=uart0-pi5`), puts the kernel
console on `ttyAMA10` and leaves `serial-getty@ttyAMA0` inactive.
**Detach the PCIe endpoint before any JTAG load** or the Pi crashes. A wedged
Pi 5 draws ~0.4 W on PoE instead of ~8 W and needs a PoE cycle (> 90 s to
return).

### Fomu EVT (on the RPi 3B+ 00000000cc479fd1, seen on sw1 p17 on 8 Oct 2026)

The Fomu EVT sits on the Pi's GPIO header, which reaches its iCE40's reset,
CDONE, SPI flash and UART ([pin mapping](fomu-pin-mapping.md#the-pis-header)):
the check finds and identifies it there. In its bootloader it also appears on
USB as "Generic Fomu EVT running DFU Bootloader v2.0.4" (`1209:5bf0`). An
OpenVizsla OV3 USB analyser (`1d50:607c`, serial OV100662) sits inline on the
Fomu's USB to debug its USB stack: a debug tool, not a board. On 9 Oct 2026 at
09:00 ACDT, with only the OV3 on USB, the header's CDONE read high.

### Tiny Tapeout ASIC Boards (×6, on S3300 ports 3–8, RPi 4 / 3B+ hosts with PMOD HATs)

These boards contain **real fabricated TT ASIC silicon** on a TT demo board
(RP2040, MicroPython TT SDK). They are the public boards on
[tinytapeout.fpgas.online](https://tinytapeout.fpgas.online): S3300 port N carries TTN, the board page is
`https://tinytapeout.fpgas.online/board/<slug>/` and its `status.json` is the
liveness check.

| Host      | Slug     | Switch Port | IP        | RPi MAC           | RPi Model (rev)               | Chip / firmware                          | RP2040 serial      |
| --------- | -------- | ----------- | --------- | ----------------- | ----------------------------- | ---------------------------------------- | ------------------ |
| pi-sw2-p3 | [tt03p5](https://tinytapeout.fpgas.online/board/tt03p5/) | sw2 p3 | 10.21.2.3 | 98:fe:54:1b:7f:de | RPi 4 2 GB Rev 1.5 (b03115) | TT03p5 (sky130), demo-board fw **1.2.2** (last release supporting tt03p5) | de636c65c34d6a25 |
| pi-sw2-p4 | [tt04](https://tinytapeout.fpgas.online/board/tt04/)     | sw2 p4 | 10.21.2.4 | 98:fe:54:1b:7f:57 | RPi 4 2 GB Rev 1.5 (b03115) | TT04, TT SDK 2.0.4                        | de637061074b1838 |
| pi-sw2-p5 | [tt05](https://tinytapeout.fpgas.online/board/tt05/)     | sw2 p5 | 10.21.2.5 | 98:fe:54:1b:80:11 | RPi 4 2 GB Rev 1.5 (b03115) | TT05, TT SDK 2.0.4                        | de637061071e5439 |
| pi-sw2-p6 | [tt06](https://tinytapeout.fpgas.online/board/tt06/)     | sw2 p6 | 10.21.2.6 | b8:27:eb:71:78:cc | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT06, TT SDK 2.0.4                      | de640cb1d3357125 |
| pi-sw2-p7 | [tt07](https://tinytapeout.fpgas.online/board/tt07/)     | sw2 p7 | 10.21.2.7 | b8:27:eb:19:43:cd | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT07, TT SDK 2.0.4                      | de641070db746f27 |
| pi-sw2-p8 | [tt08](https://tinytapeout.fpgas.online/board/tt08/)     | sw2 p8 | 10.21.2.8 | b8:27:eb:44:46:e9 | RPi 3B+ 1 GB Rev 1.3 (a020d3) | TT08, TT SDK 2.0.4                      | de641070db5b2d27 |

Ports 9 and 10 (tt09, tt10) are reserved in the catalogue but have no Pi yet.
The TT ASIC boards appear as "MicroPython Board in FS mode" (RP2040, VID:PID
`2e8a:0005`) at `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_<serial>-if00`,
with a udev symlink `/dev/ttboard → ttyACM0`. Every host runs the `fpgas-tt`
daemon (0.1.0), which **owns the serial port** and exposes it as a WebSocket
bridge on port 8765 for the web Commander; stop it before using `mpremote`.
Every host also has a Digilent Pmod HAT and an ov5647 camera.

Firmware notes: tt04 … tt08 run TT SDK 2.0.4 (the last RP2040 build; 3.x is
RP2350-only). The tt03p5 chip is not supported by SDK ≥ 2.0, so that board runs demo-board
firmware 1.2.2 with a hand-pushed `/shuttles/tt03p5.json` and
`rom_fallback.txt` (TT03p5 has no chip ROM). The RP2 bootloader's mass-storage
path stalls on Pi 3B+ hosts (dwc_otg resets every ~35 s) — flash from those
with PICOBOOT, and run flashes detached (`setsid nohup … &`).

Source: live probe 2026-09-03 (`lsusb`, `/dev/serial/by-id`, `fuser
/dev/ttyACM0`, daemon `/health`); catalogue = `tt_boards` in infra `host_vars/fpgas.online.yml`.

### Tiny Tapeout FPGA Demo Boards (×4, on S3300 ports 33–36, RPi 4 hosts with PMOD HATs)

These boards contain an **iCE40UP5K FPGA** (FabricFox breakout) that emulates
Tiny Tapeout designs, on a TT demo board **v3 (RP2350B)** running TT SDK
**3.1.0**. They are **not** ASIC boards. Public as
`fpga-1` … `fpga-4` on tinytapeout.fpgas.online, where users
can run bundled demos or upload their own bitstream.

| Host       | Slug   | Switch Port | IP         | RPi MAC           | RPi Model (rev)              | USB VID:PID | RP2350 Serial    | `verify_hardware.py` |
| ---------- | ------ | ----------- | ---------- | ----------------- | ---------------------------- | ----------- | ---------------- | -------------------- |
| pi-sw2-p33 | [fpga-1](https://tinytapeout.fpgas.online/board/fpga-1/) | sw2 p33 | 10.21.2.33 | e4:5f:01:97:0e:77 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | 4df39a7a6856f86f | welland-pi27 |
| pi-sw2-p34 | [fpga-2](https://tinytapeout.fpgas.online/board/fpga-2/) | sw2 p34 | 10.21.2.34 | e4:5f:01:97:27:f2 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | fd1a167bd863a198 | welland-pi29 |
| pi-sw2-p35 | [fpga-3](https://tinytapeout.fpgas.online/board/fpga-3/) | sw2 p35 | 10.21.2.35 | e4:5f:01:97:0c:e3 | RPi 4 2 GB Rev 1.5 (b03115) | 2e8a:0005 | 8c46329b33590ecb | welland-pi31 |
| pi-sw2-p36 | [fpga-4](https://tinytapeout.fpgas.online/board/fpga-4/) | sw2 p36 | 10.21.2.36 | e4:5f:01:8e:02:27 | RPi 4 8 GB Rev 1.5 (d03115) | 2e8a:0005 | a2961e5cac65b25f | welland-pi33 |

Like the ASIC boards, these appear as "MicroPython Board in FS mode" (VID:PID
`2e8a:0005`) with the `/dev/ttboard` symlink, and the `fpgas-tt` daemon owns
the port. See [tt-fpga.md](tt-fpga.md) for the firmware and its
consequences for this repo's `mpremote`-based tooling.

Source: live probe 2026-09-03 (`lsusb`, `/dev/serial/by-id`, daemon `/health`).

### NeTV2 Boards (separate network — development/debug hosts)

In addition to the NeTV2 boards on the tweed network above, there are two NeTV2 development hosts on a **separate network** accessible via different hostnames:

| Host                              | IP (via DNS)    | RPi Model             | Board                  | Connections         | SSH                                                        |
| --------------------------------- | --------------- | --------------------- | ---------------------- | ------------------- | ---------------------------------------------------------- |
| rpi5-netv2.iot.welland.mithis.com | 10.1.90.210/211 | RPi 5 Model B Rev 1.0 | NeTV2 (bare developer) | GPIO + PCIe Gen2 x1 | `tim@rpi5-netv2.iot.welland.mithis.com` (via `wg-desktop`) |
| rpi3-netv2.iot.welland.mithis.com | 10.1.90.212/213 | RPi 3                 | NeTV2 (stock packaged) | GPIO only           | `pi@rpi3-netv2.iot.welland.mithis.com` (via `wg-desktop`)  |

### PMOD HAT Hosts (separate network)

Additional PMOD-related RPi hosts on a separate `iot.welland.mithis.com` network:

| Host                             | RPi Model | Notes             |
| -------------------------------- | --------- | ----------------- |
| rpi5-pmod.iot.welland.mithis.com | RPi 5     | PMOD HAT dev host |
| rpi4-pmod.iot.welland.mithis.com | RPi 4     | PMOD HAT dev host |

## Programming Methods

### openFPGALoader

[openFPGALoader](https://github.com/trabucayre/openFPGALoader) is the primary JTAG programming tool used across almost all boards. It supports multiple JTAG transports and FPGA families.

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
sudo ln -sfn /dev/gpiochip15 /dev/gpiochip0                   # the libgpiod cable opens gpiochip0
openFPGALoader --cable libgpiod --pins 10:9:11:8 design.bit   # TDI:TDO:TCK:TMS, ~16 s, SRAM only
```

PCIe-based flash programming needs the fpgas.online SoC already running; see
[acorn-pcie-programming.md](acorn-pcie-programming.md).

**Fomu EVT** (via USB DFU):

A Fomu in its DFU bootloader (v2.0.4) can be programmed via `dfu-util -D design.dfu` as a fallback. openFPGALoader also supports DFU-based programming.

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

Used for: **Acorn CLE-215+** (the RPi 5 hosts), **NeTV2** (RPi5 only)

The Acorn enumerates at `0001:01:00.0`: as `10ee:7021` with subsystem `1e24:021f` when it runs the fpgas.online SoC, `1e24:021f` on Sqrl's factory firmware, `10ee:7011` on the vendor XDMA sample. Reconfiguring the FPGA over JTAG while the endpoint is enumerated is a surprise removal that crashes the Pi 5 — remove the device from the bus first and rescan afterwards ([acorn-pcie-programming.md](acorn-pcie-programming.md#detach-the-pcie-endpoint-before-any-jtag-reconfiguration)).

The NeTV2 supports PCIe x1/x2/x4. On RPi5, it connects as PCIe Gen2 x1. The FPGA appears with vendor ID `10ee` (Xilinx) and device ID `7011`.

### USB (Native)

Used for: **Fomu EVT** (ValentyUSB on pi-sw1-p17), **Tiny Tapeout ASIC** (RP2040 on pi-sw2-p3…p8), **Tiny Tapeout FPGA Demo Board** (RP2350 on pi-sw2-p33…p36). An OpenVizsla on pi-sw1-p17 analyzes the Fomu's USB traffic.

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

## Known Issues

- **Stale NFS handles after package upgrades in the shared NFS root**: upgrading a package (`fpgas-online-cam`, say) under running Pis leaves them with `ESTALE` on the replaced files: cameras go off air and `dpkg-query` reports `Stale file handle`. Only a reboot fixes it — expect it after any NFS-root package update.
