\[[top](./README.md)\] \[[spec](./fomu-evt.md)\]

# Fomu EVT Pin Mapping

Pin mapping for the Kosagi Fomu EVT (iCE40UP5K-SG48) as connected in the fpgas.online test infrastructure. Two hosts: pi17 (10.21.0.117), pi21 (10.21.0.121).

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

The Fomu EVT is a tiny PCB that fits inside a USB-A connector. On pi17/pi21, the Fomu connects to the RPi in two ways:
- **GPIO header**: The Fomu sits directly on the RPi GPIO header as a standard HAT, connecting UART and GPIO signals.
- **USB**: The Fomu's USB-A connector plugs into the RPi's USB port (through the inline USB analyzer — OpenVizsla on pi17, Cythion/LUNA on pi21).

## Programming Interface

The Fomu boots from SPI flash into a DFU bootloader. Programming loads a new bitstream into volatile SRAM via USB DFU.

| Parameter | Value |
|-----------|-------|
| Interface | USB DFU (iCE40 SRAM load) |
| USB VID:PID | `1209:5bf0` (DFU bootloader) |
| Tool | `openFPGALoader -b fomu <bitstream>` |
| Bitstream type | `.bin` (volatile SRAM load) |
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

| Host | Analyzer       | USB VID:PID |
|------|----------------|-------------|
| pi17 | OpenVizsla     | `1d50:607c` |
| pi21 | Cythion/LUNA   | `16d0:05a5` |

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

On pi17/pi21 (RPi 3), `hciuart` is inactive, so `/dev/ttyAMA0` (PL011) is available on GPIO14/15 for FPGA UART. `serial-getty` must be masked (not just stopped) to prevent it from consuming serial data.

**TODO**: Document the exact Fomu-to-RPi GPIO header pin mapping from iCE40 pins 13, 21 to RPi GPIO14, GPIO15.

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

### Confirmed Loopback Pair

Only 1 of the 4 loopback pairs connects to RPi GPIO through the GPIO header:

| Drive RPi GPIO | Read RPi GPIO | Status |
|---------------|--------------|--------|
| GPIO27 | GPIO9 | Confirmed |

**TODO**: Determine which iCE40 pins GPIO27 and GPIO9 map to through the GPIO header. The Fomu-to-RPi header pin mapping needs physical inspection.

### Pre-test Requirements

- `rmmod spidev spi_bcm2835` — GPIO9 is SPI0_MISO; the kernel driver must be unloaded
- The Fomu GPIO output has slow propagation (~5ms settle time). The test uses a poll-until-stable loop.

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
