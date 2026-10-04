\[[top](./README.md)\] \[[spec](./tt-fpga.md)\] \[[pmod standards](./pmod-tt.md)\] \[[pmod hat](./rpi-hat-pmod.md)\]

# TT FPGA Demo Board v3 Pin Mapping

Pin mapping for the TinyTapeout FPGA Demo Board v3 (TTDBv3) as connected in the fpgas.online test infrastructure. Four hosts on the Welland S3300 (switch 2): pi-sw2-p33 (10.21.2.33, `fpga-1`), pi-sw2-p34 (10.21.2.34, `fpga-2`), pi-sw2-p35 (10.21.2.35, `fpga-3`), pi-sw2-p36 (10.21.2.36, `fpga-4`). See [tt-fpga.md](tt-fpga.md#deployment) for MACs, RP2350 serials and the serial-port ownership rule.

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

- The boards run TT SDK 3.1.0 (the stock build hangs in `DemoBoard()`); the public site depends on the SDK booting, so do **not** replace `main.py` with a no-op on deployed boards (see [tt-fpga.md](tt-fpga.md#known-workarounds)).
- The `fpgas-tt` daemon owns `/dev/ttboard` (→ `/dev/ttyACM0`) on every deployed host; stop it before using `mpremote` directly.
- If the RP2350 is unresponsive, USB power cycle via `uhubctl` or PoE reset can recover it.
- The stock RP2350 firmware loads `GPIOMapTT04` instead of `GPIOMapTTDBv3`, returning incorrect GPIO numbers. All pin numbers in this document are the correct TTDBv3 values (empirically confirmed), not the firmware-reported values.

## TinyTapeout I/O Signals

### ui_in (User Inputs)

8-bit input bus. The RPi drives these through the PMOD HAT; the FPGA reads them. Cabled to PMOD HAT port JA.

| Bit      | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO | Verified |
| -------- | --------- | ----------- | ------------ | -------- | -------- |
| ui_in[0] | 13        | 17          | JA1          | 8        | pin-id   |
| ui_in[1] | 19        | 18          | JA2          | 10       | (*)      |
| ui_in[2] | 18        | 19          | JA3          | 9        | (*)      |
| ui_in[3] | 21        | 20          | JA4          | 11       | (*)      |
| ui_in[4] | 23        | 21          | JA7          | 19       | pin-id   |
| ui_in[5] | 25        | 22          | JA8          | 21       | pin-id   |
| ui_in[6] | 26        | 23          | JA9          | 20       | pin-id   |
| ui_in[7] | 27        | 24          | JA10         | 18       | pin-id   |

(\*) ui_in[1:3] are on JA pins 2-4, which share RPi GPIOs with JB pins 2-4. The pin-id decode on these GPIOs is corrupted because ui_in and uio both drive them. Positions inferred from the pattern: the JA connector pin numbering matches the TT bit ordering straight through (bit 0→pin 1, bit 7→pin 10).

### uo_out (User Outputs)

8-bit output bus. The FPGA drives these; the RPi reads them through the PMOD HAT. Cabled to PMOD HAT port JC.

| Bit       | iCE40 Pin | RP2350 GPIO | PMOD HAT Pin | RPi GPIO | Verified |
| --------- | --------- | ----------- | ------------ | -------- | -------- |
| uo_out[0] | 38        | 33          | JC1          | 16       | pin-id   |
| uo_out[1] | 42        | 34          | JC2          | 14       | pin-id   |
| uo_out[2] | 43        | 35          | JC3          | 15       | pin-id   |
| uo_out[3] | 44        | 36          | JC4          | 17       | pin-id   |
| uo_out[4] | 45        | 37          | JC7          | 4        | pin-id   |
| uo_out[5] | 46        | 38          | JC8          | 12       | pin-id   |
| uo_out[6] | 47        | 39          | JC9          | 5        | pin-id   |
| uo_out[7] | 48        | 40          | JC10         | 6        | pin-id   |

Measured with the pin-id design on pi-sw2-p33, p35 and p36 on 2026-09-29 and again by `fpgas-verify` on 2026-10-04: every Welland host is cabled ui_in → JA, uio → JB, uo_out → JC. Earlier versions of this page had JA and JC the other way round ([issue #58](https://github.com/fpgas-online/fpgas.online-test-designs/issues/58)).

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

**WARNING — JA/JB pin sharing conflict**: HAT JB pins 2-4 and HAT JA pins 2-4 are the [same RPi GPIO lines](rpi-hat-pmod.md) (GPIO10, GPIO9, GPIO11 — the shared SPI0 bus). This means 3 ui_in signals and 3 uio signals are electrically connected at the RPi side:

| RPi GPIO | HAT JA Pin | TT Signal (ui_in) | HAT JB Pin | TT Signal (uio) | Conflict |
| -------- | ---------- | ----------------- | ---------- | --------------- | -------- |
| GPIO10   | JA2        | ui_in[1]          | JB2        | uio[1]          | Shorted  |
| GPIO9    | JA3        | ui_in[2]          | JB3        | uio[2]          | Shorted  |
| GPIO11   | JA4        | ui_in[3]          | JB4        | uio[3]          | Shorted  |

ui_in is an input to the design, so the short does not make two FPGA outputs fight. It does mean:

- **A design that drives uio[1,2,3]** also drives ui_in[1,2,3], and the RPi must leave GPIO10/9/11 as inputs or it fights the FPGA.
- **The RPi driving ui_in[1,2,3]** also drives uio[1,2,3], so those uio bits must be inputs in the design.
- **Bidirectional I/O test**: cannot test uio[1,2,3] independently of ui_in[1,2,3].
- **SPI kernel modules**: Must be unloaded (`rmmod spidev spi_bcm2835`) since GPIO7-11 overlap with HAT JA pins 1-4 and JB pins 1-4.

The 5 unaffected uio bits (uio[0], uio[4:7]) on JB pins 1 and 7-10 use unique RPi GPIOs and work correctly.

## UART Interface

The TT standard UART uses ui_in[3] (RX) and uo_out[4] (TX), following the [TinyTapeout UART0 convention](pmod-tt.md#uart-via-rp2040rp2350-built-in-usb-bridge-no-pmod-needed).

### Signal Routing

| Signal                    | iCE40 Pin | TT Signal | RP2350 GPIO | PMOD HAT Pin | RPi GPIO |
| ------------------------- | --------- | --------- | ----------- | ------------ | -------- |
| Serial RX (FPGA receives) | 21        | ui_in[3]  | GPIO20      | JA4          | 11       |
| Serial TX (FPGA sends)    | 45        | uo_out[4] | GPIO37      | JC7          | 4        |

### Access via RP2350 USB bridge (recommended)

The RP2350 connects to the same FPGA pins via GPIO20/GPIO37 and can bridge UART data to the USB CDC serial port (`/dev/ttyACM0`). This is the recommended approach since:

- RPi GPIO11 (to the FPGA's RX) and GPIO4 (from the FPGA's TX) are **not a hardware UART pair** — the BCM2711 has no UART peripheral assignable to them in these directions.
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

The RPi would have to transmit on GPIO11 and receive on GPIO4. On the BCM2711, GPIO4's UART function is UART3 TX (the wrong direction) and GPIO11's is UART4 RTS, so no hardware UART fits. Without hardware UART support, these pins cannot reliably serve as a serial port at 115200 baud.

## PMOD Loopback

The GPIO loopback design computes `uo_out = ~ui_in`: the RPi drives the 8 ui_in pins (HAT JA) and reads the 8 uo_out pins (HAT JC). See the ui_in and uo_out tables above for the mapping.

The GPIO lists in `test_pmod_loopback.py`'s `tt` config predate the measured cabling and have not been re-run against it ([issue #19](https://github.com/fpgas-online/fpgas.online-test-designs/issues/19)). The loopback is not one of the tests `fpgas-verify` runs at boot.

### Pre-test Requirements

- `rmmod spidev spi_bcm2835` — SPI kernel modules claim GPIO7-11 (HAT JA pins 1-4 and JB pin 1, used by ui_in[0:3] and uio[0])
- RP2350 GPIOs must be released to high-Z after FPGA programming (the programming wrapper handles this automatically)
- Driving ui_in[1:3] also drives uio[1:3] (see the warning above); the loopback design does not use uio

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
