\[[top](./README.md)\] \[[spec](./fomu-evt.md)\]

# Fomu EVT Pin Mapping

Pin mapping for the Kosagi Fomu EVT (iCE40UP5K-SG48) as connected in the fpgas.online test infrastructure: one EVT, on the Raspberry Pi 3B+ 00000000cc479fd1 at Welland.

## FPGA Device

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K-SG48 |
| Package | SG48 (48-pin QFN) |
| Clock | 48 MHz on-board oscillator (pin 44) |
| Block RAM | 30 EBR blocks (15 KB total) |
| SPRAM | 128 KB (4 × 32 KB) |
| Toolchain | icestorm / nextpnr-ice40 (open source) |

Source: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)

## Physical Form Factor

The Fomu EVT connects to its Pi in two ways:
- **GPIO header**: it sits on the Pi's 40-pin header ([the Pi's header](#the-pis-header)): reset, CDONE, the SPI flash and the UART.
- **USB**: its USB plugs into the Pi's USB, through an inline OpenVizsla OV3 analyser on the Welland host.

## The Pi's header

The EVT is the "stretch" Fomu PCB with a Raspberry Pi header (J1, "Raspberry Pi Hat, used for firmware
development"): it plugs onto the Pi's 40-pin header. From its schematic
([tomu-fpga.sch](https://github.com/im-tomu/fomu-hardware/blob/evt/hardware/pcb/tomu-fpga.sch), branch `evt`), which
[fomu-flash](https://github.com/im-tomu/fomu-flash) and the board's
[EVT1a notes](https://github.com/im-tomu/fomu-hardware/blob/evt/hardware/EVT1a.md) agree with:

| Pi pin | BCM | Net | Goes to |
|---|---|---|---|
| 3 | 2 | DBG_1 | iCE40 pin 20 (LiteX `dbg:0`) |
| 5 | 3 | DBG_2 | iCE40 pin 12 (`dbg:1`) |
| 7 | 4 | DBG_3 | iCE40 pin 11 (`dbg:2`) |
| 8 | 14 (TXD) | UART_TX | iCE40 pin 21, the design's serial RX |
| 10 | 15 (RXD) | UART_RX | iCE40 pin 13, the design's serial TX |
| 11 | 17 | CDONE | iCE40 CDONE: high once it has loaded a design |
| 12 | 18 | DBG_4 | iCE40 pin 25 (`dbg:3`) |
| 13 | 27 | CRESET | iCE40 CRESET_B (low: in reset), and the board's reset button |
| 15 | 22 | DBG_5 | iCE40 pin 10 (`dbg:4`) |
| 18 | 24 | SPI_IO2 | flash /WP, iCE40 pin 18 |
| 19 | 10 (MOSI) | SPI_MOSI | flash DI, iCE40 pin 14 (SPI_SO) |
| 21 | 9 (MISO) | SPI_MISO | flash DO, iCE40 pin 17 (SPI_SI) |
| 22 | 25 | SPI_IO3 | flash /HOLD, iCE40 pin 19 |
| 23 | 11 (SCLK) | SPI_CLK | flash CLK, iCE40 pin 15 (SPI_SCK) |
| 24 | 8 (CE0) | SPI_CS | flash /CS, iCE40 pin 16 (SPI_SS) |
| 26 | 7 | DBG_6 | iCE40 pin 9 (`dbg:5`) |

Pins 2 and 4 (5 V) power the board, the grounds are tied, and the 3V3 pins (1, 17) are not connected. The
flash, U4, is a Winbond W25Q128JV-IM (JEDEC ID `ef 70 18`, 16 MiB, a 64-bit unique ID).

The iCE40's configuration port, the flash and the Pi's SPI0 pins are one bus. With CRESET held low the iCE40
releases it, so the Pi can read the flash (the schematic: "To program SPI flash, put FPGA in RESET"). That is
how the check identifies the Fomu ([fpgas-verify: the Fomu](../verify/tests.md#arty-netv2-fomu-and-tt-fpga)):
`fomu_header_id.py` reads the flash's JEDEC ID and unique ID with read commands only, sets every line back to
an input before it lets CRESET go, and the iCE40 then boots from its flash as at power-up. Finding the board
only reads CDONE.


## Programming Interface

The Fomu boots from SPI flash into a DFU bootloader, foboot. A DFU load writes the bitstream into the flash's user image, at offset 0x40000, and starts it ([foboot's README](https://github.com/im-tomu/foboot#loading-and-running-other-bitstreams)). A power cycle starts foboot again; the user image stays in the flash until the next DFU load replaces it.

| Parameter | Value |
|-----------|-------|
| Interface | USB DFU (written to the flash's user image, then started) |
| USB VID:PID | `1209:5bf0` (DFU bootloader) |
| Tool | `openFPGALoader -b fomu <bitstream>` |
| Bitstream type | `.bin` |
| Bootloader | DFU Bootloader v2.0.4 |

### DFU Bootloader Timeout

The DFU bootloader has a ~3 minute timeout. If no DFU activity occurs within this window, the bootloader warm-boots the iCE40 to load the user bitstream from SPI flash. The user bitstream typically has no USB, causing the Fomu to disappear from USB.

**Recovery**: PoE power cycle resets the Fomu, restarting the DFU bootloader. The `verify_hardware.py` script automatically triggers a PoE reset and retries programming when DFU is unavailable.

## USB Interface

| Signal | iCE40 Pin | IO Standard |
|--------|-----------|-------------|
| D+ | 34 | LVCMOS33 |
| D- | 37 | LVCMOS33 |
| Pull-up | 35 | LVCMOS33 |
| Pull-down | 36 | LVCMOS33 |

The USB interface is active only when the DFU bootloader or a USB-enabled bitstream is loaded. Custom test bitstreams (UART echo, GPIO loopback) do not include USB, so the Fomu disappears from USB after programming.

## USB Monitoring

Each Fomu host has an inline USB protocol analyzer between the Fomu and the RPi USB port for capturing and debugging USB traffic.

| Host | Analyser | USB VID:PID |
|------|----------|-------------|
| RPi 3B+ 00000000cc479fd1 (Welland) | OpenVizsla OV3, serial OV100662 | `1d50:607c` |

The check names the analyser as a debug tool (`OpenVizsla OV3 OV100662 on USB (…), a debug tool, not a board`),
never as a board, and never as "no board": the Fomu is found on its header whatever is on its USB. The
Cythion/LUNA analyser (`16d0:05a5`) an older version of this page listed for a second host is
not at the site now.

## UART Interface

The FPGA's serial pins connect to the RPi's GPIO UART via the GPIO header. This is a direct connection — NOT through USB.

| Signal | iCE40 Pin | Direction | IO Standard |
|--------|-----------|-----------|-------------|
| TX (FPGA → RPi) | 13 | Output | LVCMOS33 (PULLUP) |
| RX (RPi → FPGA) | 21 | Input | LVCMOS33 |

| Parameter | Value |
|-----------|-------|
| RPi device | `/dev/serial0` → `/dev/ttyAMA0` |
| Baud rate | 115200 |
| Test args | `--port /dev/serial0 --board fomu --skip-banner` |

On the Pi 3B+, `hciuart` is inactive, so `/dev/ttyAMA0` (PL011) is available on GPIO14/15 for FPGA UART. `serial-getty` must be masked (not just stopped) to prevent it from consuming serial data.

The header joins iCE40 pin 21 (the design's RX) to the Pi's TXD (GPIO14, pin 8) and iCE40 pin 13 (TX) to the Pi's RXD (GPIO15, pin 10): [the Pi's header](#the-pis-header).

### Pre-test Requirements

- `systemctl mask serial-getty@ttyAMA0` — Mask prevents systemd from restarting the serial login console
- `systemctl stop serial-getty@ttyAMA0` — Stop the currently running instance
- `fuser -k /dev/serial0` — Kill any remaining process holding the port
- `chmod 666 /dev/serial0` — Fix permissions after serial-getty releases

## PMOD / GPIO Loopback

The Fomu EVT has two PMOD-style connectors defined in the platform file. The loopback gateware uses `pmoda_n` as input and `pmodb_n` as output.

### pmoda_n (Loopback Input)

| Index | iCE40 Pin |
|-------|-----------|
| 0 | 28 |
| 1 | 27 |
| 2 | 26 |
| 3 | 23 |

### pmodb_n (Loopback Output)

| Index | iCE40 Pin |
|-------|-----------|
| 0 | 48 |
| 1 | 47 |
| 2 | 46 |
| 3 | 45 |

Note: `pmodb_n` shares pins with `touch_pins` (capacitive touch pads on the Fomu).

### Not a loopback on the EVT

An earlier version of this page listed "drive GPIO27, read GPIO9" as a confirmed loopback pair. On the EVT's header that cannot be one:
- GPIO27 is the iCE40's CRESET, a dedicated reset input.
- GPIO9 is the flash's MISO.

No net joins the two ([the Pi's header](#the-pis-header)). The `pmod` and `pin-id` tests assume the PMOD HAT's wiring, which an EVT on the header does not have. On this board the Pi lines an iCE40 design can drive are the six `dbg` pins (GPIO 2, 3, 4, 18, 22, 7), the UART (GPIO 14, 15), and the SPI pins it shares with its flash (GPIO 8-11, 24, 25; only once it has loaded a design, and never while the Pi reads the flash with the iCE40 held in reset). The follow-up is in
[#202](https://github.com/fpgas-online/fpgas.online-test-designs/issues/202).

## SPI Flash

Dedicated iCE40 SPI pins for persistent bitstream storage.

| Signal | iCE40 Pin | IO Standard |
|--------|-----------|-------------|
| CS_N | 16 | LVCMOS33 |
| CLK | 15 | LVCMOS33 |
| MOSI (DQ0) | 14 | LVCMOS33 |
| MISO (DQ1) | 17 | LVCMOS33 |
| WP (DQ2) | 18 | LVCMOS33 |
| HOLD (DQ3) | 19 | LVCMOS33 |

Quad SPI supported via `spiflash4x` resource.

## I2C

| Signal | iCE40 Pin | IO Standard |
|--------|-----------|-------------|
| SCL | 12 | LVCMOS18 |
| SDA | 20 | LVCMOS18 |

Note: I2C uses 1.8V IO standard, unlike all other pins (3.3V LVCMOS33).

## Other Signals

| Signal | iCE40 Pin | IO Standard | Function |
|--------|-----------|-------------|----------|
| clk48 | 44 | LVCMOS33 | 48 MHz oscillator input |
| user_led_n | 41 | LVCMOS33 | User LED (active low) |
| RGB LED R | 40 | LVCMOS33 | RGB LED red |
| RGB LED G | 39 | LVCMOS33 | RGB LED green |
| RGB LED B | 41 | LVCMOS33 | RGB LED blue |
| user_btn_n[0] | 42 | LVCMOS33 | Capacitive touch button |
| user_btn_n[1] | 38 | LVCMOS33 | Capacitive touch button |

## Debug Header

The Fomu EVT has a debug connector with 6 pins:

| Index | iCE40 Pin |
|-------|-----------|
| dbg:0 | 20 |
| dbg:1 | 12 |
| dbg:2 | 11 |
| dbg:3 | 25 |
| dbg:4 | 10 |
| dbg:5 | 9 |

## References

- LiteX platform file: [kosagi_fomu_evt.py](https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/kosagi_fomu_evt.py)
- Fomu EVT design files: [github.com/im-tomu/fomu-hardware](https://github.com/im-tomu/fomu-hardware/tree/evt/hardware/pcb)
- Crowd Supply campaign: [crowdsupply.com/sutajio-kosagi/fomu](https://www.crowdsupply.com/sutajio-kosagi/fomu)
- PMOD HAT Documentation: [rpi-hat-pmod.md](rpi-hat-pmod.md)
