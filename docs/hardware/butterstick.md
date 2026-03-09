# GSG ButterStick

> **Status: Future / Planned** -- This board is not yet deployed in the fpgas.online infrastructure.

The ButterStick is a high-performance ECP5 development board designed by Greg Davill (Great Scott Gadgets / gsg). It features a Lattice ECP5 with SERDES capabilities, DDR3 memory, Gigabit Ethernet, and a SYZYGY high-speed connector.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice ECP5UM5G-85F-8BG381C |
| Package | BG381 |
| SERDES | Up to 5 Gbps (ECP5UM5G variant) |
| Logic cells | 84,000 |
| DDR3 SDRAM | 1 GB (32-bit bus) |
| Ethernet | RGMII Gigabit Ethernet (1000Base-T) |
| USB | ULPI USB 2.0 PHY |
| Expansion | SYZYGY connector (high-speed, not PMOD) |
| LEDs | User LEDs |
| JTAG | On-board USB-JTAG |
| Power | USB-C powered |

Source: [gsd_butterstick.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/gsd_butterstick.py), [ButterStick website](https://butterstick.io)

## Notable Differences from Other Boards

- **ECP5UM5G with SERDES**: The `5G` variant includes high-speed serializer/deserializer blocks, enabling protocols like PCIe Gen1, SATA, or custom high-speed links.
- **SYZYGY connector** (not PMOD): The SYZYGY standard provides higher-speed and higher-density connectivity than PMOD. PMOD-based tests cannot run on this board without an adapter.
- **Gigabit Ethernet**: RGMII PHY supporting 1000Base-T, unlike the 100Base-T on the Arty and NeTV2.
- **ULPI USB**: External USB 2.0 PHY, unlike the Fomu's native USB.
- **DDR3**: Full DDR3 with 32-bit bus, similar to NeTV2 but larger capacity.

## LiteX Integration

| Property | Value |
|----------|-------|
| Platform module | `litex_boards.platforms.gsd_butterstick` |
| Target module | `litex_boards.targets.gsd_butterstick` |
| Toolchain | Yosys + nextpnr-ecp5 (open source, Project Trellis) |

## Programming

```bash
# Via openFPGALoader
openFPGALoader -b butterstick design.bit

# Via DFU (ButterStick has a DFU bootloader)
dfu-util -D design.bit
```

## References

- LiteX platform file: <https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/gsd_butterstick.py>
- ButterStick website: <https://butterstick.io>
- ButterStick GitHub: <https://github.com/butterstick-fpga>
