\[[top](./README.md)\] \[[spec](./acorn.md)\] \[[wiring](./acorn-wiring-guide.md)\]

# Sqrl Acorn CLE-215+ / LiteFury Pinmap

Pinmap for the Sqrl Acorn CLE-215+ (and compatible NiteFury / LiteFury boards) as connected in the fpgas.online test infrastructure. The Acorn connects to the RPi 5 via an mPCIe HAT for PCIe, with two Pico-EZmate cables adapted to pin headers for JTAG and UART/GPIO access via the RPi's 40-pin GPIO header.

## Board Connectors

The Acorn exposes two 6-pin Molex Pico-EZmate connectors:

- **P1**: JTAG (programming and debug)
- **P2**: Serial / GPIO (UART and spare I/O)

Each connector uses a [Molex Pico-EZmate 6-pin cable](https://www.digikey.fr/en/products/detail/molex/0369200601/10233018), cut in half and soldered to a 2x3 pin header for connection to the RPi GPIO header.

Source: [LiteX Acorn CLE-215 wiki](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)

## P2: Serial / GPIO Connector

The P2 connector provides UART and 2 spare GPIO pins.

### FPGA Pins

| P2 Pin | FPGA Pin | Function     | I/O Standard |
|--------|----------|--------------|--------------|
| 1      | K2       | Serial TX    | LVCMOS33     |
| 2      | J2       | Serial RX    | LVCMOS33     |
| 3      | J5       | Spare GPIO 0 | LVCMOS33     |
| 4      | H5       | Spare GPIO 1 | LVCMOS33     |
| 5      | GND      | Ground       | —            |
| 6      | VCC      | 3.3V         | —            |

### RPi GPIO Header Connection

The P2 pin header connects to RPi header pins 5-10 (adjacent to the mPCIe HAT):

| P2 Pin | Function     | FPGA Pin | RPi Header Pin | RPi GPIO     | BCM Function |
|--------|--------------|----------|----------------|--------------|--------------|
| 1      | Serial TX    | K2       | 8              | GPIO14       | TXD0         |
| 2      | Serial RX    | J2       | 10             | GPIO15       | RXD0         |
| 3      | Spare GPIO 0 | J5       | 5              | GPIO3        | I2C1_SCL     |
| 4      | Spare GPIO 1 | H5       | 7              | GPIO4        | GPCLK0       |
| 5      | GND          | —        | 6              | GND          | —            |
| 6      | VCC (3.3V)   | —        | 9              | GND          | —            |

The UART pins (K2/J2) connect to the RPi's hardware UART (GPIO14/15 = `/dev/ttyAMA0`), enabling direct serial communication without USB adapters.

| Parameter | Value                    |
|-----------|--------------------------|
| Device    | `/dev/ttyAMA0`           |
| Baud rate | 115200                   |
| Pre-test  | `systemctl stop serial-getty@ttyAMA0` |

## P1: JTAG Connector

The P1 connector provides standard Xilinx JTAG signals.

### RPi GPIO Header Connection

The P1 pin header connects to RPi SPI0 pins (header pins 19-26):

| P1 Pin | JTAG Signal | RPi Header Pin | RPi GPIO | BCM Function |
|--------|-------------|----------------|----------|--------------|
| 1      | TCK         | 23             | GPIO11   | SPI0_SCLK    |
| 2      | TDI         | 19             | GPIO10   | SPI0_MOSI    |
| 3      | TDO         | 21             | GPIO9    | SPI0_MISO    |
| 4      | TMS         | 24             | GPIO8    | SPI0_CE0     |
| 5      | GND         | 25             | GND      | —            |
| 6      | VCC (3.3V)  | 26             | GPIO7    | SPI0_CE1     |

JTAG signals are mapped to the RPi's SPI0 pins for compatibility with openFPGALoader's SPI-based JTAG transport. The SPI kernel modules must be unloaded before use (`rmmod spidev spi_bcm2835`).

### Additional JTAG Header Pins

| RPi Header Pin | RPi GPIO | Function                |
|----------------|----------|-------------------------|
| 20             | GND      | Ground                  |
| 22             | GPIO25   | Spare (unused by JTAG)  |

## Programming

### Via JTAG (openFPGALoader)

Using the SPI0-mapped JTAG pins:

```bash
# Unload SPI kernel modules first
rmmod spidev spi_bcm2835

# Program volatile (SRAM)
openFPGALoader --cable <tbd> <bitstream>

# Program persistent (SPI flash)
openFPGALoader --cable <tbd> --write-flash <bitstream>
```

### Via PCIe (LitePCIe)

When a LiteX bitstream with PCIe support is already loaded:

```bash
litepcie_util flash_write <bitstream>
```

## Compatible Boards

The Acorn CLE-215+ is pin-compatible with the [NiteFury and LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury) boards from RHSResearch:

| Board        | FPGA            | Speed Grade | DDR3   | PCIe    |
|--------------|-----------------|-------------|--------|---------|
| LiteFury     | XC7A100T-FBG484 | -2          | 512 MB | Gen2 x4 |
| NiteFury     | XC7A200T-FBG484 | -2          | 512 MB | Gen2 x4 |
| Acorn CLE-215  | XC7A200T-FBG484 | -2        | 1 GB   | Gen2 x4 |
| Acorn CLE-215+ | XC7A200T-FBG484 | -3        | 1 GB   | Gen2 x4 |

All boards share the same PCB layout and pin assignments. The Acorn CLE-215+ differs from NiteFury only in DDR3 capacity (1 GB vs 512 MB). The LiteFury uses a smaller XC7A100T FPGA.

LiteX platform files: `sqrl_acorn.py` works for all variants — change only the device string. See [LiteX Acorn CLE-215 wiki](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215).

## References

- LiteX wiki: [Use LiteX on the Acorn CLE-215](https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215)
- NiteFury/LiteFury: [RHSResearchLLC/NiteFury-and-LiteFury](https://github.com/RHSResearchLLC/NiteFury-and-LiteFury)
- LiteX platform: [sqrl_acorn.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sqrl_acorn.py)
- OpenOCD flashing: [NiteFury/Acorn flashing guide](https://github.com/Gbps/nitefury-openocd-flashing-guide)
- Acorn hardware doc: [acorn.md](acorn.md)
