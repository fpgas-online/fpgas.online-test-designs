# fpgas-online Test Designs

Automated hardware verification designs for the [fpgas.online](https://fpgas.online) platform.

## Purpose

This repository contains LiteX-based FPGA test designs that run automatically during Raspberry Pi boot to verify that FPGA boards connected to the fpgas.online infrastructure are functioning correctly. Each test produces a clear pass/fail result over UART or other interfaces, enabling fully automated hardware health checks.

## Installing the Packages

CI builds the verification tools, and the bitstreams they check against, as Debian packages. Every green commit on `main` publishes them to the fpgas.online APT repository at <https://apt.fpgas.online> ([fpgas-online/apt](https://github.com/fpgas-online/apt)), which picks up new builds within about 15 minutes. Installing a board's tools package also installs its bitstreams and openFPGALoader.

| Board | Package |
|-------|---------|
| [Acorn CLE-215+ / CLE-101](docs/hardware/acorn.md#installing-the-acorn-packages) | `fpgas-online-acorn-tools` |

The other boards have no packages yet. Their bitstreams are the `all-bitstreams` artifact of the [Collect Bitstreams](.github/workflows/collect-bitstreams.yml) workflow.

**1. Add the repository** (once per host). It serves `bookworm` (Debian 12) and `trixie` (Debian 13). The packages are architecture-independent, so this works on Raspberry Pi OS and on an x86 machine alike:

```bash
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
sudo apt update
```

This is the setup every fpgas.online apt repository uses ([convention](https://github.com/mithro/apt-repo-action/blob/main/docs/conventions.md)). If you added the repository before 2026-09-24 using `pubkey.gpg` and `https://apt.fpgas.online <suite> main`, that path is now a frozen snapshot that gets no new packages. Remove it with `sudo rm /etc/apt/sources.list.d/fpgas-online.list /usr/share/keyrings/fpgas-online.gpg`, then run the commands above.

**2. Install your board's package** from the table above. For the Acorn:

```bash
sudo apt install fpgas-online-acorn-tools
```

The board's page, linked from the table, says what to run afterwards. To upgrade, run `sudo apt update && sudo apt upgrade`.

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

| Board | FPGA | Toolchain | Connection to Host | Status |
|-------|------|-----------|--------------------|--------|
| [Digilent Arty A7](docs/hardware/arty-a7.md) | Xilinx XC7A35T | openXC7 | USB JTAG+UART, PMOD HAT, Ethernet | Active |
| [Kosagi NeTV2](docs/hardware/netv2.md) | Xilinx XC7A35T | openXC7 | GPIO JTAG+UART, PCIe, Ethernet | Active |
| [Sqrl Acorn CLE-215+](docs/hardware/acorn.md) | Xilinx XC7A200T | openXC7 | GPIO JTAG+UART, PCIe | Active |
| [LiteFury](docs/hardware/acorn.md) | Xilinx XC7A100T | openXC7 | GPIO JTAG+UART, PCIe | Active |
| [Fomu EVT](docs/hardware/fomu-evt.md) | Lattice iCE40UP5K | Yosys + nextpnr-ice40 | USB, GPIO header | Active |
| [TT FPGA Demo Board](docs/hardware/tt-fpga.md) | Lattice iCE40UP5K | Yosys + nextpnr-ice40 | USB (via RP2350), PMOD HAT | Active |
| [Radiona ULX3S](docs/hardware/ulx3s.md) | Lattice ECP5 | Yosys + nextpnr-ecp5 | USB | Planned |
| [GSG ButterStick](docs/hardware/butterstick.md) | Lattice ECP5 | Yosys + nextpnr-ecp5 | USB, Ethernet | Planned |

## Test Matrix

| Test | Arty A7 | NeTV2 | Fomu EVT | TT FPGA | Acorn / LiteFury | ULX3S | ButterStick |
|------|---------|-------|----------|---------|------------------|-------|-------------|
| [GPIO Loopback](docs/tests/pmod-loopback.md) | Yes | Yes | Yes | Yes | Yes | — | — |
| [PMOD Pin ID](docs/tests/pmod-loopback.md) | Yes | Yes | Yes | Yes | Yes | — | — |
| [UART](docs/tests/uart.md) | Yes | Yes | Yes | Yes | Yes | — | — |
| [Ethernet](docs/tests/ethernet.md) | Yes | Yes | — | — | — | — | — |
| [PCIe Enumeration](docs/tests/pcie-enumeration.md) | — | Yes | — | — | Yes | — | — |
| [DDR Memory](docs/tests/ddr-memory.md) | Yes | Yes | — | — | Yes | — | — |
| [SPI Flash ID](docs/tests/spi-flash-id.md) | Yes | Yes | Yes | Yes | Yes | — | — |

See [docs/tests/](docs/tests/) for detailed test specifications.

## Documentation

- **[Hardware Reference](docs/hardware/)** — Board specs, pin mappings, host connections
  - [Welland Site](docs/hardware/site-welland.md) — Private test lab (Arty, NeTV2, Fomu, TT ASIC + TT FPGA on [tinytapeout.fpgas.online](https://tinytapeout.fpgas.online), 6× Acorn CLE-215+ on Pi 5)
  - [PS1 Site](docs/hardware/site-ps1.md) — Public fpgas.online service (Arty A7 boards)
  - [PMOD Interface Spec](docs/hardware/pmod.md) — Standard PMOD types and connector pinouts
  - [RPi PMOD HAT](docs/hardware/rpi-hat-pmod.md) — Raspberry Pi PMOD HAT adapter pin mapping
  - [TinyTapeout PMOD Standards](docs/hardware/pmod-tt.md) — TT-specific PMOD layouts and peripherals
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
