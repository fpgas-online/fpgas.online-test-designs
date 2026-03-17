# TT FPGA Demo Board v3 Pin Mapping

Pin mapping for the TinyTapeout FPGA Demo Board v3 (TTDBv3) as connected in the fpgas.online test infrastructure. Four hosts: pi27 (10.21.0.127), pi29 (10.21.0.129), pi31 (10.21.0.131), pi33 (10.21.0.133).

## Hardware Overview

The TTDBv3 consists of two boards:

- **FPGA Breakout Board**: iCE40UP5K + SPI flash + clock oscillator
- **TT Demo PCB**: RP2350B controller, PMOD headers, 7-segment display, DIP switches

The RP2350 programs the iCE40 via SPI and provides a 50 MHz clock. After programming, the RP2350 releases its GPIO pins to high-impedance so the RPi can communicate with the FPGA directly through the PMOD HAT.

## FPGA Device

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K-SG48 |
| Package | SG48 (48-pin QFN) |
| Clock | 50 MHz from RP2350 PWM (GPIO16) |
| Block RAM | 30 EBR blocks (15 KB total) |
| SPRAM | 128 KB (4 × 32 KB) |
| Toolchain | icestorm / nextpnr-ice40 (open source) |

Source: [tt_fpga_platform.py](../../designs/_shared/tt_fpga_platform.py)

## Programming Interface

The iCE40 is programmed via the RP2350 over USB CDC, not directly from the RPi.

| Parameter | Value |
|-----------|-------|
| Interface | RP2350 PIO SPI → iCE40 SPI configuration port |
| USB device | `/dev/ttyACM0` (MicroPython REPL) |
| USB VID:PID | `2e8a:0005` (MicroPython Board in FS mode) |
| Tool | `python3 tt_fpga_program.py /dev/ttyACM0 <bitstream>` |
| Bitstream type | `.bin` (volatile SRAM load) |

### RP2350 SPI Programming Pins

| Signal | RP2350 GPIO | Function |
|--------|------------|----------|
| SCK | GPIO6 | SPI clock |
| MOSI | GPIO3 | SPI data out |
| SS | GPIO5 | SPI chip select |
| CRESET_B | GPIO1 | iCE40 configuration reset |

### Programming Flow

1. Upload bitstream to RP2350 filesystem via `mpremote`
2. Execute MicroPython script via raw REPL:
   - Assert CRESET_B low, then high (reset iCE40 into config mode)
   - Stream bitstream via PIO SPI at 1 MHz
   - Start 50 MHz PWM clock on GPIO16
3. Release all shared GPIOs to high-Z (input mode)

### RP2350 Considerations

- The stock `main.py` calls `DemoBoard()` which probes I2C and can hang permanently. A safe `main.py` must be installed via `mpremote` to prevent this.
- If the RP2350 is unresponsive, USB power cycle via `uhubctl` or PoE reset can recover it.
- The RP2350 firmware loads `GPIOMapTT04` instead of `GPIOMapTTDBv3`, returning incorrect GPIO numbers. All pin numbers in this document are the correct TTDBv3 values (empirically confirmed), not the firmware-reported values.

## TinyTapeout I/O Signals

### ui_in (User Inputs)

8-bit input bus. The RPi drives these through the PMOD HAT; the FPGA reads them.

| Bit | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO |
|-----|-----------|-------------|--------------|----------|
| ui_in[0] | 13 | 17 | JC10 | 6 |
| ui_in[1] | 19 | 18 | JC8  | 12 |
| ui_in[2] | 18 | 19 | JC1  | 16 |
| ui_in[3] | 21 | 20 | JC9  | 5 |
| ui_in[4] | 23 | 21 | JC4  | 17 |
| ui_in[5] | 25 | 22 | JC7  | 4 |
| ui_in[6] | 26 | 23 | JC2  | 14 |
| ui_in[7] | 27 | 24 | JC3  | 15 |

### uo_out (User Outputs)

8-bit output bus. The FPGA drives these; the RPi reads them through the PMOD HAT.

| Bit | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO |
|-----|-----------|-------------|--------------|----------|
| uo_out[0] | 38 | 33 | JA10 | 18 |
| uo_out[1] | 42 | 34 | JA8  | 21 |
| uo_out[2] | 43 | 35 | JA1  | 8 |
| uo_out[3] | 44 | 36 | JA9  | 20 |
| uo_out[4] | 45 | 37 | JA4  | 11 |
| uo_out[5] | 46 | 38 | JA7  | 19 |
| uo_out[6] | 47 | 39 | JA2  | 10 |
| uo_out[7] | 48 | 40 | JA3  | 9 |

### uio (Bidirectional I/O)

8-bit bidirectional bus.

| Bit | iCE40 Pin |
|-----|-----------|
| uio[0] | 2 |
| uio[1] | 4 |
| uio[2] | 3 |
| uio[3] | 6 |
| uio[4] | 9 |
| uio[5] | 10 |
| uio[6] | 11 |
| uio[7] | 12 |

**TODO**: Determine PMOD HAT mapping for uio pins (not yet probed).

## UART Interface

The FPGA's UART pins are routed through the PMOD HAT to RPi GPIOs. This is a direct connection — NOT through the RP2350.

| Signal | iCE40 Pin | TT Signal | PMOD HAT Pin | RPi GPIO |
|--------|-----------|-----------|--------------|----------|
| Serial RX (FPGA receives) | 21 | ui_in[3] | JC9 | 5 |
| Serial TX (FPGA sends) | 45 | uo_out[4] | JA4 | 11 |

| Parameter | Value |
|-----------|-------|
| Baud rate | 115200 |
| Test args | `--port <TBD> --board tt --skip-banner` |

**TODO**: RPi GPIO5 and GPIO11 are not standard hardware UART pins. A device tree overlay or alternative UART peripheral is needed to use these as a serial port. See task #10.

## PMOD Loopback

The GPIO loopback test uses all 8 ui_in pins (drive) and all 8 uo_out pins (read). The FPGA computes `uo_out = ~ui_in`.

All 8 pairs are **empirically confirmed** (4-transition verification on pi33). See the ui_in and uo_out tables above for the full mapping.

### Pre-test Requirements

- `rmmod spidev spi_bcm2835` — SPI kernel modules claim GPIO7-11 (overlap with HAT JA pins 1-4 and JB pin 1, used by uo_out[2], uo_out[4], uo_out[6], uo_out[7])
- RP2350 GPIOs must be released to high-Z after FPGA programming (the programming wrapper handles this automatically)

## SPI Flash

Dedicated iCE40 SPI pins on the FPGA breakout board (not shared with PMOD).

| Signal | iCE40 Pin |
|--------|-----------|
| CS_N | 16 |
| CLK | 15 |
| MISO | 17 |
| MOSI | 14 |

## 7-Segment Display

The TT Demo PCB has a 7-segment LED display connected to uo_out[0:6]. These share the same PMOD traces — when the RPi is driving GPIO tests, the display reflects the test patterns.

| Segment | TT Signal | iCE40 Pin |
|---------|-----------|-----------|
| a | uo_out[0] | 38 |
| b | uo_out[1] | 42 |
| c | uo_out[2] | 43 |
| d | uo_out[3] | 44 |
| e | uo_out[4] | 45 |
| f | uo_out[5] | 46 |
| g | uo_out[6] | 47 |

## Other Signals

| Signal | iCE40 Pin | Function |
|--------|-----------|----------|
| clk_rp2040 | 20 | 50 MHz clock from RP2350 PWM GPIO16 |
| rst_n | 37 | Reset (active low) |
| RGB LED R | 39 | Accent LED (active low) |
| RGB LED G | 40 | Accent LED (active low) |
| RGB LED B | 41 | Accent LED (active low) |

## References

- TT FPGA platform definition: [tt_fpga_platform.py](../../designs/_shared/tt_fpga_platform.py)
- TinyTapeout PCB Specs: [tinytapeout.com/specs/pcb](https://tinytapeout.com/specs/pcb/)
- PMOD HAT Documentation: [pmod-hat.md](pmod-hat.md)
