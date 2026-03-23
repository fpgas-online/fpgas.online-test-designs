\[[top](./README.md)\] \[[buy](https://radiona.org/ulx3s/)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/radiona_ulx3s.py)\]

# Radiona ULX3S

> **Status: Future / Planned** -- This board is not yet deployed in the fpgas.online infrastructure.

The ULX3S is an open-source ECP5 FPGA development board designed by Radiona.org. It is a feature-rich board with SDRAM, video output, WiFi, and USB.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice ECP5 (LFE5U-12F, 25F, 45F, or 85F variants) |
| Package | BG381 |
| SDRAM | 32 MB SDR SDRAM (AS4C32M16SB-7TCN or similar) |
| Video output | GPDI (HDMI-compatible differential pairs) |
| USB | USB 1.1 Full Speed (directly on FPGA, US1/US2 connectors) |
| WiFi/BT | ESP32 module (WROOM-32) |
| Audio | 3.5mm headphone jack (I2S DAC) |
| MicroSD | MicroSD card slot |
| LEDs | 8 user LEDs |
| Buttons | 7 buttons (power, fire1, fire2, up, down, left, right) |
| GPIO | 28 GPIO pins on pin headers |
| PMOD | No standard PMOD connectors |
| JTAG | On-board FTDI FT231X USB-JTAG |
| Power | USB powered |

Source: [radiona_ulx3s.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/radiona_ulx3s.py), [ULX3S project page](https://radiona.org/ulx3s/)

## ECP5 Variants

| Variant | Device | Logic Cells | LUTs |
|---------|--------|------------|------|
| 12F | LFE5U-12F-6BG381C | 12,000 | 12,000 |
| 25F | LFE5U-25F-6BG381C | 24,000 | 24,000 |
| 45F | LFE5U-45F-6BG381C | 44,000 | 44,000 |
| 85F | LFE5U-85F-6BG381C | 84,000 | 84,000 |

## Notable Differences from Other Boards

- **No PMOD connectors**: Uses pin headers instead. PMOD-based tests cannot run on this board without an adapter.
- **SDR SDRAM** (not DDR3): 32 MB, 16-bit bus. Simpler memory interface but lower bandwidth.
- **ESP32 WiFi**: On-board wireless connectivity, could enable remote test reporting without wired Ethernet.
- **GPDI video**: HDMI-compatible output using differential pairs.

## LiteX Integration

| Property | Value |
|----------|-------|
| Platform module | `litex_boards.platforms.radiona_ulx3s` |
| Target module | `litex_boards.targets.radiona_ulx3s` |
| Toolchain | Yosys + nextpnr-ecp5 (open source, Project Trellis) |

## Programming

```bash
# Via openFPGALoader (USB-JTAG)
openFPGALoader -b ulx3s design.bit

# Via fujprog
fujprog design.bit
```

## References

- LiteX platform file: <https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/radiona_ulx3s.py>
- ULX3S project page: <https://radiona.org/ulx3s/>
- ULX3S GitHub: <https://github.com/emard/ulx3s>
