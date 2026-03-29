# Test Designs

FPGA test designs for automated hardware verification on the
[fpgas.online](https://fpgas.online) platform. Each design targets specific
hardware features and produces pass/fail results suitable for CI.

## Designs

| Design | Type | Tests | Boards |
|--------|------|-------|--------|
| [uart](uart/) | SoC | UART TX/RX echo via LiteX BIOS | Arty A7, NeTV2, Acorn, Fomu, TT FPGA |
| [ddr-memory](ddr-memory/) | SoC | DDR3 calibration and memtest | Arty A7, NeTV2, Acorn |
| [spi-flash-id](spi-flash-id/) | SoC | SPI Flash JEDEC ID readback | Arty A7, NeTV2, Acorn, Fomu, TT FPGA |
| [ethernet-test](ethernet-test/) | SoC | Ethernet MAC/PHY link and ping | Arty A7 (MII), NeTV2 (RMII) |
| [pcie-enumeration](pcie-enumeration/) | SoC | PCIe link training and enumeration | NeTV2, Acorn (CLE-215+/215/101) |
| [pmod-loopback](pmod-loopback/) | Gateware | GPIO loopback (directly wired pins) | Arty A7, NeTV2, TT FPGA |
| [pmod-pin-id](pmod-pin-id/) | Gateware | UART TX pin identification | Arty A7, Fomu, TT FPGA, Acorn |

## Shared Modules

| Directory | Purpose |
|-----------|---------|
| [_shared/](_shared/) | Reusable build helpers, platform fixups, and toolchain workarounds |
| [_host/](_host/) | Host-side test utilities for TT FPGA Demo Board |

## Design Types

**SoC designs** use a VexRiscv CPU with LiteX and require a cross compiler
(`gcc-riscv64-unknown-elf`) plus meson. They produce bitstreams that boot
firmware over UART or run embedded tests.

**Pure gateware designs** have no CPU. They use `platform.build()` directly
and only need the FPGA toolchain (openXC7 or Yosys+nextpnr-ice40).

## Building

All designs are built with `uv`:

```sh
uv sync --extra build
uv run python designs/<design>/gateware/<script>.py --toolchain openxc7 --build
```

Bitstreams are written to `designs/<design>/build/<board>/gateware/`.

## Supported Boards

| Board | FPGA | Package | Toolchain |
|-------|------|---------|-----------|
| Digilent Arty A7 | XC7A35T | CSG324 | openXC7 |
| Kosagi NeTV2 | XC7A35T / XC7A100T | FGG484 | openXC7 |
| SQRL Acorn CLE-215+ | XC7A200T | SBG484 | openXC7 |
| SQRL Acorn CLE-215 (NiteFury) | XC7A200T | FBG484 | openXC7 |
| SQRL Acorn CLE-101 (LiteFury) | XC7A100T | FGG484 | openXC7 |
| Fomu EVT | iCE40UP5K | UWG30 | Yosys+nextpnr-ice40 |
| TT FPGA Demo Board | iCE40UP5K | SG48 | Yosys+nextpnr-ice40 |
