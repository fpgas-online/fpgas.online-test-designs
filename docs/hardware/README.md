# Hardware Documentation

Documentation for the FPGA boards, host infrastructure, and interconnects used in the fpgas.online test infrastructure.

## Sites

- [site-welland.md](site-welland.md) — [welland.fpgas.online](https://welland.fpgas.online) — Welland, Australia — Arty A7, NeTV2, Fomu EVT, TT FPGA, Acorn CLE-215+
- [site-ps1.md](site-ps1.md) — [ps1.fpgas.online](https://ps1.fpgas.online) — Pumping Station: One, Chicago — Arty A7 boards with live camera feeds

## FPGA Boards

| Board | FPGA | Features | Docs | Welland | PS1 |
|-------|------|----------|------|---------|-----|
| [Digilent Arty A7-35T](https://digilent.com/shop/arty-a7-artix-7-fpga-development-board/) | Xilinx XC7A35T | DDR3, Ethernet, PMOD, USB JTAG+UART | [spec](arty-a7.md), [pinmap](arty-a7-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py) | ×5 | ×8 |
| [Kosagi NeTV2](https://www.crowdsupply.com/alphamax/netv2) (GPIO JTAG) | Xilinx XC7A35T | DDR3, Ethernet, PCIe, HDMI, GPIO JTAG+UART | [spec](netv2.md), [pinmap](netv2-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py) | ×5 | — |
| [Kosagi NeTV2](https://www.crowdsupply.com/alphamax/netv2) (RPi5 PCIe) | Xilinx XC7A35T | DDR3, Ethernet, PCIe, HDMI, GPIO JTAG+UART | [spec](netv2.md), [pinmap](netv2-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py) | (+×4) | — |
| [Sqrl Acorn CLE-215+](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215) | Xilinx XC7A200T | DDR3, PCIe, SPI Flash, GPIO JTAG+UART | [spec](acorn.md), [pinmap](acorn-pinmap.md), [wiring](acorn-wiring-guide.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py) | ×1 (+×4) | — |
| [LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury) | Xilinx XC7A100T | DDR3, PCIe, SPI Flash, GPIO JTAG+UART | [spec](acorn.md), [pinmap](acorn-pinmap.md), [wiring](acorn-wiring-guide.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py) | (+×1) | ×2 (+×4) |
| [Fomu EVT](https://www.crowdsupply.com/sutajio-kosagi/fomu) | Lattice iCE40UP5K | USB 1.1, SPI Flash, PMOD, I2C | [spec](fomu-evt.md), [pinmap](fomu-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py) | ×2 | — |
| [TT FPGA Demo Board](https://tinytapeout.com/guides/fpga-breakout/) | Lattice iCE40UP5K | PMOD, USB (RP2350), SPI Flash | [spec](tt-fpga.md), [pinmap](tt-fpga-pin-mapping.md), [platform](../../designs/_shared/tt_fpga_platform.py) | ×4 | (+×4) |
| [ButterStick](https://butterstick.io/) | Lattice ECP5UM5G-85F | DDR3, GbE, USB 2.0, SYZYGY | [spec](butterstick.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/gsd_butterstick.py) | (+×4) | — |
| [ULX3S](https://radiona.org/ulx3s/) | Lattice ECP5 (various) | SDRAM, USB, WiFi, PMOD | [spec](ulx3s.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/radiona_ulx3s.py) | (+×4) | — |
| [TT02](https://tinytapeout.com/chips/tt02/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |
| [TT03](https://tinytapeout.com/chips/tt03/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |
| [TT04](https://tinytapeout.com/chips/tt04/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |
| [TT05](https://tinytapeout.com/chips/tt05/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |
| [TT06](https://tinytapeout.com/chips/tt06/) | SKY130 ASIC | PMOD, USB (RP2040) | — | ×1 | (+×1) |
| [TT07](https://tinytapeout.com/chips/tt07/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |
| [TT08](https://tinytapeout.com/chips/tt08/) | SKY130 ASIC | PMOD, USB (RP2040) | — | ×1 | (+×1) |
| [TT09](https://tinytapeout.com/chips/tt09/) | SKY130 ASIC | PMOD, USB (RP2040) | — | (+×1) | (+×1) |

Deployment counts: `×N` = deployed, `(+×N)` = pending deployment.

## PMOD Interconnects

- [pmod.md](pmod.md) — PMOD interface specification (standard Digilent types 1–6 + I2C extension)
- [rpi-hat-pmod.md](rpi-hat-pmod.md) — Digilent PMOD HAT adapter for Raspberry Pi (RPi GPIO ↔ PMOD pinmap, type conformance)
- [pmod-tt.md](pmod-tt.md) — TinyTapeout PMOD connector standards (TT-specific layouts, RP2040/RP2350 GPIO mapping, community PMOD boards)

## Wiring Guides

- [acorn-wiring-guide.md](acorn-wiring-guide.md) — Step-by-step Acorn CLE-215+ setup: M.2 HAT, Pico-EZmate cable prep, JTAG/UART/GPIO wiring, PCIe verification

## Processes

- [deployment-checklist.md](deployment-checklist.md) — Files to update when deploying a new device of an existing type

## Analysis

- [gpio-connectivity-analysis.md](gpio-connectivity-analysis.md) — GPIO scan results and connectivity verification across boards
