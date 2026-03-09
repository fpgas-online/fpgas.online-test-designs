# openXC7 Toolchain

## What is openXC7

openXC7 is a fully open source FPGA toolchain targeting **Xilinx 7-Series** devices,
including Artix-7, Kintex-7, Spartan-7, and Zynq-7000 families. It combines several
open source projects into a coherent synthesis-to-bitstream flow, removing the need
for Xilinx Vivado in many use cases.

The project is funded by **NLnet** under the NGI Assure program and is hosted at
<https://github.com/openXC7>.

## Supported Devices

| Family    | Example Parts              |
|-----------|----------------------------|
| Artix-7   | XC7A35T, XC7A100T, XC7A200T |
| Kintex-7  | XC7K70T, XC7K325T         |
| Spartan-7 | XC7S25, XC7S50             |
| Zynq-7000 | XC7Z010, XC7Z020           |

Device support is determined by the availability of data in the
[Project X-Ray](https://github.com/chipsalliance/prjxray) database. Not every
speed grade or package variant has complete coverage; check the Project X-Ray
repository for current status.

## Synthesis Flow

The openXC7 flow consists of four stages:

```
Verilog / SystemVerilog
        |
        v
   +---------+
   |  Yosys  |   RTL synthesis (maps design to FPGA primitives)
   +---------+
        |  (JSON netlist)
        v
 +----------------+
 | nextpnr-xilinx |   Place & route (uses Project X-Ray device database)
 +----------------+
        |  (FASM - FPGA Assembly)
        v
  +-------------+
  | fasm2frames |   Converts FASM text to configuration frame data
  +-------------+
        |  (frames)
        v
 +----------------+
 | xc7frames2bit  |   Packs frames into a Xilinx-compatible .bit bitstream
 +----------------+
        |
        v
   bitstream.bit
```

### Component Sources

- **Yosys** -- RTL synthesis frontend supporting Verilog, SystemVerilog, and VHDL
  (via the GHDL plugin). Source: <https://github.com/YosysHQ/yosys>
- **nextpnr-xilinx** -- Place-and-route engine with Xilinx 7-Series backend.
  Source: <https://github.com/openXC7/nextpnr-xilinx>
- **Project X-Ray** -- Reverse-engineered device database describing the bitstream
  format of Xilinx 7-Series FPGAs. Source: <https://github.com/chipsalliance/prjxray>
- **fasm2frames** and **xc7frames2bit** -- Bitstream assembly utilities distributed
  as part of Project X-Ray.

## Installation

### From Source (toolchain-installer)

The recommended approach is the openXC7 toolchain installer, which builds and
installs all components to `/opt/openxc7`:

```bash
git clone https://github.com/openXC7/toolchain-installer.git
cd toolchain-installer
make
```

Source: <https://github.com/openXC7/toolchain-installer>

After installation, add `/opt/openxc7/bin` to your `PATH`:

```bash
export PATH="/opt/openxc7/bin:$PATH"
```

### Docker

A pre-built Docker container is available that includes the openXC7 toolchain
together with LiteX:

```bash
docker run -it ghcr.io/meriac/openxc7-litex:latest
```

Source: <https://github.com/tiiuae/OpenXC7-LiteX>

This container is particularly useful for CI pipelines and for users who do not
want to build the toolchain from source.

### ARM Support

The openXC7 toolchain can be compiled and run on ARM platforms, including
Raspberry Pi. This is useful for on-device builds where the RPi is directly
connected to the FPGA board via JTAG or SPI, enabling a self-contained
build-and-program workflow without a separate x86 host.

## LiteX Integration

When building LiteX SoC targets for Xilinx 7-Series boards, pass the
`--toolchain yosys+nextpnr` flag to select the openXC7 flow instead of Vivado:

```bash
python3 -m litex_boards.targets.digilent_arty --toolchain yosys+nextpnr --build
```

LiteX will invoke Yosys for synthesis, nextpnr-xilinx for place and route, and
the FASM utilities for bitstream generation automatically.

Source: <https://github.com/enjoy-digital/litex>, <https://github.com/litex-hub/litex-boards>

## Example Build Command

A minimal example targeting the Digilent Arty A7 board:

```bash
# Ensure openXC7 tools are on PATH
export PATH="/opt/openxc7/bin:$PATH"

# Build a LiteX SoC with the open source toolchain
python3 -m litex_boards.targets.digilent_arty \
    --toolchain yosys+nextpnr \
    --build
```

The resulting bitstream will be located in the `build/digilent_arty/gateware/`
directory.

## References

- openXC7 organization: <https://github.com/openXC7>
- Toolchain installer: <https://github.com/openXC7/toolchain-installer>
- OpenXC7-LiteX Docker: <https://github.com/tiiuae/OpenXC7-LiteX>
- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr-xilinx: <https://github.com/openXC7/nextpnr-xilinx>
- Project X-Ray: <https://github.com/chipsalliance/prjxray>
- NLnet NGI Assure: <https://nlnet.nl/assure/>
