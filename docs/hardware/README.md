# Hardware Documentation

Documentation for the FPGA boards, host infrastructure, and interconnects used in the fpgas.online test infrastructure.

## Sites

- [site-welland.md](site-welland.md) — [welland.fpgas.online](https://welland.fpgas.online) — Welland, Australia — Arty A7, NeTV2, Fomu EVT, TT FPGA, Acorn CLE-215+
- [site-ps1.md](site-ps1.md) — [ps1.fpgas.online](https://ps1.fpgas.online) — Pumping Station: One, Chicago — Arty A7 boards with live camera feeds

## FPGA Boards

| Board                       | Docs                                                  | Welland (deployed) | Welland (pending) | PS1 (deployed) | PS1 (pending) |
| --------------------------- | ----------------------------------------------------- | ------------------ | ----------------- | -------------- | ------------- |
| Digilent Arty A7-35T        | [spec](arty-a7.md), [pin map](arty-a7-pin-mapping.md) | ×5                 | —                 | ×8             | —             |
| Kosagi NeTV2 — GPIO JTAG    | [spec](netv2.md), [pin map](netv2-pin-mapping.md)     | ×5                 | —                 | —              | —             |
| Kosagi NeTV2 — RPi5 PCIe    | [spec](netv2.md), [pin map](netv2-pin-mapping.md)     | —                  | ×4                | —              | —             |
| Kosagi Fomu EVT             | [spec](fomu-evt.md), [pin map](fomu-pin-mapping.md)   | ×2                 | —                 | —              | —             |
| TinyTapeout FPGA Demo Board | [spec](tt-fpga.md), [pin map](tt-fpga-pin-mapping.md) | ×4                 | —                 | —              | ×4            |
| TinyTapeout ASIC (TT06)     | —                                                     | ×1                 | ×1                | ×1             | ×1            |
| TinyTapeout ASIC (TT08)     | —                                                     | ×1                 | ×1                | —              | ×1            |
| Sqrl Acorn CLE-215+         | [spec](acorn-cle215.md)                               | ×1                 | ×3                | ×1             | ×3            |
| 1BitSquared ButterStick     | [spec](butterstick.md)                                | —                  | ×4                | —              | —             |
| 1BitSquared ULX3S           | [spec](ulx3s.md)                                      | —                  | ×4                | —              | —             |

## PMOD Interconnects

- [pmod.md](pmod.md) — PMOD interface specification (standard Digilent types 1–6 + I2C extension)
- [rpi-hat-pmod.md](rpi-hat-pmod.md) — Digilent PMOD HAT adapter for Raspberry Pi (RPi GPIO ↔ PMOD pin mapping, type conformance)
- [pmod-tt.md](pmod-tt.md) — TinyTapeout PMOD connector standards (TT-specific layouts, RP2040/RP2350 GPIO mapping, community PMOD boards)

## Analysis

- [gpio-connectivity-analysis.md](gpio-connectivity-analysis.md) — GPIO scan results and connectivity verification across boards
