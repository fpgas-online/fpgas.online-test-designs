\[[top](./README.md)\] \[[spec](./tt-fpga.md)\] \[[pmod standards](./pmod-tt.md)\] \[[pmod hat](./rpi-hat-pmod.md)\]

# TT FPGA Demo Board v3 Pin Mapping

The pin mapping of a Tiny Tapeout FPGA demo board on a Raspberry Pi with a Digilent Pmod HAT is kept in one
place, and this page is not it:

- **The wiring itself**, the cable picture and the pin tables:
  [`docs/wiring/tt-fpga/`](../wiring/tt-fpga/README.md) in this repository, generated from `wiring.toml`.
  A test there fails if the tables and the test code's own numbers ever differ.

| What | Generated page |
| --- | --- |
| Which demo board header goes to which Pmod HAT port, with the picture | [tt-fpga-cables.md](../wiring/tt-fpga/generated/tt-fpga-cables.md) |
| `ui_in` and `uo_out`, wire by wire: iCE40 pin, signal, demo board pin, Pmod HAT pin, Pi GPIO | [tt-fpga-pins-ui-uo.md](../wiring/tt-fpga/generated/tt-fpga-pins-ui-uo.md) |
| `uio`, wire by wire, the GPIOs that two ports share, and the serial port | [tt-fpga-pins-uio-uart.md](../wiring/tt-fpga/generated/tt-fpga-pins-uio-uart.md) |
| The pins that load the FPGA, the seven-segment display, the clock, the reset and the LED | [tt-fpga-pins-other.md](../wiring/tt-fpga/generated/tt-fpga-pins-other.md) |
| Where each of those facts comes from, and what nobody has checked | [tt-fpga-sources.md](../wiring/tt-fpga/generated/tt-fpga-sources.md) |

[![Which Pmod header of the demo board goes to which port of the Pmod HAT](../wiring/tt-fpga/generated/tt-fpga-pmod-cables.png)](../wiring/tt-fpga/generated/tt-fpga-pmod-cables.svg)

What is left on this page is what is not wiring: how the FPGA is loaded, and notes on the serial port and the
loopback test. Which boards exist and where they are is not kept here either: see [tt-fpga.md](tt-fpga.md#deployment).

## Hardware Overview

The TTDBv3 consists of two boards:

- **FPGA Breakout Board**: iCE40UP5K + clock oscillator (no SPI flash)
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

The microcontroller pins the loader drives, and the iCE40's configuration pins:
[tt-fpga-pins-other.md, "Loading the FPGA"](../wiring/tt-fpga/generated/tt-fpga-pins-other.md#loading-the-fpga-its-configuration-pins).

### Programming Flow

1. Show the RP2350 a copy of the bitstream on the Pi (`mpremote mount`, served over the serial link; nothing is
   written to the RP2350's filesystem)
2. Execute MicroPython script via raw REPL:
   - Assert CRESET_B low, then high (reset iCE40 into config mode)
   - Stream bitstream via PIO SPI at 1 MHz
   - Start 50 MHz PWM clock on GPIO16
3. Release all shared GPIOs to high-Z (input mode)

### openFPGALoader Support (work in progress)

Direct programming of the iCE40 via openFPGALoader (bypassing the MicroPython REPL) is being developed. This would allow faster, more reliable programming without needing `mpremote`.

- openFPGALoader fork with TT FPGA support: [mithro/openFPGALoader (tt-fpga-support)](https://github.com/mithro/openFPGALoader/tree/tt-fpga-support)

### RP2350 Considerations

- The boards run TT SDK 3.1.0 (the stock build hangs in `DemoBoard()`); the public site depends on the SDK booting, so do **not** replace `main.py` with a no-op on deployed boards (see [tt-fpga.md](tt-fpga.md#known-workarounds)).
- The `fpgas-tt` daemon owns `/dev/ttboard` (→ `/dev/ttyACM0`) on every deployed host; stop it before using `mpremote` directly.
- If the RP2350 is unresponsive, USB power cycle via `uhubctl` or PoE reset can recover it.
- The stock RP2350 firmware loads `GPIOMapTT04` instead of `GPIOMapTTDBv3`, returning incorrect GPIO numbers. All pin numbers in this document are the correct TTDBv3 values (empirically confirmed), not the firmware-reported values.

## TinyTapeout I/O Signals

The tables of `ui_in`, `uo_out` and `uio` (iCE40 pin, demo board pin, Pmod HAT pin, Pi GPIO, and whether each
wire was measured) are generated: [tt-fpga-pins-ui-uo.md](../wiring/tt-fpga/generated/tt-fpga-pins-ui-uo.md) and
[tt-fpga-pins-uio-uart.md](../wiring/tt-fpga/generated/tt-fpga-pins-uio-uart.md). The second one explains the three Raspberry Pi GPIOs
that Pmod HAT ports JA and JB share, and what that means for a design.

Two things about those shared GPIOs that are about testing, not wiring:

- The pin identification design gives the two FPGA pins on each shared GPIO their turns: `ui_in[1:3]` send their
  pin numbers for 0.4 s while `uio[1:3]` are high impedance, then nobody for 0.1 s, then the reverse; the scan
  listens on each shared GPIO for a whole cycle and expects both numbers
  ([#142](https://github.com/fpgas-online/fpgas.online-test-designs/issues/142)). One thing the test cannot
  tell even then: the JA wire and the JB wire of the same number (2, 3 or 4) swapped with each other. Both end
  on the same Pi pin, where the HAT joins them, so the Pi hears the same two numbers either way; the two
  ribbons swapped as a whole is caught, by their other five wires.
- The SPI kernel modules must be unloaded (`rmmod spidev spi_bcm2835`) before a Pmod test, since they claim
  GPIO7 to GPIO11, which are Pmod HAT JA pins 1 to 4 and JB pins 1 to 4.

Earlier versions of this page had JA and JC the other way round
([issue #58](https://github.com/fpgas-online/fpgas.online-test-designs/issues/58)).

## UART Interface

The TT standard UART uses ui_in[3] (RX) and uo_out[4] (TX), following the [TinyTapeout UART0 convention](pmod-tt.md#uart-via-rp2040rp2350-built-in-usb-bridge-no-pmod-needed).

### Signal Routing

Which pins, headers and GPIOs the two serial signals are on:
[tt-fpga-pins-uio-uart.md, "The serial port (UART)"](../wiring/tt-fpga/generated/tt-fpga-pins-uio-uart.md#the-serial-port-uart).

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
| Requires  | the RP2350's UART1 bridged on GPIO20/37 (`tt_test_wrapper.py`: `UART(1, 115200, tx=Pin(20), rx=Pin(37))`); these two signals are what Tiny Tapeout's convention calls UART0 ([pmod-tt.md](pmod-tt.md#uart-via-rp2040rp2350-built-in-usb-bridge-no-pmod-needed)) |

### Access via RPi GPIO (not currently feasible)

The RPi would have to transmit on GPIO11 and receive on GPIO4. On the BCM2711, UART3 has its TX, not its RX, on GPIO4, and no UART has its TX on GPIO11, so no hardware UART fits. Without hardware UART support, these pins cannot reliably serve as a serial port at 115200 baud.

## PMOD Loopback

The GPIO loopback design computes `uo_out = ~ui_in`: the RPi drives the 8 ui_in pins (HAT JA) and reads the 8
uo_out pins (HAT JC). The mapping is in [tt-fpga-pins-ui-uo.md](../wiring/tt-fpga/generated/tt-fpga-pins-ui-uo.md).

`test_pmod_loopback.py`'s `tt` config follows those tables (a test in `docs/wiring/tt-fpga/` holds it to them): bit i is driven on JA and read on JC. It replaces GPIO lists that predated the measured cabling ([issue #19](https://github.com/fpgas-online/fpgas.online-test-designs/issues/19)). The loopback is not one of the tests `fpgas-verify` runs at boot; it is the `pmod` test of `fpgas-tt-fpga-debug`.

### Pre-test Requirements

- `rmmod spidev spi_bcm2835` — SPI kernel modules claim GPIO7-11 (HAT JA pins 1-4 and JB pin 1, used by ui_in[0:3] and uio[0])
- RP2350 GPIOs must be released to high-Z after FPGA programming (the programming wrapper handles this automatically)
- Driving ui_in[1:3] also drives uio[1:3] (the shared GPIOs, above); the loopback design does not use uio

## Configuration SPI, 7-Segment Display, Other Signals

Generated: [tt-fpga-pins-other.md](../wiring/tt-fpga/generated/tt-fpga-pins-other.md). The breakout has no SPI flash
([tt-fpga.md](tt-fpga.md#programming)).

## References

- The wiring, its generator and its tests: [docs/wiring/tt-fpga/](../wiring/tt-fpga/README.md)
- TT FPGA platform definition: [tt_fpga_platform.py](../../designs/_shared/tt_fpga_platform.py)
- TinyTapeout PCB Specs: [tinytapeout.com/specs/pcb](https://tinytapeout.com/specs/pcb/)
- PMOD Interface Specification: [pmod.md](pmod.md)
- TinyTapeout PMOD Connector Standards: [pmod-tt.md](pmod-tt.md)
- PMOD HAT Adapter (RPi): [rpi-hat-pmod.md](rpi-hat-pmod.md)
