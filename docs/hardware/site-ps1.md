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
| PoE switch | Netgear S3300 at 10.21.0.200                     |
| SSH access | `ssh root@ps1.fpgas.online`                      |

NFS root: `/srv/nfs/rpi/bookworm/{boot,root}` (read-only for all RPis).

## RPi Inventory

Hosts are listed in natural sort order in `/etc/dnsmasq.d/pibs.conf`.

| Host | IP          | RPi Model          | FPGA Board | Arty Serial  | USB Ethernet | Status  |
|------|-------------|--------------------|-----------:|--------------|--------------|---------|
| pi2  | 10.21.0.102 | RPi 3B Rev 1.2     | Arty A7    | 210319B301E0 | Apple A1277  | Online  |
| pi3  | 10.21.0.103 | RPi 4B Rev 1.1     | Arty A7    | 210319A43AD3 | ASIX AX88179 | Online  |
| pi5  | 10.21.0.105 | RPi 3B Rev 1.2     | Arty A7    | 210319B58381 | ASIX AX88179 | Online  |
| pi7  | 10.21.0.107 | RPi 3B+ Rev 1.3    | Arty A7    | 210319A764F5 | ASIX AX88179 | Online  |
| pi9  | 10.21.0.109 | RPi 3B+ Rev 1.3    | Arty A7    | 210319B58379 | ASIX AX88179 | Online  |
| pi11 | 10.21.0.111 | RPi 3B Rev 1.2     | Arty A7    | 210319B5835B | ASIX AX88179 | Online  |
| pi13 | 10.21.0.113 | RPi 3B Rev 1.2     | Arty A7    | 210319B3E5C3 | ASIX AX88179 | Online  |
| pi21 | 10.21.0.121 | RPi 5 Rev 1.0      | (none)     | —            | —            | Online  |
| pi24 | 10.21.0.123 | (unknown)          | (unknown)  | —            | —            | Offline |

All Arty boards connect via FTDI FT2232C/D/H (`0403:6010`). Each provides:
- `/dev/ttyUSB0` — JTAG (openFPGALoader)
- `/dev/ttyUSB1` — UART serial console (115200 baud)

Each RPi also has a separate USB Ethernet adapter for the Arty's Ethernet port.

### Notes

- **pi21** (RPi 5): No FPGA board or USB serial devices detected. May be a test/development host or awaiting hardware.
- **pi24**: Offline — registered in dnsmasq (MAC `b8:27:eb:85:ab:d9`) but not seen on switch. Not responding.
- **pi2** uses an Apple Ethernet adapter (A1277) rather than the ASIX AX88179 used by other hosts.
- There are commented-out entries for alternate MACs on pi21 and pi23 — previous hardware that was replaced.

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
| e14  | down | disabled    |                   |             |      |                          |
| e15  | down | delivering  |                   |             |      | PoE on, no link          |
| e16  | down | disabled    |                   |             |      |                          |
| e17  | down | disabled    |                   |             |      |                          |
| e18  | down | disabled    |                   |             |      |                          |
| e19  | down | disabled    |                   |             |      |                          |
| e20  | down | disabled    |                   |             |      |                          |
| e21  | UP   | delivering  | 2c:cf:67:39:18:66 | RPi 5       | pi21 |                          |
| e22  | down | disabled    |                   |             |      |                          |
| e23  | down | searching   |                   |             |      | Cable present, no device |
| e24  | down | searching   |                   |             |      | Cable present, no device |
| g25  | UP   | —           | 00:25:90:22:c4:91 | Server NIC  | val2 | Uplink                   |
| g26  | down | —           |                   |             |      |                          |
| g27  | down | —           |                   |             |      |                          |
| g28  | down | —           |                   |             |      |                          |

### Interesting Ports

- **e1, e4, e15, e23, e24**: PoE cycling and 120s broadcast capture (2026-03-21) found zero DHCP requests and no new MAC addresses. All 5 ports remain link-down after PoE power cycle. These cables are either disconnected at the device end or the devices are dead. No Pi Compute Blades are currently connected to this switch.

## Comparison with Welland Site

| Feature         | PS1 (ps1.fpgas.online)      | Welland (tweed.welland.mithis.com) |
|-----------------|-----------------------------|------------------------------------|
| Location        | Chicago (PS1 hackerspace)   | Welland, Ontario                   |
| Public access   | Yes (web SSH + video)       | VPN only (WireGuard)               |
| RPi count       | 9 registered (7 Arty + 1 RPi5 + 1 offline) | 18+ (Arty + NeTV2 + Fomu + TT + Acorn) |
| FPGA boards     | Arty A7 only                | Arty, NeTV2, Fomu, TT FPGA, Acorn |
| Network         | 10.21.0.0/24                | 10.21.0.0/16                       |
| NFS root        | /srv/nfs/rpi/bookworm/      | /srv/nfs/rpi/bookworm/             |
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
