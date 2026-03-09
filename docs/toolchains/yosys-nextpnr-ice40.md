# Yosys + nextpnr-ice40 Toolchain

## Target FPGAs

This toolchain targets the **Lattice iCE40** family of FPGAs. The iCE40 family
includes several sub-families:

| Sub-family | Notable Parts | Key Features |
|------------|---------------|--------------|
| iCE40LP    | LP1K, LP4K, LP8K | Low power |
| iCE40HX    | HX1K, HX4K, HX8K | Higher performance |
| iCE40UP    | UP5K           | Ultra-low power, SPRAM, DSP |
| iCE40UL    | UL1K           | Ultra-lite |

The **iCE40UP5K** is used by the [Fomu](https://github.com/im-tomu/fomu-hardware)
EVT board and the TinyTapeout FPGA (TT FPGA) board.

### iCE40UP5K Specifics

The iCE40UP5K is a popular choice for small open source designs. Key resources:

- **5280 logic cells** (4-input LUTs)
- **1 Mbit single-port RAM** (SPRAM) -- 4 blocks of 256 Kbit
- **120 Kbit dual-port RAM** (DPRAM / EBR) -- 30 blocks of 4 Kbit
- **8 DSP blocks** (SB_MAC16 multiply-accumulate units)
- **1 PLL**, **2 SPI**, **2 I2C** hard IP blocks
- **RGB LED driver** and **10-bit ADC**
- Packages: QFN-48, WLCSP

## Synthesis Flow

This is part of **Project IceStorm** -- the first fully reverse-engineered FPGA
toolchain. It is mature, well-tested, and widely used in the open source hardware
community.

```
Verilog / SystemVerilog
        |
        v
   +---------+
   |  Yosys  |   RTL synthesis (maps to iCE40 primitives)
   +---------+
        |  (JSON netlist)
        v
 +---------------+
 | nextpnr-ice40 |   Place & route (uses IceStorm chip database)
 +---------------+
        |  (ASC - textual bitstream)
        v
  +---------+
  | icepack |   Packs ASC text into binary bitstream
  +---------+
        |
        v
   bitstream.bin
```

### Component Sources

- **Yosys** -- RTL synthesis frontend. Source: <https://github.com/YosysHQ/yosys>
- **nextpnr** -- Place-and-route engine (build with `--ice40` flag for iCE40
  support). Source: <https://github.com/YosysHQ/nextpnr>
- **Project IceStorm** -- Reverse-engineered iCE40 chip database, plus `icepack`,
  `iceunpack`, `iceprog`, and related utilities.
  Source: <https://github.com/YosysHQ/icestorm>

## Installation

### From Package Managers

On many Linux distributions and macOS, the iCE40 toolchain is available from
package managers:

```bash
# Debian / Ubuntu
sudo apt install yosys nextpnr-ice40 fpga-icestorm

# macOS (Homebrew)
brew install yosys nextpnr icestorm
```

Package versions may lag behind upstream. For the latest features, build from
source.

### From Source

```bash
# 1. Build and install IceStorm
git clone https://github.com/YosysHQ/icestorm.git
cd icestorm
make -j$(nproc)
sudo make install

# 2. Build and install Yosys
git clone https://github.com/YosysHQ/yosys.git
cd yosys
make -j$(nproc)
sudo make install

# 3. Build and install nextpnr with iCE40 support
git clone https://github.com/YosysHQ/nextpnr.git
cd nextpnr
cmake -DARCH=ice40 -DICESTORM_INSTALL_PREFIX=/usr/local .
make -j$(nproc)
sudo make install
```

## LiteX Integration

The Yosys + nextpnr-ice40 toolchain is the **default toolchain** for iCE40-based
LiteX board targets. No special flags are needed:

```bash
python3 -m litex_boards.targets.fomu --build
```

Source: <https://github.com/litex-hub/litex-boards>

## Programming

### iceprog (SPI Flash)

`iceprog` is part of Project IceStorm and programs iCE40 devices over SPI using
an FTDI-based adapter:

```bash
iceprog bitstream.bin
```

Source: <https://github.com/YosysHQ/icestorm>

### dfu-util (USB DFU)

The Fomu board exposes a USB DFU bootloader, allowing programming without any
external adapter:

```bash
dfu-util -D bitstream.bin
```

Source: <https://dfu-util.sourceforge.net/>

The Fomu Workshop provides a detailed walkthrough of programming and interacting
with Fomu: <https://workshop.fomu.im>

### openFPGALoader

`openFPGALoader` is a universal FPGA programming utility that also supports
iCE40 boards:

```bash
openFPGALoader -b ice40_generic bitstream.bin
```

Source: <https://github.com/trabucayre/openFPGALoader>

## References

- Yosys: <https://github.com/YosysHQ/yosys>
- nextpnr: <https://github.com/YosysHQ/nextpnr>
- Project IceStorm: <https://github.com/YosysHQ/icestorm>
- Fomu Hardware: <https://github.com/im-tomu/fomu-hardware>
- Fomu Workshop: <https://workshop.fomu.im>
- openFPGALoader: <https://github.com/trabucayre/openFPGALoader>
