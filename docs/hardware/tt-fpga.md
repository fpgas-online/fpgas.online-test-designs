\[[top](./README.md)\] \[[pinmap](./tt-fpga-pin-mapping.md)\] \[[pmod standards](./pmod-tt.md)\] \[[info](https://tinytapeout.com/guides/fpga-breakout/)\] \[[platform](../../designs/_shared/tt_fpga_platform.py)\]

# TinyTapeout FPGA Demo Board

The TinyTapeout (TT) FPGA Demo Board is a development platform that combines an FPGA breakout board (Lattice iCE40UP5K) with the TinyTapeout demo PCB (RP2040-based). It allows testing TinyTapeout designs on real FPGA hardware before silicon fabrication.

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K (on FPGA breakout board) |
| Logic cells | 5,280 LUT4s |
| SPRAM | 128 KB (4 x 32 KB blocks) |
| DPRAM (EBR) | 120 Kbit (15 x 8 Kbit blocks) |
| Controller | RP2040 (dual-core Arm Cortex-M0+, on demo PCB) |
| USB | USB-C (via RP2040) |
| Display | 7-segment LED display |
| DIP switches | Configuration switches |
| PMOD headers | 2x standard PMOD (following Digilent spec) |
| Max clock | ~66 MHz |
| I/O voltage | 3.3V |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/), [TinyTapeout FPGA Breakout Guide](https://tinytapeout.com/guides/fpga-breakout/)

## Architecture

The TT FPGA Demo Board consists of two PCBs:

1. **TinyTapeout Demo PCB** (bottom): Contains the RP2040 microcontroller, USB-C connector, 7-segment display, DIP switches, and PMOD headers. This PCB is designed to interface with TinyTapeout ASICs but also accepts the FPGA breakout board.

2. **FPGA Breakout Board** (top): Contains the iCE40UP5K FPGA and SPI flash. It plugs into the demo PCB's chip socket, presenting the same interface as a TinyTapeout ASIC.

```
┌──────────────────────────────┐
│    FPGA Breakout Board       │
│    (iCE40UP5K + SPI Flash)   │
│                              │
│    ┌────────────────────┐    │
│    │  Pin headers down  │    │
│    └────────────────────┘    │
└──────────────┬───────────────┘
               │ (plugs into)
┌──────────────┴───────────────┐
│    TinyTapeout Demo PCB      │
│                              │
│  [USB-C] [RP2040] [7-seg]   │
│  [DIP SW] [PMOD A] [PMOD B] │
└──────────────────────────────┘
```

## TinyTapeout I/O Interface

The FPGA implements a TinyTapeout-compatible interface with the following signals:

| Signal Group | Width | Direction | Description |
|-------------|-------|-----------|-------------|
| `ui_in[7:0]` | 8 bits | Input | User inputs (directly from DIP switches or RP2040) |
| `uo_out[7:0]` | 8 bits | Output | User outputs (directly to 7-segment display or RP2040) |
| `uio[7:0]` | 8 bits | Bidirectional | User bidirectional I/O |
| `ena` | 1 bit | Input | Enable signal |
| `clk` | 1 bit | Input | Clock (up to ~66 MHz) |
| `rst_n` | 1 bit | Input | Active-low reset |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## Serial Interface

The TT FPGA board supports UART communication through the TinyTapeout I/O pins. Two serial pin configurations are available:

### Option 1 (Default TT UART)

| Signal | TT Pin | Direction (FPGA perspective) |
|--------|--------|------------------------------|
| RX | ui_in[3] | Input |
| TX | uo_out[4] | Output |

### Option 2 (Alternate)

| Signal | TT Pin | Direction (FPGA perspective) |
|--------|--------|------------------------------|
| RX | ui_in[7] | Input |
| TX | uo_out[0] | Output |

The RP2040 on the demo PCB can act as a USB-to-UART bridge, forwarding serial data between the USB-C port and the FPGA's UART pins.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## PMOD Headers

The demo PCB has 2 standard PMOD headers following the Digilent specification:

- Each header is a 12-pin connector (8 signal + 2 GND + 2 VCC)
- Signal voltage: 3.3V
- The PMOD signals are routed through the TinyTapeout bidirectional I/O (`uio`) or directly to the FPGA breakout board

These PMOD headers can be used for loopback testing in the fpgas.online infrastructure.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## Clock

The RP2040 generates a 50 MHz clock via PWM on GPIO16 (`RP_PROJCLK`). The
iCE40UP5K's internal PLL divides this down to a 12 MHz system clock for
LiteX SoC designs (see `designs/_shared/tt_fpga_crg.py`).

## 7-Segment Display

The demo PCB includes a 7-segment LED display connected to the `uo_out` pins. This provides immediate visual feedback from the FPGA design:

| Segment | TT Output Pin |
|---------|--------------|
| a | uo_out[0] |
| b | uo_out[1] |
| c | uo_out[2] |
| d | uo_out[3] |
| e | uo_out[4] |
| f | uo_out[5] |
| g | uo_out[6] |
| dp | uo_out[7] |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## DIP Switches

The demo PCB has DIP switches connected to the `ui_in` pins, allowing manual input to the FPGA design during development and testing.

## Programming

The RP2040 programs the iCE40UP5K over SPI using the `fabricfox` MicroPython
module (PIO-accelerated or bitbang fallback).

```bash
python3 designs/_host/tt_fpga_program.py /dev/ttyACM0 bitstream.bin
```

**Programming workflow:**

1. Upload `.bin` to `/bitstreams/custom.bin` on the RP2040 via `mpremote`
2. Enter raw REPL and execute a MicroPython script that:
   - Asserts `CRESET` (GPIO1) to reset the FPGA
   - Transfers the bitstream over SPI (SCK=GPIO6, MOSI=GPIO3, SS=GPIO5)
   - Releases `CRESET` and waits for FPGA `CDONE`
   - Starts the 50 MHz clock on GPIO16
3. For PMOD tests: release all GPIO pins to high-Z (`--gpio-release`)

**SPI Flash:** The breakout board also has SPI flash (CS_N=pin 16, CLK=pin 15,
MOSI=pin 14, MISO=pin 17) for persistent bitstream storage, used by
the SPI Flash ID test.

## LiteX Integration

| Property | Value |
|----------|-------|
| FPGA | iCE40UP5K (same as Fomu) |
| Toolchain | Yosys + nextpnr-ice40 (open source, IceStorm flow) |

The TT FPGA board does not have a dedicated LiteX platform file in litex-boards. Designs target the iCE40UP5K with a custom pin constraint file matching the TinyTapeout I/O interface.

## Deployment

Eight TT FPGA Demo Boards across two sites. Four are deployed at
Welland, four are pending deployment at PS1.

| Site    | Host | RPi       | IP          | Switch Port | RP2040 Serial      |
|---------|------|-----------|-------------|-------------|---------------------|
| Welland | pi27 | RPi 4 2GB | 10.21.0.127 | 27          | `4df39a7a6856f86f` |
| Welland | pi29 | RPi 4 2GB | 10.21.0.129 | 29          | `fd1a167bd863a198` |
| Welland | pi31 | RPi 4 2GB | 10.21.0.131 | 31          | `8c46329b33590ecb` |
| Welland | pi33 | RPi 4 8GB | 10.21.0.133 | 33          | `a2961e5cac65b25f` |
| PS1     | TBD  | TBD       | TBD         | TBD         | TBD                |
| PS1     | TBD  | TBD       | TBD         | TBD         | TBD                |
| PS1     | TBD  | TBD       | TBD         | TBD         | TBD                |
| PS1     | TBD  | TBD       | TBD         | TBD         | TBD                |

Each RPi connects to a TT FPGA board via USB-C and has a PMOD HAT for
GPIO-level control of the TT I/O pins. RPis are powered and networked
through PoE switches at each site.

**USB device:** `/dev/ttyACM0` (VID:PID `2e8a:0005` — RP2040 MicroPython).

| Site    | Gateway                               | Network       |
|---------|---------------------------------------|---------------|
| Welland | `tweed.welland.mithis.com` (10.21.0.1) | 10.21.0.0/16 |
| PS1     | `ps1.fpgas.online` (10.21.0.1)        | 10.21.0.0/24 |

See the [deployment checklist](deployment-checklist.md) for the steps
to bring up the PS1 boards.

## Test Infrastructure

The RP2040 provides bitstream loading, clock generation, and USB-to-UART
bridging. Three host-side wrapper scripts handle the RP2040 interaction:

| Script                                                              | Purpose                                          |
|---------------------------------------------------------------------|--------------------------------------------------|
| [`tt_fpga_program.py`](../../designs/_host/tt_fpga_program.py)      | Upload and program bitstream via mpremote         |
| [`tt_test_wrapper.py`](../../designs/_host/tt_test_wrapper.py)      | Program + UART bridge (PTY) + run test            |
| [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)      | Program + release GPIOs + hand off to RPi GPIO test |

### Available Tests

| Test           | Bitstream                                                                            | Wrapper                                                            | What it verifies                     |
|----------------|--------------------------------------------------------------------------------------|--------------------------------------------------------------------|--------------------------------------|
| UART echo      | [`uart/.../tt_fpga_platform.bin`](../../designs/uart/build/tt/gateware/)              | [`tt_test_wrapper.py`](../../designs/_host/tt_test_wrapper.py)     | Serial TX/RX via RP2040 bridge       |
| SPI Flash ID   | [`spi-flash-id/.../tt_fpga_platform.bin`](../../designs/spi-flash-id/build/tt/gateware/) | [`tt_test_wrapper.py`](../../designs/_host/tt_test_wrapper.py) | JEDEC ID readback from on-board flash |
| PMOD loopback  | [`pmod-loopback/.../top.bin`](../../designs/pmod-loopback/build/tt/)                  | [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)     | GPIO inversion across wired pin pairs |
| PMOD pin ID    | [`pmod-pin-id/.../top.bin`](../../designs/pmod-pin-id/build/tt/)                      | [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)     | UART TX on each GPIO pin             |

### Test Execution

Tests are orchestrated by [`verify_hardware.py`](../../verify_hardware.py), which uploads the wrapper
scripts and bitstreams to the RPi, then runs the appropriate test:

```bash
uv run python verify_hardware.py --board tt --host pi33.tweed.welland.mithis.com
```

## Known Workarounds

### GPIOMap firmware mismatch

All deployed boards load `GPIOMapTT04` firmware, but the TTDBv3 hardware
uses different GPIO assignments. The `pin_indices()` function returns
wrong pin numbers. **Workaround:** all host scripts hardcode the correct
GPIO pins (SPI: SCK=6, MOSI=3, SS=5, CRESET=1; UART: TX=GPIO20, RX=GPIO37).

### DemoBoard() hang on boot

The stock RP2040 `main.py` calls `DemoBoard()` which probes I2C and can
hang permanently, making the board unrecoverable without a physical reset.
**Workaround:** `tt_test_wrapper.py` installs a safe no-op `main.py` after
each test run. Boards pi27, pi29, and pi31 are currently hung from earlier
runs before this workaround was added — they need a physical board reset.

### RP2040 PWM first-call bug

The first `PWM()` call on GPIO16 produces a stuck-HIGH output instead of
oscillation. **Workaround:** deinit and recreate the PWM object:

```python
clk = PWM(Pin(16))
clk.deinit()
utime.sleep_ms(1)
clk = PWM(Pin(16))  # Second call oscillates correctly
```

### SPI kernel module conflict

RPi GPIO7-11 overlap with the SPI0 bus and conflict with PMOD HAT pins
(JA/JB pins 2-4). **Workaround:** unload `spidev` and `spi_bcm2835`
kernel modules before running PMOD tests.

## References

- TinyTapeout Demo PCB design: <https://github.com/TinyTapeout/tt-demo-pcb>
- TinyTapeout PCB specifications: <https://tinytapeout.com/specs/pcb/>
- TinyTapeout FPGA Breakout Guide: <https://tinytapeout.com/guides/fpga-breakout/>
- TT FPGA Demo repository: <https://github.com/efabless/tt-fpga-demo>
- TinyTapeout main site: <https://tinytapeout.com>
