# Yosys + nextpnr-ecp5 Toolchain

## Target FPGAs

This toolchain targets the **Lattice ECP5** family of FPGAs. The ECP5 offers
significantly more resources than the iCE40 family, making it suitable for larger
designs including full Linux-capable SoCs.

### ECP5 Variants

| Part     | LUTs   | EBR (Kbit) | DSP Blocks | SERDES |
|----------|--------|------------|------------|--------|
| LFE5U-12F  | 12,000  | 576        | 28         | No     |
| LFE5U-25F  | 24,000  | 1,008      | 28         | No     |
| LFE5U-45F  | 44,000  | 1,944      | 64         | No     |
| LFE5U-85F  | 84,000  | 3,744      | 156        | No     |
| LFE5UM5G-25F | 24,000 | 1,008    | 28         | Yes    |
| LFE5UM5G-45F | 44,000 | 1,944    | 64         | Yes    |
| LFE5UM5G-85F | 84,000 | 3,744    | 156        | Yes    |

The **5G variants** include multi-gigabit SERDES transceivers, enabling high-speed
serial interfaces.

### Boards Using ECP5

- **ULX3S** -- Open source ECP5 development board with SDRAM, HDMI, and WiFi.
  Source: <https://radiona.org/ulx3s/>
- **ButterStick** -- ECP5 board with PCIe edge connector and Ethernet.
  Source: <https://butterstick.io>

## Synthesis Flow

This toolchain is part of **Project Trellis**, which provides a reverse-engineered
database of the ECP5 bitstream format.

```
Verilog / SystemVerilog
        |
        v
   +---------+
   |  Yosys  |   RTL synthesis (maps to ECP5 primitives)
   +---------+
        |  (JSON netlist)
        v
 +--------------+
 | nextpnr-ecp5 |   Place & route (uses Project Trellis chip database)
 +--------------+
        |  (textual bitstream)
        v
  +---------+
  | ecppack |   Packs into binary bitstream (.bit) or compressed bitstream
  +---------+
        |
        v
   bitstream.bit
```

### Component Sources

- **Yosys** -- RTL synthesis frontend. Source: <https://github.com/YosysHQ/yosys>
- **nextpnr** -- Place-and-route engine (build with `--ecp5` flag for ECP5
  support). Source: <https://github.com/YosysHQ/nextpnr>
- **Project Trellis** -- Reverse-engineered ECP5 device database and the `ecppack`
  bitstream packing utility. Source: <https://github.com/YosysHQ/prjtrellis>

## Installation

### From Package Managers

```bash
# Debian / Ubuntu
sudo apt install yosys nextpnr-ecp5 prjtrellis

# macOS (Homebrew)
brew install yosys nextpnr
```

Package availability varies by distribution. For full ECP5 support, building from
source is often necessary.

### From Source

```bash
# 1. Build and install Project Trellis
git clone --recursive https://github.com/YosysHQ/prjtrellis.git
cd prjtrellis/libtrellis
cmake .
make -j$(nproc)
sudo make install

# 2. Build and install Yosys
git clone https://github.com/YosysHQ/yosys.git
cd yosys
make -j$(nproc)
sudo make install

# 3. Build and install nextpnr with ECP5 support
git clone https://github.com/YosysHQ/nextpnr.git
cd nextpnr
cmake -DARCH=ecp5 -DTRELLIS_INSTALL_PREFIX=/usr/local .
make -j$(nproc)
sudo make install
```

Note: The `--recursive` flag is required when cloning Project Trellis to fetch
the device database submodule.

## LiteX Integration

The Yosys + nextpnr-ecp5 toolchain is the **default toolchain** for ECP5-based
LiteX board targets:

```bash
# ULX3S example
python3 -m litex_boards.targets.radiona_ulx3s --build

# ButterStick example
python3 -m litex_boards.targets.gsd_butterstick --build
```

No `--toolchain` flag is needed because the open source flow is the default for
ECP5 targets in LiteX.

Source: <https://github.com/litex-hub/litex-boards>

## Programming

### openFPGALoader

`openFPGALoader` is a universal programming tool that supports ECP5 boards
natively:

```bash
# Program to SRAM (volatile, lost on power cycle)
openFPGALoader -b ulx3s bitstream.bit

# Program to SPI flash (non-volatile)
openFPGALoader -b ulx3s -f bitstream.bit
```

Source: <https://github.com/trabucayre/openFPGALoader>

### ecpprog

`ecpprog` is a lightweight ECP5 programming tool, particularly suited for use
with FTDI-based adapters:

```bash
ecpprog bitstream.bit
```

## References

- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr: <https://github.com/YosysHQ/nextpnr>
- Project Trellis: <https://github.com/YosysHQ/prjtrellis>
- ULX3S: <https://radiona.org/ulx3s/>
- ButterStick: <https://butterstick.io>
- openFPGALoader: <https://github.com/trabucayre/openFPGALoader>
