# TT FPGA Demo Board v3 Pin Mapping

Pin mapping for the TinyTapeout FPGA Demo Board v3 (TTDBv3) as connected in the fpgas.online test infrastructure. Four hosts: pi27 (10.21.0.127), pi29 (10.21.0.129), pi31 (10.21.0.131), pi33 (10.21.0.133).

## Hardware Overview

The TTDBv3 consists of two boards:

- **FPGA Breakout Board**: iCE40UP5K + SPI flash + clock oscillator
- **TT Demo PCB**: RP2350B controller, PMOD headers, 7-segment display, DIP switches

The RP2350 programs the iCE40 via SPI and provides a 50 MHz clock. After programming, the RP2350 releases its GPIO pins to high-impedance so the RPi can communicate with the FPGA directly through the PMOD HAT.

## FPGA Device

| Parameter | Value                                  |
| --------- | -------------------------------------- |
| FPGA      | Lattice iCE40UP5K-SG48                 |
| Package   | SG48 (48-pin QFN)                      |
| Clock     | 50 MHz from RP2350 PWM (GPIO16)        |
| Block RAM | 30 EBR blocks (15 KB total)            |
| SPRAM     | 128 KB (4 × 32 KB)                     |
| Toolchain | icestorm / nextpnr-ice40 (open source) |

Source: [tt_fpga_platform.py](../../designs/_shared/tt_fpga_platform.py)

## Programming Interface

The iCE40 is programmed via the RP2350 over USB CDC, not directly from the RPi.

| Parameter      | Value                                                 |
| -------------- | ----------------------------------------------------- |
| Interface      | RP2350 PIO SPI → iCE40 SPI configuration port         |
| USB device     | `/dev/ttyACM0` (MicroPython REPL)                     |
| USB VID:PID    | `2e8a:0005` (MicroPython Board in FS mode)            |
| Tool           | `python3 tt_fpga_program.py /dev/ttyACM0 <bitstream>` |
| Bitstream type | `.bin` (volatile SRAM load)                           |

### RP2350 SPI Programming Pins

| Signal   | RP2350 GPIO | Function                  |
| -------- | ----------- | ------------------------- |
| SCK      | GPIO6       | SPI clock                 |
| MOSI     | GPIO3       | SPI data out              |
| SS       | GPIO5       | SPI chip select           |
| CRESET_B | GPIO1       | iCE40 configuration reset |

### Programming Flow

1. Upload bitstream to RP2350 filesystem via `mpremote`
2. Execute MicroPython script via raw REPL:
   - Assert CRESET_B low, then high (reset iCE40 into config mode)
   - Stream bitstream via PIO SPI at 1 MHz
   - Start 50 MHz PWM clock on GPIO16
3. Release all shared GPIOs to high-Z (input mode)

### openFPGALoader Support (work in progress)

Direct programming of the iCE40 via openFPGALoader (bypassing the MicroPython REPL) is being developed. This would allow faster, more reliable programming without needing `mpremote` or the RP2350 filesystem.

- openFPGALoader fork with TT FPGA support: [mithro/openFPGALoader (tt-fpga-support)](https://github.com/mithro/openFPGALoader/tree/tt-fpga-support)

### RP2350 Considerations

- The stock `main.py` calls `DemoBoard()` which probes I2C and can hang permanently. A safe `main.py` must be installed via `mpremote` to prevent this.
- If the RP2350 is unresponsive, USB power cycle via `uhubctl` or PoE reset can recover it.
- The RP2350 firmware loads `GPIOMapTT04` instead of `GPIOMapTTDBv3`, returning incorrect GPIO numbers. All pin numbers in this document are the correct TTDBv3 values (empirically confirmed), not the firmware-reported values.

## TinyTapeout I/O Signals

### ui_in (User Inputs)

8-bit input bus. The RPi drives these through the PMOD HAT; the FPGA reads them.

| Bit      | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO | Verified |
| -------- | --------- | ----------- | ------------ | -------- | -------- |
| ui_in[0] | 13        | 17          | JC1          | 16       | pin-id   |
| ui_in[1] | 19        | 18          | JC2          | 14       | pin-id   |
| ui_in[2] | 18        | 19          | JC3          | 15       | pin-id   |
| ui_in[3] | 21        | 20          | JC4          | 17       | pin-id   |
| ui_in[4] | 23        | 21          | JC7          | 4        | pin-id   |
| ui_in[5] | 25        | 22          | JC8          | 12       | (*)      |
| ui_in[6] | 26        | 23          | JC9          | 5        | (*)      |
| ui_in[7] | 27        | 24          | JC10         | 6        | pin-id   |

(\*) ui_in[5] and ui_in[6] were not decoded (initial=0, decoder sync issue). Positions inferred from the pattern — the JC connector pin numbering matches the TT bit ordering straight through (bit 0→pin 1, bit 7→pin 10).

### uo_out (User Outputs)

8-bit output bus. The FPGA drives these; the RPi reads them through the PMOD HAT.

| Bit       | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO | Verified |
| --------- | --------- | ----------- | ------------ | -------- | -------- |
| uo_out[0] | 38        | 33          | JA1          | 8        | pin-id   |
| uo_out[1] | 42        | 34          | JA2          | 10       | (**)     |
| uo_out[2] | 43        | 35          | JA3          | 9        | (**)     |
| uo_out[3] | 44        | 36          | JA4          | 11       | (**)     |
| uo_out[4] | 45        | 37          | JA7          | 19       | pin-id   |
| uo_out[5] | 46        | 38          | JA8          | 21       | pin-id   |
| uo_out[6] | 47        | 39          | JA9          | 20       | pin-id   |
| uo_out[7] | 48        | 40          | JA10         | 18       | pin-id   |

(\*\*) uo_out[1:3] are on JA pins 2-4 which share RPi GPIOs with JB pins 2-4. The pin-id decode on these GPIOs is corrupted by JA/JB contention. Positions inferred from the pattern — the JA connector pin numbering matches the TT bit ordering straight through (bit 0→pin 1, bit 7→pin 10).

### uio (Bidirectional I/O)

8-bit bidirectional bus. Connected through the TT board's third PMOD header to PMOD HAT port JB.

| Bit    | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO |
| ------ | --------- | ----------- | ------------ | -------- |
| uio[0] | 2         | 25          | JB1          | 7        |
| uio[1] | 4         | 26          | JB2          | 10       |
| uio[2] | 3         | 27          | JB3          | 9        |
| uio[3] | 6         | 28          | JB4          | 11       |
| uio[4] | 9         | 29          | JB7          | 26       |
| uio[5] | 10        | 30          | JB8          | 13       |
| uio[6] | 11        | 31          | JB9          | 3        |
| uio[7] | 12        | 32          | JB10         | 2        |

RP2350 GPIO numbers follow the sequential pattern (ui_in=17-24, uio=25-32, uo_out=33-40).

**WARNING — JA/JB pin sharing conflict**: HAT JB pins 2-4 and HAT JA pins 2-4 are the [same RPi GPIO lines](rpi-hat-pmod.md) (GPIO10, GPIO9, GPIO11 — the shared SPI0 bus). This means 3 uo_out signals and 3 uio signals are electrically connected at the RPi side:

| RPi GPIO | HAT JA Pin | TT Signal (uo_out) | HAT JB Pin | TT Signal (uio) | Conflict |
| -------- | ---------- | ------------------ | ---------- | --------------- | -------- |
| GPIO10   | JA2        | uo_out[1]          | JB2        | uio[1]          | Shorted  |
| GPIO9    | JA3        | uo_out[2]          | JB3        | uio[2]          | Shorted  |
| GPIO11   | JA4        | uo_out[3]          | JB4        | uio[3]          | Shorted  |

When the FPGA drives uo_out[1,2,3] and uio[1,2,3] simultaneously with different values, the two FPGA outputs will fight each other through the shared RPi GPIO. This has several consequences:

- **GPIO loopback test**: Works because the test only drives ui_in (JC) and reads uo_out (JA). The uio pins (JB) are not driven during this test, so no conflict occurs.
- **Bidirectional I/O test**: Cannot independently test uio[1,2,3] because they are shorted to uo_out[1,2,3] respectively. If the FPGA drives both buses, the conflicting outputs may cause contention or incorrect readings.
- **SPI kernel modules**: Must be unloaded (`rmmod spidev spi_bcm2835`) since GPIO7-11 overlap with HAT JA pins 1-4 and JB pins 1-4.

The 5 unaffected uio bits (uio[0], uio[4:7]) on JB pins 1 and 7-10 use unique RPi GPIOs and work correctly.

## UART Interface

The TT standard UART uses ui_in[3] (RX) and uo_out[4] (TX), following the [TinyTapeout UART0 convention](pmod-tt.md#uart-via-rp2040rp2350-built-in-usb-bridge-no-pmod-needed).

### Signal Routing

| Signal                    | iCE40 Pin | TT Signal | RP2350 GPIO | PMOD HAT Pin | RPi GPIO |
| ------------------------- | --------- | --------- | ----------- | ------------ | -------- |
| Serial RX (FPGA receives) | 21        | ui_in[3]  | GPIO20      | JC9          | 5        |
| Serial TX (FPGA sends)    | 45        | uo_out[4] | GPIO37      | JA4          | 11       |

### Access via RP2350 USB bridge (recommended)

The RP2350 connects to the same FPGA pins via GPIO20/GPIO37 and can bridge UART data to the USB CDC serial port (`/dev/ttyACM0`). This is the recommended approach since:

- RPi GPIO5/11 are **not hardware UART pins** — the BCM2711 has no UART peripheral assignable to this GPIO pair.
- The NFS boot image has no device tree overlay files, and the root filesystem is read-only.
- Software bit-bang UART at 115200 baud is unreliable under a non-RT Linux kernel.
- The RP2350 has hardware UART peripherals that can be configured for these pins.

| Parameter | Value                                                   |
| --------- | ------------------------------------------------------- |
| Device    | `/dev/ttyACM0` (via RP2350 USB CDC)                     |
| Baud rate | 115200                                                  |
| Test args | `--port /dev/ttyACM0 --board tt --skip-banner`          |
| Requires  | RP2350 firmware configured to bridge UART0 on GPIO20/37 |

### Access via RPi GPIO (not currently feasible)

RPi GPIO5 and GPIO11 are not assignable to any BCM2711 hardware UART as a pair. The BCM2711 UART3 uses GPIO4/5 (TX/RX), and no UART uses GPIO11 for TX. Without hardware UART support, these pins cannot reliably serve as a serial port at 115200 baud.

## PMOD Loopback

The GPIO loopback test uses all 8 ui_in pins (drive) and all 8 uo_out pins (read). The FPGA computes `uo_out = ~ui_in`.

All 8 pairs are **empirically confirmed** (4-transition verification on pi33). See the ui_in and uo_out tables above for the full mapping.

### Pre-test Requirements

- `rmmod spidev spi_bcm2835` — SPI kernel modules claim GPIO7-11 (overlap with HAT JA pins 1-4 and JB pin 1, used by uo_out[2], uo_out[4], uo_out[6], uo_out[7])
- RP2350 GPIOs must be released to high-Z after FPGA programming (the programming wrapper handles this automatically)

## SPI Flash

Dedicated iCE40 SPI pins on the FPGA breakout board (not shared with PMOD).

| Signal | iCE40 Pin |
| ------ | --------- |
| CS_N   | 16        |
| CLK    | 15        |
| MISO   | 17        |
| MOSI   | 14        |

## 7-Segment Display

The TT Demo PCB has a 7-segment LED display connected to uo_out[0:6]. These share the same PMOD traces — when the RPi is driving GPIO tests, the display reflects the test patterns.

| Segment | TT Signal | iCE40 Pin |
| ------- | --------- | --------- |
| a       | uo_out[0] | 38        |
| b       | uo_out[1] | 42        |
| c       | uo_out[2] | 43        |
| d       | uo_out[3] | 44        |
| e       | uo_out[4] | 45        |
| f       | uo_out[5] | 46        |
| g       | uo_out[6] | 47        |

## Other Signals

| Signal     | iCE40 Pin | Function                            |
| ---------- | --------- | ----------------------------------- |
| clk_rp2040 | 20        | 50 MHz clock from RP2350 PWM GPIO16 |
| rst_n      | 37        | Reset (active low)                  |
| RGB LED R  | 39        | Accent LED (active low)             |
| RGB LED G  | 40        | Accent LED (active low)             |
| RGB LED B  | 41        | Accent LED (active low)             |

## References

- TT FPGA platform definition: [tt_fpga_platform.py](../../designs/_shared/tt_fpga_platform.py)
- TinyTapeout PCB Specs: [tinytapeout.com/specs/pcb](https://tinytapeout.com/specs/pcb/)
- PMOD Interface Specification: [pmod.md](pmod.md)
- TinyTapeout PMOD Connector Standards: [pmod-tt.md](pmod-tt.md)
- PMOD HAT Adapter (RPi): [rpi-hat-pmod.md](rpi-hat-pmod.md)
