# Site: PS1 (ps1.fpgas.online)

The PS1 site is the public-facing fpgas.online infrastructure, hosted at Pumping Station One (PS1) hackerspace in Chicago. It provides remote access to Arty A7 FPGA boards for anyone to use.

## Gateway: val2

| Parameter  | Value                                            |
|------------|--------------------------------------------------|
| Hostname   | val2                                             |
| Public DNS | ps1.fpgas.online                                 |
| OS         | Debian 12 (bookworm)                             |
| Kernel     | 6.1.0-40-amd64                                   |
| eth-uplink | 76.227.131.147/25 (public internet)              |
| eth-local  | 10.21.0.1/24 (RPi network)                       |
| Web server | nginx (reverse proxy for web SSH + video streams) |
| PoE switch | Netgear FS728TPv2 at 10.21.0.200                 |
| SSH access | `ssh root@ps1.fpgas.online`                      |

NFS roots:
- **bookworm** (armhf): `/srv/nfs/rpi/bookworm/{boot,root}` — RPi 3B/3B+/4B (read-only with overlayroot)
- **trixie** (arm64): `/srv/nfs/rpi/trixie/{boot,root}` — RPi CM5 Lite Compute Blades (kernel 6.12.75+rpt-rpi-v8)

## RPi Inventory

Hosts are listed in natural sort order in `/etc/dnsmasq.d/pibs.conf`.

| Host | IP          | RPi Model            | FPGA Board    | Arty Serial  | USB Ethernet | Status  |
|------|-------------|----------------------|---------------|--------------|--------------|---------|
| pi2  | 10.21.0.102 | RPi 3B Rev 1.2       | Arty A7       | 210319B301E0 | Apple A1277  | Offline |
| pi3  | 10.21.0.103 | RPi 4B Rev 1.1       | Arty A7       | 210319A43AD3 | ASIX AX88179 | Online  |
| pi5  | 10.21.0.105 | RPi 3B Rev 1.2       | Arty A7       | 210319B58381 | ASIX AX88179 | Online  |
| pi7  | 10.21.0.107 | RPi 3B+ Rev 1.3      | Arty A7       | 210319A764F5 | ASIX AX88179 | Online  |
| pi9  | 10.21.0.109 | RPi 3B+ Rev 1.3      | Arty A7       | 210319B58379 | ASIX AX88179 | Online  |
| pi11 | 10.21.0.111 | RPi 3B Rev 1.2       | Arty A7       | 210319B5835B | ASIX AX88179 | Online  |
| pi13 | 10.21.0.113 | RPi 3B Rev 1.2       | Arty A7       | 210319B3E5C3 | ASIX AX88179 | Online  |
| pi14 | 10.21.0.114 | CM4 Rev 1.1 4GB      | Acorn CLE-101 | —            | —            | Online  |
| pi16 | 10.21.0.116 | CM5 Lite Rev 1.0 8GB | Acorn CLE-101 | —            | —            | Online  |
| pi17 | 10.21.0.117 | RPi 3B Rev 1.2       | Arty A7       | 210319B58370 | ASIX AX88179 | Online  |
| pi18 | 10.21.0.118 | CM4 Rev 1.1 4GB      | (empty M.2)   | —            | —            | Online  |
| pi19 | 10.21.0.119 | RPi 3B               | (none)        | —            | —            | Dead    |
| pi20 | 10.21.0.120 | CM5 Lite Rev 1.0 8GB | (empty M.2)   | —            | —            | Online  |
| pi21 | 10.21.0.121 | RPi 5 Rev 1.0 4GB    | (none)        | —            | —            | Online  |
| pi24 | 10.21.0.124 | (unknown)            | (unknown)     | —            | —            | Offline |

All Arty boards connect via FTDI FT2232C/D/H (`0403:6010`). Each provides:
- `/dev/ttyUSB0` — JTAG (openFPGALoader)
- `/dev/ttyUSB1` — UART serial console (115200 baud)

Each RPi also has a separate USB Ethernet adapter for the Arty's Ethernet port.

### Notes

- **pi2** (port e2): Uses Apple Ethernet adapter (A1277). Currently offline per pibs.conf.
- **pi17** (port e17): RPi 3B with Arty A7 (serial 210319B58370, FTDI + ASIX Ethernet). Discovered 2026-03-21.
- **pi19** (port e19): RPi 3B, dead. Link UP but no DHCP/TFTP activity.
- **pi21** (port e21): RPi 5 Rev 1.0, 4 GB. No FPGA board. Running Trixie (arm64).
- **pi24**: Offline — registered in dnsmasq (MAC `b8:27:eb:85:ab:d9`) but not seen on switch.

## PoE Switch Port Inventory

Switch: **Netgear FS728TPv2** at 10.21.0.200 (24 Fast Ethernet + 4 Gigabit ports). Queried via SNMPv3 on 2026-03-21.

LLDP: server (val2) connects on port g25. Upstream is a Ubiquiti US-24-G1 (`PS1-SW-MODEM`).

| Port | Link | PoE         | MAC               | Device      | Host | Notes                    |
|------|------|-------------|-------------------|-------------|------|--------------------------|
| e1   | down | searching   |                   |             |      | Cable present, no device |
| e2   | UP   | delivering  | b8:27:eb:2f:5d:08 | RPi 3B      | pi2  |                          |
| e3   | UP   | delivering  | dc:a6:32:05:32:45 | RPi 4B      | pi3  |                          |
| e4   | down | searching   |                   |             |      | Cable present, no device |
| e5   | UP   | delivering  | b8:27:eb:d4:f1:74 | RPi 3B      | pi5  |                          |
| e6   | down | disabled    |                   |             |      |                          |
| e7   | UP   | delivering  | b8:27:eb:33:51:27 | RPi 3B+     | pi7  |                          |
| e8   | down | disabled    |                   |             |      |                          |
| e9   | UP   | delivering  | b8:27:eb:a3:51:b4 | RPi 3B+     | pi9  |                          |
| e10  | down | disabled    |                   |             |      |                          |
| e11  | UP   | delivering  | b8:27:eb:51:01:df | RPi 3B      | pi11 |                          |
| e12  | down | disabled    |                   |             |      |                          |
| e13  | UP   | delivering  | b8:27:eb:68:fc:e7 | RPi 3B      | pi13 |                          |
| e14  | UP   | delivering  | 2c:cf:67:37:d4:bd | CM4 4GB     | pi14 | Acorn CLE-101            |
| e15  | down | delivering  |                   |             |      | PoE on, no link          |
| e16  | UP   | delivering  | 2c:cf:67:fb:91:e5 | CM5 Lite 8GB| pi16 | Acorn CLE-101            |
| e17  | UP   | delivering  | b8:27:eb:5f:de:85 | RPi 3B      | pi17 | Arty A7                  |
| e18  | UP   | delivering  | 2c:cf:67:37:d5:08 | CM4 4GB     | pi18 | Empty M.2 slot           |
| e19  | UP   | delivering  | b8:27:eb:0c:f8:43 | RPi 3B      | pi19 | Dead                     |
| e20  | down | delivering  | 2c:cf:67:fd:1e:be | CM5 Lite 8GB| pi20 | Empty M.2 slot           |
| e21  | UP   | delivering  | 2c:cf:67:39:18:66 | RPi 5       | pi21 |                          |
| e22  | down | disabled    |                   |             |      |                          |
| e23  | down | searching   |                   |             |      | Cable present, no device |
| e24  | down | searching   |                   |             |      | Cable present, no device |
| g25  | UP   | —           | 00:25:90:22:c4:91 | Server NIC  | val2 | Uplink                   |
| g26  | down | —           |                   |             |      |                          |
| g27  | down | —           |                   |             |      |                          |
| g28  | down | —           |                   |             |      |                          |

### Discovered Devices (2026-03-21)

Six devices discovered 2026-03-21 after enabling PoE on previously-disabled ports. All now registered in `pibs.conf`:

| Port | MAC               | Type       | TFTP Serial | Name | IP            | FPGA          | Boot Status              |
|------|-------------------|------------|-------------|------|---------------|---------------|--------------------------|
| e14  | 2c:cf:67:37:d4:bd | RPi CM4    | d00eb762    | pi14 | 10.21.0.114   | Acorn CLE-101 | **Online** (Trixie 6.12.75) |
| e16  | 2c:cf:67:fb:91:e5 | RPi CM5 Lite | cb291e63  | pi16 | 10.21.0.116   | Acorn CLE-101 | **Online** (Trixie 6.12.75) |
| e17  | b8:27:eb:5f:de:85 | RPi 3B     | 7d5fde85    | pi17 | 10.21.0.117   | Arty A7       | Online (bookworm)        |
| e18  | 2c:cf:67:37:d5:08 | RPi CM4    | 4e45f174    | pi18 | 10.21.0.118   | (empty M.2)   | **Online** (Trixie 6.12.75) |
| e19  | b8:27:eb:0c:f8:43 | RPi 3B     | 9b0cf843    | pi19 | 10.21.0.119   | —             | Dead                     |
| e20  | 2c:cf:67:fd:1e:be | RPi CM5 Lite | de59093d  | pi20 | 10.21.0.120   | (empty M.2)   | **Online** (Trixie 6.12.75) |

- **All Compute Blades**: Booting Trixie arm64 (Debian 13) with kernel 6.12.75+rpt-rpi-v8 via NFS. Overlayroot (tmpfs), netconsole, and eth-uplink interface naming all configured. Trixie NFS root has full package parity with bookworm.
- **pi14 (CM4 + Acorn CLE-101)**: Online. Acorn CLE-101 detected on PCIe bus 0000:01. Device path `platform-fd580000.ethernet` (BCM2711).
- **pi16 (CM5 Lite + Acorn CLE-101)**: Online. Acorn CLE-101 detected on PCIe bus 0001:01. Device path `platform-1f00100000.ethernet` (BCM2712).
- **pi18 (CM4, no FPGA)**: Online. PCIe bridge present but M.2 slot appears empty — no FPGA detected. Device path `platform-fd580000.ethernet` (BCM2711).
- **pi20 (CM5 Lite, no FPGA)**: Online. Only RP1 South Bridge on PCIe — M.2 slot appears empty. Device path `platform-1f00100000.ethernet` (BCM2712).
- **pi17** (e17): RPi 3B with Arty A7. Online and SSH-accessible. Added to pibs.conf.
- **pi19** (e19): RPi 3B. Link UP but zero PXE/DHCP activity after PoE cycling. Dead hardware.
- **Ports e1, e4, e15, e23, e24**: No link after PoE cycling. Cables disconnected or dead hardware.

### Port Status Notes

All even-numbered ports (e6/e8/e10/e12) between the registered Arty hosts were previously PoE-disabled. These are the Arty Ethernet test ports (USB Ethernet adapters) — they don't need PoE.

## Comparison with Welland Site

| Feature         | PS1 (ps1.fpgas.online)      | Welland (tweed.welland.mithis.com) |
|-----------------|-----------------------------|------------------------------------|
| Location        | Chicago (PS1 hackerspace)   | Welland, South Australia                   |
| Public access   | Yes (web SSH + video)       | VPN only (WireGuard)               |
| RPi count       | 15 registered (8 Arty + 4 Compute Blade + 1 RPi 5 + 2 offline) | 27 registered (5 Arty + 5 NeTV2 + 4 Acorn + 2 Fomu + 7 TT + 4 other) |
| FPGA boards     | Arty A7, Acorn CLE-101      | Arty, NeTV2, Fomu, TT FPGA, Acorn |
| Network         | 10.21.0.0/24                | 10.21.0.0/16                       |
| NFS roots       | bookworm (armhf) + trixie (arm64) | /srv/nfs/rpi/bookworm/         |
| PoE switch      | Netgear S3300 (10.21.0.200) | Netgear S3300 (10.21.0.200)        |

## Public Web Interface

The PS1 site serves the fpgas.online web interface at `https://ps1.fpgas.online/`:
- Per-board pages with web SSH terminal, reset button, and live video feed
- Video streams via HLS (`/live/piN.m3u8`)
- File upload for bitstreams
- Power cycle control via PoE switch

Source: [fpgas.online](https://fpgas.online), [CarlFK/pici wiki](https://github.com/CarlFK/pici/wiki)

## References

- Public website: [fpgas.online](https://fpgas.online)
- Getting started: [CarlFK/pici wiki](https://github.com/CarlFK/pici/wiki/Getting-Started)
- Ansible playbooks: [CarlFK/pici](https://github.com/CarlFK/pici)
