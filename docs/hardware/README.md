# Hardware Documentation

Documentation for the FPGA boards, host infrastructure, and interconnects used in the fpgas.online test infrastructure.

## Sites

- [site-welland.md](site-welland.md) — Welland, Australia — Private test lab with Arty A7, NeTV2, Fomu EVT, TT FPGA, Acorn CLE-215+
- [site-ps1.md](site-ps1.md) — Pumping Station: One, Chicago — Public-facing fpgas.online service with Arty A7 boards

## FPGA Boards

| Board                       | Spec                               | Pin Mapping                                      | Welland (deployed) | Welland (pending) | PS1 (deployed) | PS1 (pending) |
| --------------------------- | ---------------------------------- | ------------------------------------------------ | ------------------ | ----------------- | -------------- | ------------- |
| Digilent Arty A7-35T        | [arty-a7.md](arty-a7.md)           | [arty-a7-pin-mapping.md](arty-a7-pin-mapping.md) | ×5                 | —                 | ×8             | —             |
| Kosagi NeTV2 (GPIO JTAG)    | [netv2.md](netv2.md)               | [netv2-pin-mapping.md](netv2-pin-mapping.md)     | ×5                 | —                 | —              | —             |
| Kosagi NeTV2 (RPi5 PCIe)    | [netv2.md](netv2.md)               | [netv2-pin-mapping.md](netv2-pin-mapping.md)     | —                  | ×4                | —              | —             |
| Kosagi Fomu EVT             | [fomu-evt.md](fomu-evt.md)         | [fomu-pin-mapping.md](fomu-pin-mapping.md)       | ×2                 | —                 | —              | —             |
| TinyTapeout FPGA Demo Board | [tt-fpga.md](tt-fpga.md)           | [tt-fpga-pin-mapping.md](tt-fpga-pin-mapping.md) | ×4                 | —                 | —              | ×4            |
| TinyTapeout ASIC (TT06)     | —                                  | —                                                | ×1                 | ×1                | ×1             | ×1            |
| TinyTapeout ASIC (TT08)     | —                                  | —                                                | ×1                 | ×1                | —              | ×1            |
| Sqrl Acorn CLE-215+         | [acorn-cle215.md](acorn-cle215.md) | —                                                | ×1                 | ×3                | ×1             | ×3            |
| 1BitSquared ButterStick     | [butterstick.md](butterstick.md)   | —                                                | —                  | ×4                | —              | —             |
| 1BitSquared ULX3S           | [ulx3s.md](ulx3s.md)               | —                                                | —                  | ×4                | —              | —             |

## PMOD Interconnects

- [pmod.md](pmod.md) — PMOD interface specification (standard Digilent types 1–6 + I2C extension)
- [rpi-hat-pmod.md](rpi-hat-pmod.md) — Digilent PMOD HAT adapter for Raspberry Pi (RPi GPIO ↔ PMOD pin mapping, type conformance)
- [pmod-tt.md](pmod-tt.md) — TinyTapeout PMOD connector standards (TT-specific layouts, RP2040/RP2350 GPIO mapping, community PMOD boards)

## Analysis

- [gpio-connectivity-analysis.md](gpio-connectivity-analysis.md) — GPIO scan results and connectivity verification across boards
