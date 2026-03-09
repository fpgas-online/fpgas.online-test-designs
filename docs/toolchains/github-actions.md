# Building FPGA Bitstreams with GitHub Actions

## Overview

FPGA bitstream synthesis is a compute-only process -- no FPGA hardware is needed
during the build step. This makes GitHub Actions runners well suited for
building bitstreams as part of a CI/CD pipeline. The resulting bitstream artifacts
can then be deployed to Raspberry Pi hosts that have physical FPGA boards attached
for hardware-in-the-loop (HIL) testing.

Source: <http://pepijndevos.nl/2026/02/17/hardware-in-the-loop-continuous-integration-for-fpga-tools.html>

## Strategy

The CI pipeline separates two concerns:

1. **Build** (GitHub-hosted runners) -- Install toolchains, synthesize bitstreams,
   upload artifacts.
2. **Test** (self-hosted RPi runners) -- Download artifacts, program FPGA boards,
   run hardware tests.

This separation means the build step scales with GitHub's infrastructure, while
hardware testing runs on dedicated self-hosted machines that have FPGA boards
physically connected.

## Workflow Structure

A typical workflow uses a **matrix build** with one job per board or FPGA family:

```yaml
name: Build FPGA Bitstreams

on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - board: digilent_arty
            toolchain: openxc7
            family: xc7
          - board: fomu_evt
            toolchain: icestorm
            family: ice40
          - board: radiona_ulx3s
            toolchain: trellis
            family: ecp5

    steps:
      - uses: actions/checkout@v4

      - name: Install toolchain
        run: |
          case "${{ matrix.toolchain }}" in
            openxc7)
              # Install openXC7 from toolchain-installer
              git clone https://github.com/openXC7/toolchain-installer.git
              cd toolchain-installer && make
              echo "/opt/openxc7/bin" >> $GITHUB_PATH
              ;;
            icestorm)
              sudo apt-get update
              sudo apt-get install -y yosys nextpnr-ice40 fpga-icestorm
              ;;
            trellis)
              sudo apt-get update
              sudo apt-get install -y yosys nextpnr-ecp5 prjtrellis
              ;;
          esac

      - name: Build bitstream
        run: |
          python3 -m litex_boards.targets.${{ matrix.board }} \
            --build \
            ${{ matrix.family == 'xc7' && '--toolchain yosys+nextpnr' || '' }}

      - name: Upload bitstream artifact
        uses: actions/upload-artifact@v4
        with:
          name: bitstream-${{ matrix.board }}
          path: build/${{ matrix.board }}/gateware/*.bit
```

## Toolchain Installation in CI

### openXC7 (Xilinx 7-Series)

Two approaches:

**Option 1: Build from source**

```yaml
- name: Install openXC7
  run: |
    git clone https://github.com/openXC7/toolchain-installer.git
    cd toolchain-installer && make
    echo "/opt/openxc7/bin" >> $GITHUB_PATH
```

Source: <https://github.com/openXC7/toolchain-installer>

**Option 2: Docker container**

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/meriac/openxc7-litex:latest
    steps:
      - uses: actions/checkout@v4
      - name: Build
        run: python3 -m litex_boards.targets.digilent_arty --toolchain yosys+nextpnr --build
```

Source: <https://github.com/tiiuae/OpenXC7-LiteX>

The Docker approach avoids lengthy compilation and provides a reproducible
environment.

### iCE40 (Lattice iCE40)

```yaml
- name: Install iCE40 toolchain
  run: |
    sudo apt-get update
    sudo apt-get install -y yosys nextpnr-ice40 fpga-icestorm
```

For newer tool versions, build from source:
- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr: <https://github.com/YosysHQ/nextpnr> (build with `-DARCH=ice40`)
- IceStorm: <https://github.com/YosysHQ/icestorm>

### ECP5 (Lattice ECP5)

```yaml
- name: Install ECP5 toolchain
  run: |
    sudo apt-get update
    sudo apt-get install -y yosys nextpnr-ecp5 prjtrellis
```

For newer tool versions, build from source:
- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr: <https://github.com/YosysHQ/nextpnr> (build with `-DARCH=ecp5`)
- Project Trellis: <https://github.com/YosysHQ/prjtrellis>

## openFPGALoader

[openFPGALoader](https://github.com/trabucayre/openFPGALoader) is a universal
open source FPGA programming utility. It supports boards from Xilinx, Lattice,
Intel, Gowin, and other vendors, making it the recommended tool for deploying
bitstreams to hardware in the test phase of the pipeline.

### Installation

```bash
sudo apt-get install -y openfpgaloader
```

Or build from source: <https://github.com/trabucayre/openFPGALoader>

### Usage

```bash
# Program to SRAM (volatile)
openFPGALoader -b <board> bitstream.bit

# Program to flash (non-volatile)
openFPGALoader -b <board> -f bitstream.bit
```

Supported board names include `arty_a7_35t`, `ulx3s`, `ice40_generic`,
`butterstick`, and many others. Run `openFPGALoader --list-boards` for the full
list.

## Docker-Based Builds

The [OpenXC7-LiteX](https://github.com/tiiuae/OpenXC7-LiteX) project provides
Docker containers with the openXC7 toolchain and LiteX pre-installed. This is
useful for:

- Reproducible CI builds without compiling the toolchain each run
- Local development that matches the CI environment exactly
- Quick experimentation without installing tools on the host

```bash
docker run -it -v $(pwd):/work ghcr.io/meriac/openxc7-litex:latest
```

For a broader approach to containerized hardware CI, see the
[Baremetal CI Docker](https://github.com/BareMetalTestLab/baremetal-ci-docker)
project, which provides Docker containers for managing self-hosted runners with
hardware access.

## Reference Projects

- **TinyTapeout FPGA HDL Demo** -- A CI pipeline that builds FPGA designs for the
  TinyTapeout FPGA board. Source: <https://github.com/efabless/tt-fpga-hdl-demo>
- **Baremetal CI Docker** -- Docker containers for hardware-in-the-loop CI with
  self-hosted runners. Source: <https://github.com/BareMetalTestLab/baremetal-ci-docker>
- **Pepijn de Vos HIL CI blog post** -- Describes the architecture of
  hardware-in-the-loop continuous integration for FPGA tools.
  Source: <http://pepijndevos.nl/2026/02/17/hardware-in-the-loop-continuous-integration-for-fpga-tools.html>
- **Ferrous Systems HIL Testing** -- General guide to hardware-in-the-loop testing
  with GitHub Actions self-hosted runners.
  Source: <https://ferrous-systems.com/blog/gha-hil-tests/>

## References

- openXC7: <https://github.com/openXC7>
- openXC7 Toolchain Installer: <https://github.com/openXC7/toolchain-installer>
- OpenXC7-LiteX Docker: <https://github.com/tiiuae/OpenXC7-LiteX>
- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr: <https://github.com/YosysHQ/nextpnr>
- Project X-Ray: <https://github.com/chipsalliance/prjxray>
- Project IceStorm: <https://github.com/YosysHQ/icestorm>
- Project Trellis: <https://github.com/YosysHQ/prjtrellis>
- openFPGALoader: <https://github.com/trabucayre/openFPGALoader>
