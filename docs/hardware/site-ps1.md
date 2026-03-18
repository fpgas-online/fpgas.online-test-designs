# Site: Pumping Station: One, Chicago

Public-facing [fpgas.online](https://fpgas.online) service hosted at [Pumping Station: One](https://pumpingstationone.org/) (PS1), a hackerspace in Chicago, IL. Managed by Carl Karsten via the [CarlFK/pici](https://github.com/CarlFK/pici) repository.

This site provides public remote access to Arty A7 FPGA boards — anyone can program and interact with the boards through a web interface, with live camera feeds showing the board LEDs.

## FPGA Board Inventory

All boards are Digilent Arty A7-35T connected to Raspberry Pi hosts with PMOD HATs and USB cameras.

| Host | Board          | PMOD HAT | Camera | Live Stream                            |
| ---- | -------------- | -------- | ------ | -------------------------------------- |
| pi2  | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi2.m3u8`      |
| pi3  | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi3.m3u8`      |
| pi5  | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi5.m3u8`      |
| pi7  | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi7.m3u8`      |
| pi9  | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi9.m3u8`      |
| pi11 | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi11.m3u8`     |
| pi21 | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi21.m3u8`     |
| pi23 | Arty A7-35T    | Yes      | Yes    | `ps1.fpgas.online/live/pi23.m3u8`     |

Each RPi has:
- Digilent PMOD HAT connecting RPi GPIO to Arty PMOD ports (JA→JA, JB→JB, JC→JC)
- USB camera pointed at the Arty board for live HLS video streaming
- NFS netboot from the site server

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
