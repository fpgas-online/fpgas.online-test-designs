# fpgas-online Test Designs

Automated hardware verification designs for the [fpgas.online](https://fpgas.online) platform.

## Purpose

This repository contains LiteX-based FPGA test designs that run automatically during Raspberry Pi boot to verify that FPGA boards connected to the fpgas.online infrastructure are functioning correctly. Each test produces a clear pass/fail result over UART or other interfaces, enabling fully automated hardware health checks.

## Installing the Packages

CI builds the boot-time board check, `fpgas-verify`, and the bitstreams it checks with, as Debian packages. Every green commit on `main` publishes them to the fpgas.online APT repository at <https://apt.fpgas.online> ([fpgas-online/apt](https://github.com/fpgas-online/apt)), which picks up new builds within about 15 minutes. At every boot, `fpgas-verify` loads the board's test bitstreams, runs their host tests, and checks the board and its flash against what it found last time.

**1. Add the repository** (once per host). It serves `bookworm` (Debian 12) and `trixie` (Debian 13). The packages are architecture-independent, so this works on Raspberry Pi OS and on an x86 machine alike:

```bash
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
sudo apt update
```

This is the setup every fpgas.online apt repository uses ([convention](https://github.com/mithro/apt-repo-action/blob/main/docs/conventions.md)). If you added the repository before 2026-09-24 using `pubkey.gpg` and `https://apt.fpgas.online <suite> main`, that path is now a frozen snapshot that gets no new packages. Remove it with `sudo rm /etc/apt/sources.list.d/fpgas-online.list /usr/share/keyrings/fpgas-online.gpg`, then run the commands above.

**2. Say which board the host has**, by installing exactly one of these:

| Install | The host has | If it is not found |
|---------|--------------|--------------------|
| `fpgas-online-<board>`, one of the boards below | that one board; nothing else is looked for | fatal |
| `fpgas-online-all-boards` | any one of the boards: every board's tools, and the one found is checked. For a netboot root shared by every Pi | fatal if none is found |
| `fpgas-online-multi-board` and the `fpgas-online-<board>-tools` you want | any one of the boards you chose | fatal if none is found |

| Board | Package | Its page |
|-------|---------|----------|
| Sqrl Acorn CLE-215+ / CLE-101 | `fpgas-online-acorn` | [acorn.md](docs/hardware/acorn.md#installing-the-acorn-packages) |
| Digilent Arty A7 | `fpgas-online-arty` | [arty-a7.md](docs/hardware/arty-a7.md#installing-the-arty-packages) |
| Kosagi NeTV2 | `fpgas-online-netv2` | [netv2.md](docs/hardware/netv2.md#installing-the-netv2-packages) |
| Fomu EVT | `fpgas-online-fomu` | [fomu-evt.md](docs/hardware/fomu-evt.md#installing-the-fomu-packages) |
| TT FPGA Demo Board | `fpgas-online-tt-fpga` | [tt-fpga.md](docs/hardware/tt-fpga.md#installing-the-tt-fpga-packages) |

For example, on an Arty's Pi:

```bash
sudo apt install fpgas-online-arty
```

These packages conflict with each other, so a host is never set up for two boards by accident: apt offers to remove the first board's package when you install another's. Each board's package brings only that board's tooling. It enables `fpgas-verify.service`, which runs at the next boot; it is not started on install, because it loads test designs into the board. To check the board now, run `sudo fpgas-verify`. When a check fails, install `fpgas-online-<board>-debug` for `fpgas-<board>-debug`, which runs each step by hand. To upgrade, run `sudo apt update && sudo apt upgrade`.

**What a check can say.** Only `pass` exits 0, and anything else also leaves `fpgas-verify.service` failed:

| Result | Meaning |
|--------|---------|
| `pass` | every test passed, and the board and its flash are the ones recorded |
| `driver-bound`, `degraded`, `unconverted` | Acorn only: a kernel driver (`litepcie.ko`) holds the board so it was not read; running its golden image; still on SQRL's factory image |
| `changed` | a different board, or a different flash, from last time. If you did that on purpose (flashed or swapped the board), run `sudo fpgas-verify --update` |
| `fail` | a test, a load or a flash comparison failed |
| `missing` | the board is not there |
| `error` | the check itself could not run: a missing tool, a damaged package, nothing configured |

The result is in `/run/fpgas-online/verify.json`, and is published as the `fpga-verified` fleet-event on fleet Pis (with `fleet-event` from `fpgas-online-setup-pi`; elsewhere the check warns and still reports). What `changed` compares is kept in `/var/lib/fpgas-online/verify-state.json`. On a netboot root that is in tmpfs, so each boot starts afresh. The design is in [docs/plans/2026-09-26-fpgas-online-verify-design.md](docs/plans/2026-09-26-fpgas-online-verify-design.md). The same code is the `fpgas_online_verify` Python package in [`verify/`](verify/), for PyPI later.

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
