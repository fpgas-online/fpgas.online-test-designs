# Hardware Documentation

Documentation for the FPGA boards, host infrastructure, and interconnects used in the fpgas.online test infrastructure.

## Infrastructure

- [infrastructure.md](infrastructure.md) — Host machines, network topology, SSH access, programming tools

## FPGA Boards

| Board                              | Spec                       | Pin Mapping                                |
| ---------------------------------- | -------------------------- | ------------------------------------------ |
| Digilent Arty A7-35T               | [arty-a7.md](arty-a7.md)  | [arty-a7-pin-mapping.md](arty-a7-pin-mapping.md) |
| Kosagi NeTV2                       | [netv2.md](netv2.md)       | [netv2-pin-mapping.md](netv2-pin-mapping.md)     |
| Kosagi Fomu EVT                    | [fomu-evt.md](fomu-evt.md) | [fomu-pin-mapping.md](fomu-pin-mapping.md)       |
| TinyTapeout FPGA Demo Board        | [tt-fpga.md](tt-fpga.md)   | [tt-fpga-pin-mapping.md](tt-fpga-pin-mapping.md) |
| Sqrl Acorn CLE-215+               | [acorn-cle215.md](acorn-cle215.md) | —                                    |
| 1BitSquared ButterStick            | [butterstick.md](butterstick.md)   | —                                    |
| 1BitSquared ULX3S                  | [ulx3s.md](ulx3s.md)              | —                                    |

## PMOD Interconnects

- [pmod.md](pmod.md) — PMOD interface specification (standard Digilent types 1–6 + I2C extension)
- [rpi-hat-pmod.md](rpi-hat-pmod.md) — Digilent PMOD HAT adapter for Raspberry Pi (RPi GPIO ↔ PMOD pin mapping, type conformance)
- [pmod-tt.md](pmod-tt.md) — TinyTapeout PMOD connector standards (TT-specific layouts, RP2040/RP2350 GPIO mapping, community PMOD boards)

## Analysis

- [gpio-connectivity-analysis.md](gpio-connectivity-analysis.md) — GPIO scan results and connectivity verification across boards
