# Hardware Documentation

Documentation for the FPGA boards, host infrastructure, and interconnects used in the fpgas.online test infrastructure.

## Sites

- [site-welland.md](site-welland.md) — [welland.fpgas.online](https://welland.fpgas.online) / [tinytapeout.fpgas.online](https://tinytapeout.fpgas.online) — Welland, Australia — Arty A7, NeTV2, Fomu EVT, TT ASIC (TT03p5–TT08), TT FPGA, Acorn CLE-215+ (VLAN-per-port addressing since 2026-08-23)
- [site-ps1.md](site-ps1.md) — [ps1.fpgas.online](https://ps1.fpgas.online) — Pumping Station: One, Chicago — Arty A7 boards with live camera feeds, LiteFury / Acorn CLE-101 on Compute Blades

## FPGA Boards

| Board | Docs | [Welland](site-welland.md) | [PS1](site-ps1.md) | FPGA | Features |
|-------|------|---------|-----|------|----------|
| [Digilent Arty A7-35T](https://digilent.com/shop/arty-a7-artix-7-fpga-development-board/) | [spec](arty-a7.md), [pinmap](arty-a7-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/digilent_arty.py) | ×5 | ×8 | Xilinx XC7A35T | DDR3, Ethernet, PMOD, USB&nbsp;JTAG+UART |
| [Kosagi NeTV2](https://www.crowdsupply.com/alphamax/netv2) (GPIO&nbsp;JTAG) | [spec](netv2.md), [pinmap](netv2-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py) | ×5 | — | Xilinx XC7A35T | DDR3, Ethernet, PCIe, HDMI, GPIO&nbsp;JTAG+UART |
| [Kosagi NeTV2](https://www.crowdsupply.com/alphamax/netv2) (RPi5&nbsp;PCIe) | [spec](netv2.md), [pinmap](netv2-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_netv2.py) | —&nbsp;(+×4) | — | Xilinx XC7A35T | DDR3, Ethernet, PCIe, HDMI, GPIO&nbsp;JTAG+UART |
| [Sqrl Acorn CLE-215+](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215) | [spec](acorn.md), [pinmap](acorn-pinmap.md), [pinmap & wiring](acorn-pinmap.md), [pcie programming](acorn-pcie-programming.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py) | ×6 | — | Xilinx XC7A200T | DDR3, PCIe, SPI&nbsp;Flash, GPIO&nbsp;JTAG+UART |
| [LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury) / Acorn CLE-101 | [spec](acorn.md), [pinmap](acorn-pinmap.md), [pinmap & wiring](acorn-pinmap.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py) | — | ×3&nbsp;(+×1) | Xilinx XC7A100T | DDR3, PCIe, SPI&nbsp;Flash, GPIO&nbsp;JTAG+UART |
| [Fomu EVT](https://www.crowdsupply.com/sutajio-kosagi/fomu) | [spec](fomu-evt.md), [pinmap](fomu-pin-mapping.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py) | ×2 | — | Lattice iCE40UP5K | USB&nbsp;1.1, SPI&nbsp;Flash, PMOD, I2C |
| [TT FPGA Demo Board](https://tinytapeout.com/guides/fpga-breakout/) | [spec](tt-fpga.md), [pinmap](tt-fpga-pin-mapping.md), [platform](../../designs/_shared/tt_fpga_platform.py), [live](https://tinytapeout.fpgas.online/board/fpga-1/) | ×4 | —&nbsp;(+×4) | Lattice iCE40UP5K | PMOD, USB&nbsp;(RP2350), SPI&nbsp;Flash |
| [ButterStick](https://butterstick.io/) | [spec](butterstick.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/gsd_butterstick.py) | —&nbsp;(+×4) | — | Lattice ECP5UM5G-85F | DDR3, GbE, USB&nbsp;2.0, SYZYGY |
| [ULX3S](https://radiona.org/ulx3s/) | [spec](ulx3s.md), [litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/radiona_ulx3s.py) | —&nbsp;(+×4) | — | Lattice ECP5 (various) | SDRAM, USB, WiFi, PMOD |
| [TT02](https://tinytapeout.com/chips/tt02/) | — | —&nbsp;(+×1) | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT03](https://tinytapeout.com/chips/tt03/) | — | —&nbsp;(+×1) | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT03p5](https://tinytapeout.com/chips/tt03p5/) | [live](https://tinytapeout.fpgas.online/board/tt03p5/) | ×1 | — | SKY130 ASIC | PMOD, USB&nbsp;(RP2040, fw 1.2.2) |
| [TT04](https://tinytapeout.com/chips/tt04/) | [live](https://tinytapeout.fpgas.online/board/tt04/) | ×1 | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT05](https://tinytapeout.com/chips/tt05/) | [live](https://tinytapeout.fpgas.online/board/tt05/) | ×1 | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT06](https://tinytapeout.com/chips/tt06/) | [live](https://tinytapeout.fpgas.online/board/tt06/) | ×1 | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT07](https://tinytapeout.com/chips/tt07/) | [live](https://tinytapeout.fpgas.online/board/tt07/) | ×1 | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT08](https://tinytapeout.com/chips/tt08/) | [live](https://tinytapeout.fpgas.online/board/tt08/) | ×1 | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |
| [TT09](https://tinytapeout.com/chips/tt09/) | — | —&nbsp;(+×1) | —&nbsp;(+×1) | SKY130 ASIC | PMOD, USB&nbsp;(RP2040) |

Deployment counts: `×N` = deployed, `(+×N)` = pending deployment, `—` = none.
The Welland TT ASIC and TT FPGA boards are the public boards on
[tinytapeout.fpgas.online](https://tinytapeout.fpgas.online) and sit on S3300
ports 3–8 and 33–36 (`pi-sw2-p<port>`); see [site-welland.md](site-welland.md).

## PMOD Interconnects

- [pmod.md](pmod.md) — PMOD interface specification (standard Digilent types 1–6 + I2C extension)
- [rpi-hat-pmod.md](rpi-hat-pmod.md) — Digilent PMOD HAT adapter for Raspberry Pi (RPi GPIO ↔ PMOD pinmap, type conformance)
- [pmod-tt.md](pmod-tt.md) — TinyTapeout PMOD connector standards (TT-specific layouts, RP2040/RP2350 GPIO mapping, community PMOD boards)

## Wiring Guides

- [acorn-pinmap.md](acorn-pinmap.md) — Step-by-step Acorn CLE-215+ setup: M.2 HAT, Pico-EZmate cable prep, JTAG/UART/GPIO wiring (serial crossover!), Pi 5 traps, measured per-board wiring, PCIe verification
- [acorn-pcie-programming.md](acorn-pcie-programming.md) — PCIe-detach rule for JTAG loads, prebuilt Vivado bitstreams, PCIe-based bitstream programming, Xilinx 7-series multiboot, flash layout, recovery procedures

## Processes

- [deployment-checklist.md](deployment-checklist.md) — Files to update when deploying a new device of an existing type

## Analysis

- [gpio-connectivity-analysis.md](gpio-connectivity-analysis.md) — GPIO scan results and connectivity verification across boards
