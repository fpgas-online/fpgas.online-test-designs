# Site: PS1 (ps1.fpgas.online)

[ps1.fpgas.online](https://ps1.fpgas.online) — fpgas.online site hosted at [Pumping Station: One](https://pumpingstationone.org/) (PS1), a hackerspace in Chicago, IL. Managed by Carl Karsten via the [CarlFK/pici](https://github.com/CarlFK/pici) repository.

This site provides remote access to FPGA boards — anyone can program and interact with the boards through a web interface, with live camera feeds showing the board LEDs.

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
- **trixie** (arm64): `/srv/nfs/rpi/trixie/{boot,root}` — Compute Blades (kernel 6.12.75+rpt-rpi-v8)

## FPGA Board Summary

| Board Type    | Deployed | Pending | Hosts                     |
|---------------|----------|---------|---------------------------|
| Arty A7-35T   | ×8       | —       | [pi2](https://ps1.fpgas.online/fpgas/pi2.html), [pi3](https://ps1.fpgas.online/fpgas/pi3.html), [pi5](https://ps1.fpgas.online/fpgas/pi5.html), [pi7](https://ps1.fpgas.online/fpgas/pi7.html), [pi9](https://ps1.fpgas.online/fpgas/pi9.html), [pi11](https://ps1.fpgas.online/fpgas/pi11.html), [pi13](https://ps1.fpgas.online/fpgas/pi13.html), pi17 |
| LiteFury / Acorn CLE-101 | ×3 | ×1 | pi14, pi16, pi20 (pending: pi18, M.2 empty) |
| TT FPGA Demo  | —        | ×4      | TBD                       |
| TT ASIC       | —        | ×7      | TBD (one each: TT02-TT09 except TT08) |

## RPi Inventory

Hosts are listed in natural sort order per `/etc/dnsmasq.d/pibs.conf`.

### Arty A7 Hosts

| Host | Port | IP          | RPi MAC           | RPi Model       | Arty Serial  | USB Eth MAC       | USB Eth Type |
|------|------|-------------|-------------------|-----------------|--------------|-------------------|--------------|
| [pi2](https://ps1.fpgas.online/fpgas/pi2.html)   | e2   | 10.21.0.102 | b8:27:eb:2f:5d:08 | RPi 3B Rev 1.2  | 210319B301E0 | —                 | Apple A1277  |
| [pi3](https://ps1.fpgas.online/fpgas/pi3.html)   | e3   | 10.21.0.103 | dc:a6:32:05:32:45 | RPi 4B Rev 1.1  | 210319A43AD3 | 00:05:1b:b0:47:9d | ASIX AX88179 |
| [pi5](https://ps1.fpgas.online/fpgas/pi5.html)   | e5   | 10.21.0.105 | b8:27:eb:d4:f1:74 | RPi 3B Rev 1.2  | 210319B58381 | f8:e4:3b:a6:a8:62 | ASIX AX88179 |
| [pi7](https://ps1.fpgas.online/fpgas/pi7.html)   | e7   | 10.21.0.107 | b8:27:eb:33:51:27 | RPi 3B+ Rev 1.3 | 210319A764F5 | 00:05:1b:b0:46:51 | ASIX AX88179 |
| [pi9](https://ps1.fpgas.online/fpgas/pi9.html)   | e9   | 10.21.0.109 | b8:27:eb:a3:51:b4 | RPi 3B+ Rev 1.3 | 210319B58379 | f8:e4:3b:a0:55:af | ASIX AX88179 |
| [pi11](https://ps1.fpgas.online/fpgas/pi11.html) | e11  | 10.21.0.111 | b8:27:eb:51:01:df | RPi 3B Rev 1.2  | 210319B5835B | f8:e4:3b:a6:c6:a9 | ASIX AX88179 |
| [pi13](https://ps1.fpgas.online/fpgas/pi13.html) | e13  | 10.21.0.113 | b8:27:eb:68:fc:e7 | RPi 3B Rev 1.2  | 210319B3E5C3 | f8:e4:3b:a6:cf:b1 | ASIX AX88179 |
| pi17 | e17  | 10.21.0.117 | b8:27:eb:5f:de:85 | RPi 3B Rev 1.2  | 210319B58370 | f8:e4:3b:a6:c6:10 | ASIX AX88179 |

All Arty boards connect via FTDI FT2232C/D/H (`0403:6010`). Each provides:
- `/dev/ttyUSB0` — JTAG (openFPGALoader)
- `/dev/ttyUSB1` — UART serial console (115200 baud)

Each RPi also has a separate USB Ethernet adapter for the Arty's Ethernet port.

**pi2 note**: Uses Apple Ethernet adapter (A1277).

### LiteFury / Compute Blade Hosts

| Host | Port | IP          | RPi MAC           | RPi Model            | Board (PCIe ID)                    | FPGA DNA           | PCIe Bus | JTAG                    |
|------|------|-------------|-------------------|----------------------|------------------------------------|--------------------|----------|-------------------------|
| pi14 | e14  | 10.21.0.114 | 2c:cf:67:37:d4:bd | CM4 Rev 1.1 4GB      | Acorn CLE-101 `1e24:0101`          | unreadable         | 0000:01  | no response (P1 unmated) |
| pi16 | e16  | 10.21.0.116 | 2c:cf:67:fb:91:e5 | CM5 Lite Rev 1.0 8GB | Acorn CLE-101 `1e24:0101`          | unreadable         | 0001:01  | no response (P1 unmated) |
| pi18 | e18  | 10.21.0.118 | 2c:cf:67:37:d5:08 | CM4 Rev 1.1 4GB      | (pending) — M.2 empty              | —                  | —        | n/a                     |
| pi20 | e20  | 10.21.0.120 | 2c:cf:67:fd:1e:be | CM5 Lite Rev 1.0 8GB | XC7A100T design `10ee:7011`        | 0x0028e5c45e304854 | 0001:01  | OK                      |

pi14/pi16 enumerate on PCIe with the Sqrl CLE-101 factory ID but do not
answer JTAG — GPIO4 (TCK) shows the Acorn's JTAG pull-up only on pi20, so their
P1 cables are unmated. Details in
[PS1 Compute blades](https://docs.fpgas.online/en/latest/sites/ps1.html#compute-blades).

All Compute Blades boot Trixie arm64 (Debian 13) via NFS with overlayroot. JTAG via Expansion Module Port using [Compute Blade wiring](https://docs.fpgas.online/en/latest/boards/acorn/wiring.html#compute-blade): `openFPGALoader --cable libgpiod --pins 2:3:4:14` (openFPGALoader **0.13.1** on all four, so `--read-dna` works). UART via GPIO14/15 (`/dev/ttyAMA0`, crossover confirmed on pi20 with the pin-ID design: K2→GPIO15, J2→GPIO14). All four have `console=tty1` and `serial-getty@ttyAMA0` inactive, so FPGA output on the UART cannot trigger SysRq ([#3](https://github.com/fpgas-online/fpgas.online-test-designs/issues/3)). PCIe via M.2 slot. Loading a design that drives J2 (pin-ID does) contends with TMS on GPIO14 and costs JTAG until a PoE cycle of the port; PoE control on the FS728TPv2 works only via the Netgear-proprietary OID over SNMPv3 (see `fpgas.online-poe/scripts/poe.sh`).

Read on pi16 on 5 October 2026 (as a visitor, with fpgas-online-verify 0.0.post1100 installed by the site's
owner): Compute Module 5 Lite Rev 1.0, 8 GB, serial `9fb8cfc7cb291e63`; Raspbian 13 (trixie) with a 32-bit
(armhf) userspace on kernel `6.18.50+rpt-rpi-v8`; `enable_uart=1`, `console=serial0,115200` and
`serial-getty@ttyAMA0` active, so what is said above (arm64, kernel 6.12.75, `console=tty1`, no serial getty)
no longer holds there.
The card enumerates as `1e24:0101` (SQRL's factory image). `fpgas-acorn-verify`: `pcie-link` passes (5.0 GT/s,
x1); `jtag` cannot run, because the serial port has GPIO14 (TMS) and that kernel does not lend it
([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)), so no scan has run there since, and the
"P1 unmated" above for pi16 rests on the earlier pull-up reading alone; every other test waits for the card to be converted. How to read that result,
and what has and has not been run on a Compute Blade:
[Checking an Acorn on a Compute Blade](https://docs.fpgas.online/en/latest/boards/acorn/checking-compute-blade.html). pi14, pi18 and pi20 were not read that day.

### Other Hosts

| Host | Port | IP          | RPi MAC           | RPi Model         | Notes                      |
|------|------|-------------|-------------------|--------------------|----------------------------|
| pi19 | e19  | 10.21.0.119 | b8:27:eb:0c:f8:43 | RPi 3B             | Dead hardware              |
| [pi21](https://ps1.fpgas.online/fpgas/pi21.html) | e21  | 10.21.0.121 | 2c:cf:67:39:18:66 | RPi 5 Rev 1.0 4GB  | No FPGA, development host  |
| pi24 | —    | 10.21.0.124 | b8:27:eb:85:ab:d9  | (unknown)          | Registered but not on switch |

## PoE Switch Port Inventory

Switch: **Netgear FS728TPv2** at 10.21.0.200 (24 Fast Ethernet + 4 Gigabit ports).

LLDP: server (val2) connects on port g25. Upstream is a Ubiquiti US-24-G1 (`PS1-SW-MODEM`).

| Port | Host | FPGA Board | Notes                      |
|------|------|------------|----------------------------|
| e1   |      |            | Cable present              |
| e2   | [pi2](https://ps1.fpgas.online/fpgas/pi2.html)  | Arty A7    |                            |
| e3   | [pi3](https://ps1.fpgas.online/fpgas/pi3.html)  | Arty A7    |                            |
| e4   |      |            | Cable present              |
| e5   | [pi5](https://ps1.fpgas.online/fpgas/pi5.html)  | Arty A7    |                            |
| e6   |      |            | Arty Ethernet test port    |
| e7   | [pi7](https://ps1.fpgas.online/fpgas/pi7.html)  | Arty A7    |                            |
| e8   |      |            | Arty Ethernet test port    |
| e9   | [pi9](https://ps1.fpgas.online/fpgas/pi9.html)  | Arty A7    |                            |
| e10  |      |            | Arty Ethernet test port    |
| e11  | [pi11](https://ps1.fpgas.online/fpgas/pi11.html) | Arty A7    |                            |
| e12  |      |            | Arty Ethernet test port    |
| e13  | [pi13](https://ps1.fpgas.online/fpgas/pi13.html) | Arty A7    |                            |
| e14  | pi14 | LiteFury   | CM4 Compute Blade          |
| e15  |      |            |                            |
| e16  | pi16 | LiteFury   | CM5 Lite Compute Blade     |
| e17  | pi17 | Arty A7    |                             |
| e18  | pi18 | (pending)  | CM4 Compute Blade, M.2 empty |
| e19  | pi19 |            | Dead hardware              |
| e20  | pi20 | LiteFury   | CM5 Lite Compute Blade |
| e21  | [pi21](https://ps1.fpgas.online/fpgas/pi21.html) |            | RPi 5, no FPGA             |
| e22  |      |            |                            |
| e23  |      |            | Cable present              |
| e24  |      |            | Cable present              |
| g25  | val2 |            | Server uplink              |
| g26  |      |            |                            |
| g27  |      |            |                            |
| g28  |      |            |                            |

Even-numbered ports (e6/e8/e10/e12) between Arty hosts are for Arty Ethernet test adapters — they don't need PoE.

## Comparison with Welland Site

| Feature     | PS1 (ps1.fpgas.online)                | Welland (tweed.welland.mithis.com)               |
|-------------|---------------------------------------|--------------------------------------------------|
| Location    | Chicago, IL (PS1 hackerspace)         | Welland, South Australia                         |
| FPGA boards | Arty A7, LiteFury                     | Arty, NeTV2, Fomu, TT FPGA, Acorn CLE-215+     |
| Network     | 10.21.0.0/24                          | 10.21.0.0/16                                     |
| NFS roots   | bookworm (armhf) + trixie (arm64)     | bookworm (armhf)                                 |
| PoE switch  | Netgear FS728TPv2 (10.21.0.200)      | Netgear S3300 (10.21.0.200)                      |

## Public Web Interface

The PS1 site serves the fpgas.online web interface at `https://ps1.fpgas.online/`:
- Per-board pages with web SSH terminal, reset button, and live video feed
- Video streams via HLS (`/live/piN.m3u8`)
- File upload for bitstreams
- Power cycle control via PoE switch

## References

- Public website: [fpgas.online](https://fpgas.online)
- Getting started: [CarlFK/pici wiki](https://github.com/CarlFK/pici/wiki/Getting-Started)
- Ansible playbooks: [CarlFK/pici](https://github.com/CarlFK/pici)
- Acorn/LiteFury board spec: [acorn.md](acorn.md)
- Acorn wiring guide: [acorn-pinmap.md](acorn-pinmap.md)
- Arty A7 board spec: [arty-a7.md](arty-a7.md)
