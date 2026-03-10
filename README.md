# fpgas-online Test Designs

Automated hardware verification designs for the [fpgas.online](https://fpgas.online) platform.

## Purpose

This repository contains LiteX-based FPGA test designs that run automatically during Raspberry Pi boot to verify that FPGA boards connected to the fpgas.online infrastructure are functioning correctly. Each test produces a clear pass/fail result over UART or other interfaces, enabling fully automated hardware health checks.

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│   GitHub Actions     │     │   Raspberry Pi Host   │
│                     │     │                      │
│  LiteX + openXC7/   │────▶│  Pre-built bitstream  │
│  Yosys+nextpnr      │     │  loaded at boot       │
│  build bitstreams    │     │                      │
└─────────────────────┘     │  Test harness script  │
                            │  drives verification  │
                            │         │             │
                            └─────────┼─────────────┘
                                      │
                              ┌───────┴───────┐
                              │  FPGA Board   │
                              │               │
                              │  Test design  │
                              │  responds to  │
                              │  host queries │
                              └───────────────┘
```

**Flow:**
1. GitHub Actions builds bitstreams using open source toolchains (no vendor tools required)
2. Pre-built bitstreams are deployed to Raspberry Pi hosts
3. On boot, the RPi programs the attached FPGA and runs verification tests
4. Test results are collected and reported

## Supported Boards

| Board                                                | FPGA               | Toolchain              | Connection to Host                    | Status  |
|------------------------------------------------------|--------------------|------------------------|---------------------------------------|---------|
| [Digilent Arty A7](docs/hardware/arty-a7.md)         | Xilinx Artix-7     | openXC7                | USB-UART + PMOD HAT + Ethernet        | Active  |
| [Kosagi NeTV2](docs/hardware/netv2.md)               | Xilinx Artix-7     | openXC7                | GPIO (JTAG+UART) + PCIe + Ethernet    | Active  |
| [Fomu EVT](docs/hardware/fomu-evt.md)                | Lattice iCE40UP5K  | Yosys + nextpnr-ice40  | USB                                   | Active  |
| [TT FPGA Demo Board](docs/hardware/tt-fpga.md)       | Lattice iCE40UP5K  | Yosys + nextpnr-ice40  | USB (via RP2040)                      | Active  |
| [Radiona ULX3S](docs/hardware/ulx3s.md)              | Lattice ECP5       | Yosys + nextpnr-ecp5   | USB                                   | Planned |
| [GSG ButterStick](docs/hardware/butterstick.md)      | Lattice ECP5       | Yosys + nextpnr-ecp5   | USB + Ethernet                        | Planned |

## Test Matrix

| Test                                                  | Arty A7 | NeTV2 (RPi5) | NeTV2 (RPi3) | Fomu EVT | TT FPGA | ULX3S | ButterStick |
|-------------------------------------------------------|---------|--------------|--------------|----------|---------|-------|-------------|
| [GPIO Loopback](docs/tests/pmod-loopback.md)          | Yes     | Yes          | Yes          | Yes      | Yes     | -     | -           |
| [UART](docs/tests/uart.md)                            | Yes     | Yes          | Yes          | Yes      | Yes     | -     | -           |
| [Ethernet](docs/tests/ethernet.md)                    | Yes     | Yes          | -            | -        | -       | -     | Plan        |
| [PCIe Enumeration](docs/tests/pcie-enumeration.md)    | -       | Yes          | -            | -        | -       | -     | -           |
| [DDR Memory](docs/tests/ddr-memory.md)                | Yes     | Yes          | Yes          | -        | -       | Plan  | Plan        |
| [SPI Flash ID](docs/tests/spi-flash-id.md)            | Yes     | Yes          | Yes          | Yes      | Yes     | Plan  | Plan        |

See [docs/tests/](docs/tests/) for detailed test specifications.

## Documentation

- **[Hardware Reference](docs/hardware/)** — Board specs, pin mappings, host connections
  - [Infrastructure Overview](docs/hardware/infrastructure.md) — Host machines, SSH access, programming tools
  - [PMOD HAT](docs/hardware/pmod-hat.md) — Raspberry Pi PMOD HAT adapter
- **[Test Specifications](docs/tests/)** — What each test verifies and how
- **[Toolchain Guides](docs/toolchains/)** — Building bitstreams with open source tools
  - [openXC7](docs/toolchains/openxc7.md) — For Xilinx 7-Series (Arty, NeTV2)
  - [Yosys + nextpnr-ice40](docs/toolchains/yosys-nextpnr-ice40.md) — For iCE40 (Fomu, TT FPGA)
  - [Yosys + nextpnr-ecp5](docs/toolchains/yosys-nextpnr-ecp5.md) — For ECP5 (ULX3S, ButterStick)
  - [GitHub Actions CI](docs/toolchains/github-actions.md) — Automated bitstream builds
- **[Resources](docs/resources.md)** — Links to repos, datasheets, examples

## Toolchains

All designs use fully open source FPGA toolchains:

- **Xilinx 7-Series** (Arty A7, NeTV2): [openXC7](https://github.com/openXC7) — Yosys + nextpnr-xilinx + Project X-Ray
- **Lattice iCE40** (Fomu, TT FPGA): Yosys + nextpnr-ice40 + Project IceStorm
- **Lattice ECP5** (ULX3S, ButterStick): Yosys + nextpnr-ecp5 + Project Trellis

## License

Apache 2.0
