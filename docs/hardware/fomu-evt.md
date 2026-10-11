\[[top](./README.md)\] \[[pinmap](./fomu-pin-mapping.md)\] \[[buy](https://www.crowdsupply.com/sutajio-kosagi/fomu)\] \[[litex](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)\]

# Fomu EVT (Engineering Validation Test)

The Fomu is a tiny FPGA board that fits inside a USB port, designed by Sean Cross (xobs) and Tim Ansell. The EVT (Engineering Validation Test) revision is used in the fpgas.online test infrastructure. It uses a Lattice iCE40UP5K FPGA with native USB connectivity.

## Installing the Fomu Packages

### What you need

- a Raspberry Pi with the Fomu EVT on its GPIO header ([Fomu EVT wiring to a Raspberry Pi](https://docs.fpgas.online/en/latest/boards/fomu-evt/setup/wiring.html#connections-to-the-pi))
- the fpgas.online apt repository added on the Pi ([fpgas-verify: installing it](../verify/installing.md#installing))
- on bookworm: the fpgas.online-fpga-tools apt repository added too ([fpgas-verify: installing it](../verify/installing.md#installing) has it). Debian bookworm's openFPGALoader is too old for the check

`grep VERSION_CODENAME /etc/os-release` says which release the Pi runs.

### Steps

**1.** Install the Fomu's packages. This also turns the check at boot on (`fpgas-verify.service`).

```bash
sudo apt install fpgas-online-fomu
```

**2.** Check the board now. Nothing is sent to the site: `--no-publish` makes sure.

```bash
sudo fpgas-fomu-verify --no-publish
```

### Check

The first line of the output starts with `fpgas-verify: pass`. The board's line under it ends in `pass`, and so does the line of each test.

### If it fails

- The first line names the result, and the output ends with `RESULT:` and `What to do:`. [fpgas-verify: reading the result](../verify/reading-the-result.md#reading-the-result) says what each result means.
- [fpgas-verify: common failures](../verify/common-failures.md#common-failures) lists the messages and what to do about each.
- To run one test with its output live, install `fpgas-online-fomu-debug` and run it:

```bash
sudo fpgas-fomu-debug test spiflash
```

### Next

- [The Fomu EVT check at boot](../verify/tests.md#the-fomu-evt-check-at-boot): what the check does, test by test.
- [Fomu EVT packages](../verify/installing.md#fomu-evt-packages): what each package installs.
- [fpgas-verify: reading the result](../verify/reading-the-result.md#reading-the-result): the report, `changed` and `--update`.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K-SG48 |
| Package | SG48 (48-pin QFN) |
| Logic cells | 5,280 LUT4s |
| SPRAM | 128 KB (4 x 32 KB blocks) |
| DPRAM (EBR) | 120 Kbit (15 x 8 Kbit blocks) |
| DSP blocks | 8 (16x16 multiply-accumulate) |
| System clock | 48 MHz (pin 44, LVCMOS33) |
| Internal oscillators | 48 MHz HFOSC, 10 kHz LFOSC |
| USB | Native USB 1.1 Full Speed (ValentyUSB core) |
| SPI Flash | Quad SPI for bitstream storage |
| RGB LED | 1 (active-low, pins R=40, G=39, B=41) |
| Touch pads | 4 (pins 48, 47, 46, 45) |
| PMOD connectors | 2 half-PMOD (4 signal pins each) |
| External SDRAM | None (SPRAM only) |
| Form factor | Fits inside a USB Type-A port |

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py), [Fomu Hardware repo](https://github.com/im-tomu/fomu-hardware)

## USB Interface

The Fomu connects directly to a USB port and implements a full USB 1.1 Full Speed device using the ValentyUSB soft core on the iCE40UP5K. No external USB PHY is needed -- the iCE40UP5K has dedicated USB I/O pins.

| Signal | FPGA Pin | Description |
|--------|----------|-------------|
| D+ | 34 | USB data positive |
| D- | 37 | USB data negative |
| Pullup | 35 | 1.5K pullup for Full Speed identification |
| Pulldown | 36 | Pulldown resistor control |

All USB pins use LVCMOS33 I/O standard.

The USB interface supports DFU (Device Firmware Upgrade) for bitstream loading, as well as acting as a CDC-ACM serial port or custom USB device depending on the loaded design.

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## Serial (UART)

The EVT board has a serial port that can be used for debugging. In practice, the USB interface (CDC-ACM or DFU) is the primary communication channel.

| Signal | FPGA Pin | I/O Standard | Notes |
|--------|----------|-------------|-------|
| RX | 21 | LVCMOS33 | |
| TX | 13 | LVCMOS33 | Has PULLUP |

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## SPI Flash

The Fomu stores its bitstream in an external SPI flash. The iCE40UP5K loads the bitstream from flash automatically on power-up.

| Signal | FPGA Pin | I/O Standard |
|--------|----------|-------------|
| CS_N | 16 | LVCMOS33 |
| CLK | 15 | LVCMOS33 |
| MOSI (DQ0) | 14 | LVCMOS33 |
| MISO (DQ1) | 17 | LVCMOS33 |
| WP (DQ2) | 18 | LVCMOS33 |
| HOLD (DQ3) | 19 | LVCMOS33 |

Quad SPI (4x) mode is supported.

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## RGB LED

The Fomu has a single RGB LED driven by the iCE40UP5K's internal LED driver IP (active-low accent LED and SB_RGBA_DRV primitive).

| Color | FPGA Pin | Active |
|-------|----------|--------|
| Red | 40 | Low |
| Green | 39 | Low |
| Blue | 41 | Low |

The `user_led_n` signal (active-low) is on pin 41 (blue).

## Touch Pads

The EVT board has 4 capacitive touch pads that can be used as user inputs.

| Pad | FPGA Pin |
|-----|----------|
| Touch 0 | 48 |
| Touch 1 | 47 |
| Touch 2 | 46 |
| Touch 3 | 45 |

These are directly connected to FPGA I/O pins. Capacitive touch sensing is implemented in the FPGA fabric.

## Buttons

Two active-low buttons:

| Button | FPGA Pin | I/O Standard |
|--------|----------|-------------|
| BTN0 | 42 | LVCMOS33 |
| BTN1 | 38 | LVCMOS33 |

## PMOD Connectors

The EVT board has two half-PMOD connectors (4 signal pins each, active-low accent accent accent -- standard 6-pin PMOD with 4 signals + GND + VCC).

### PMODA_N

| Index | FPGA Pin |
|-------|----------|
| 0 | 28 |
| 1 | 27 |
| 2 | 26 |
| 3 | 23 |

### PMODB_N

| Index | FPGA Pin |
|-------|----------|
| 0 | 48 |
| 1 | 47 |
| 2 | 46 |
| 3 | 45 |

Note: PMODB_N shares pins with the touch pads.

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## I2C

| Signal | FPGA Pin | I/O Standard |
|--------|----------|-------------|
| SCL | 12 | LVCMOS18 |
| SDA | 20 | LVCMOS18 |

Note the I2C interface uses LVCMOS18 (1.8V) rather than the 3.3V used by other I/O.

## Debug Header

| Index | FPGA Pin |
|-------|----------|
| 0 | 20 |
| 1 | 12 |
| 2 | 11 |
| 3 | 25 |
| 4 | 10 |
| 5 | 9 |

## Programming

### USB DFU (primary method)

The Fomu is programmed via USB using the DFU (Device Firmware Upgrade) protocol. The `dfu-util` tool is used:

```bash
# List connected DFU devices
dfu-util -l

# Program a bitstream
dfu-util -D design.dfu

# Program with explicit device selection
dfu-util -d 1209:5bf0 -D design.dfu
```

The DFU bootloader resides in the SPI flash and provides a USB DFU interface when no valid application is present or when the user triggers DFU mode.

### IceStorm Programmer (iceprog)

For direct SPI flash programming (requires an external SPI programmer):

```bash
iceprog design.bin
```

Source: [Fomu Workshop](https://workshop.fomu.im)

## Test Infrastructure Hosts
Welland's Fomu EVT sits on the GPIO header of the RPi 3B+ 00000000cc479fd1 (seen on switch 1 port 17 on 8 Oct
2026). An [OpenVizsla](https://github.com/openvizsla/ov_ftdi) OV3 USB protocol analyser (`1d50:607c`, serial
OV100662) sits inline on the Fomu's USB, to debug the Fomu's USB stack (DFU programming, CDC-ACM serial, custom
USB protocols) without changing the FPGA design or host software. The check names it as a debug tool, not a
board. Its state is in the [current verify results](../verify/current-results.md#current-results).

## LiteX Integration

| Property | Value |
|----------|-------|
| Platform module | `litex_boards.platforms.kosagi_fomu_evt` |
| Target module | `litex_boards.targets.kosagi_fomu` |
| Default clock | `clk48` (48 MHz, pin 44) |
| Programmer | IceStorm (`iceprog`) |
| Toolchain | Yosys + nextpnr-ice40 (open source, IceStorm flow) |

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## References

- LiteX platform file: <https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py>
- Fomu Workshop (getting started guide): <https://workshop.fomu.im>
- Fomu hardware design files: <https://github.com/im-tomu/fomu-hardware>
- Crowd Supply campaign: <https://www.crowdsupply.com/sutajio-kosagi/fomu>
