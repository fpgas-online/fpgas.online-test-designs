# Site: Pumping Station: One, Chicago

[ps1.fpgas.online](https://ps1.fpgas.online) — fpgas.online site hosted at [Pumping Station: One](https://pumpingstationone.org/) (PS1), a hackerspace in Chicago, IL. Managed by Carl Karsten via the [CarlFK/pici](https://github.com/CarlFK/pici) repository.

This site provides public remote access to Arty A7 FPGA boards — anyone can program and interact with the boards through a web interface, with live camera feeds showing the board LEDs.

## Gateway: val2 (ps1.fpgas.online)

| Parameter   | Value                                                               |
|-------------|---------------------------------------------------------------------|
| Hostname    | val2                                                                |
| OS          | Debian 12 (bookworm), kernel 6.1.0-40-amd64                        |
| eth-uplink  | 76.227.131.147/25 (internet-facing)                                 |
| eth-local   | 10.21.0.1/24 (RPi network)                                         |
| Services    | dnsmasq (DHCP/DNS/TFTP/PXE), NFS, nginx, wssh                      |
| SSH access  | `ssh pi@ps1.fpgas.online` (restricted jump-host, rbash, ssh-only)   |
| PoE control | `poe.sh <port> <1=on/2=off>` via SNMP to Netgear S3300 at 10.21.0.200 |

## FPGA Board Inventory

Verified via SSH on 2026-03-21. All Arty boards connect via FTDI FT2232 (USB JTAG + UART). Each RPi also has a USB Ethernet adapter for the Arty Ethernet port.

| Host | Switch Port | RPi Model       | Board       | USB Ethernet     | Live Stream                        |
|------|-------------|-----------------|-------------|------------------|------------------------------------|
| pi2  | port 2      | RPi 3B Rev 1.2  | Arty A7-35T | Apple Ethernet   | `ps1.fpgas.online/live/pi2.m3u8`   |
| pi3  | port 3      | RPi 4B Rev 1.1  | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi3.m3u8`   |
| pi5  | port 5      | RPi 3B Rev 1.2  | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi5.m3u8`   |
| pi7  | port 7      | RPi 3B+ Rev 1.3 | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi7.m3u8`   |
| pi9  | port 9      | RPi 3B+ Rev 1.3 | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi9.m3u8`   |
| pi11 | port 11     | RPi 3B Rev 1.2  | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi11.m3u8`  |
| pi13 | port 13     | RPi 3B Rev 1.2  | Arty A7-35T | ASIX AX88179     | `ps1.fpgas.online/live/pi13.m3u8`  |
| pi21 | port 21     | RPi 5 Rev 1.0   | (none)      | —                | `ps1.fpgas.online/live/pi21.m3u8`  |

pi21 is an RPi 5 with no FPGA board connected — available for future expansion.

Each RPi has:
- Digilent PMOD HAT connecting RPi GPIO to Arty PMOD ports (JA→JA, JB→JB, JC→JC)
- USB camera pointed at the Arty board for live HLS video streaming
- NFS netboot from val2

## PMOD Wiring

Same as the Welland site — ribbon cables connect straight through between matching port names. See [rpi-hat-pmod.md](rpi-hat-pmod.md) for the HAT pin mapping and [arty-a7-pin-mapping.md](arty-a7-pin-mapping.md) for the full RPi GPIO → PMOD → FPGA pin mapping.

| HAT Port | Arty Port |
| -------- | --------- |
| JA       | JA        |
| JB       | JB        |
| JC       | JC        |
| —        | JD (N/C)  |

Note: The PMOD ribbon cables at PS1 have the 3.3V power pins blocked with header hole plugs to prevent connecting the RPi 3.3V rail to the Arty 3.3V rail, which could damage the RPi power management chip.

## Programming

The Arty boards are programmed via openFPGALoader through the FTDI FT2232H USB JTAG interface, same as the [Welland site](site-welland.md).

## Provisioning

The site is managed with Ansible via the [CarlFK/pici](https://github.com/CarlFK/pici) repository. RPi hosts PXE/NFS netboot from a central server.

## Web Interface

The public web interface at [fpgas.online](https://fpgas.online) allows users to:
1. Select an available FPGA board
2. Upload a bitstream to program the FPGA
3. View the board via live HLS camera stream
4. Interact with the FPGA via the PMOD HAT GPIO connections

Source: [fpgas.online](https://fpgas.online), [CarlFK/pici wiki](https://github.com/CarlFK/pici/wiki)

## References

- Public web interface: <https://fpgas.online>
- Provisioning/management repo: <https://github.com/CarlFK/pici>
- Wiki (getting started, wiring, BoM): <https://github.com/CarlFK/pici/wiki>
- Arty A7 board spec: [arty-a7.md](arty-a7.md)
- Arty A7 pin mapping: [arty-a7-pin-mapping.md](arty-a7-pin-mapping.md)
- PMOD HAT adapter: [rpi-hat-pmod.md](rpi-hat-pmod.md)
