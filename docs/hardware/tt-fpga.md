\[[top](./README.md)\] \[[pinmap](./tt-fpga-pin-mapping.md)\] \[[pmod standards](./pmod-tt.md)\] \[[info](https://tinytapeout.com/guides/fpga-breakout/)\] \[[platform](../../designs/_shared/tt_fpga_platform.py)\]

# TinyTapeout FPGA Demo Board

The TinyTapeout (TT) FPGA Demo Board is a development platform that combines an FPGA breakout board (Lattice iCE40UP5K) with the TinyTapeout demo PCB (its microcontroller is an RP2350 on a version 3 demo board, the one our tooling is written for; a version 2 demo board has an RP2040). It allows testing TinyTapeout designs on real FPGA hardware before silicon fabrication.

## Installing the TT FPGA Packages

Add the fpgas.online APT repository first (the steps under [Installing](../verify.md#installing) in the boot check's documentation), then on the demo board's Pi:

```bash
sudo apt install fpgas-online-tt-fpga
```

| Package | Installs |
|---------|----------|
| `fpgas-online-tt-fpga` | installs everything below to check a TT FPGA Demo Board, and turns the boot check (`fpgas-verify.service`) on for it |
| `fpgas-online-tt-fpga-tools` | the board's module of `fpgas_online_verify`, and `fpgas-tt-fpga-verify`; with `python3-serial` and `python3-libgpiod` (the PMOD HAT scan), and recommending `micropython-mpremote` and `raspi-utils-core` (`pinctrl`, which puts back the Pi's SPI/UART/I2C pin functions after the scan; Raspberry Pi OS only) |
| `fpgas-online-tt-fpga-bitstreams` | the test bitstreams built by the same commit's CI, in `/usr/share/fpgas-online/tt-fpga/bitstreams/` |
| `fpgas-online-verify` | `fpgas-verify`, the unit, and the host test scripts |

`fpgas-online-tt` is a different package: the TT site's own.

The check, at each boot:

1. It finds the board by its Raspberry Pi microcontroller on USB (`2e8a:0005` or `2e8a:000f`, MicroPython's serial port).
2. That does not say whether the demo board carries the FPGA breakout or a Tiny Tapeout chip, so the check asks the board itself (below) and loads a design only into a board that said it is an FPGA board ([Which Tiny Tapeout board it is](../verify.md#which-tiny-tapeout-board-it-is)).
3. Every board first has what it said judged by [the `sdk` test](../verify.md#the-sdk-test), which loads nothing; for a board with a Tiny Tapeout chip that is the only test so far, and such a board fails until its Pmod cabling can be tested (the report says so).
4. On an FPGA board it then loads the PMOD pin identification design and checks the PMOD HAT cabling against the expected map (ui_in on HAT JA, uio on JB, uo_out on JC, the [pin mapping](tt-fpga-pin-mapping.md)); a miswired HAT fails the board.
5. It then loads the UART test design through that microcontroller (`tt_fpga_program.py`, over `mpremote`), and runs its host test through the UART bridge on `/dev/ttyACM0`.
6. There is no SPI flash test: the breakout has no flash. Nothing is written to the demo board: for every load the microcontroller reads the bitstream from the Pi over the serial link (see [Programming](#programming)). The board has no flash to compare, so what `changed` compares is its USB serial number.
7. `mpremote` is `micropython-mpremote` in trixie, but only in bookworm-backports for bookworm: without it the check reports an `error`.
8. Only the PMOD loopback test is left to `fpgas-tt-fpga-debug` (`sudo fpgas-tt-fpga-debug --variant tt-fpga test pmod`).
9. When the tests are done the check streams one more design, which moves the seven-segment display and is left running ([what the TT FPGA is left running](../verify.md#what-the-tt-fpga-is-left-running)); if that load fails the board still passes, with a warning in the report.

Before the first test, while it holds `/dev/ttyACM0`, the check:

1. Reads whether the board's `main.py` is still the SDK's own (`tt_main_py.py`, with or without rpi-hwid; a changed one is an `error`).
2. Starts the board's SDK (`tt_sdk_start.py`, see [The SDK's main.py](#the-sdks-mainpy)).
3. Runs `rpi-hwid tinytapeout --json --no-stop-service`, both only when [rpi-hwid](https://github.com/mithro/rpi-hwid) is installed (`python3-rpi-hwid`, which `fpgas-online-verify` suggests, from rpi-hwid's own apt repository). rpi-hwid asks the Tiny Tapeout SDK on the RP2350 which microcontroller, chip, demo board and SDK release this is. The answer goes into the board's identity, for rpi-hwid's Tiny Tapeout label ([TT FPGA identity](../verify.md#tt-fpga-identity), [Tiny Tapeout fields](../identity.md#tiny-tapeout-fields)).

Without rpi-hwid the board cannot be asked which Tiny Tapeout board it is: the check is an `error` and nothing is loaded.

It runs at every boot of the Welland TT FPGA boards: [current results](../verify.md#current-results).

**Check the board now**, or run one test with its output live (`fpgas-tt-fpga-debug` is in `fpgas-online-tt-fpga-debug`):

```bash
sudo fpgas-tt-fpga-verify --no-publish --report -  # this board only, the JSON report on stdout
sudo fpgas-tt-fpga-debug --variant tt-fpga test uart  # load one test's design and run its test
```

What the results mean, the report, `changed` and `--update`, the debug tool and common failures: [verify.md](../verify.md#reading-the-result).

## Key Specifications

| Parameter | Value |
|-----------|-------|
| FPGA | Lattice iCE40UP5K (on FPGA breakout board) |
| Logic cells | 5,280 LUT4s |
| SPRAM | 128 KB (4 x 32 KB blocks) |
| DPRAM (EBR) | 120 Kbit (15 x 8 Kbit blocks) |
| Controller | RP2350 (on the version 3 demo PCB; RP2040 on version 2) |
| USB | USB-C (via RP2350) |
| Display | 7-segment LED display |
| DIP switches | Configuration switches |
| PMOD headers | 3x standard PMOD (following Digilent spec): input, bidirectional, output ([pmod-tt.md](pmod-tt.md#demo-board-pmod-connectors)) |
| Max clock | ~66 MHz |
| I/O voltage | 3.3V |

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/), [TinyTapeout FPGA Breakout Guide](https://tinytapeout.com/guides/fpga-breakout/)

## Architecture

The TT FPGA Demo Board consists of two PCBs:

1. **TinyTapeout Demo PCB** (bottom): Contains the RP2350 microcontroller, USB-C connector, 7-segment display, DIP switches, and PMOD headers. This PCB is designed to interface with TinyTapeout ASICs but also accepts the FPGA breakout board.

2. **FPGA Breakout Board** (top): Contains the iCE40UP5K FPGA; it has no SPI flash. It plugs into the demo PCB's chip socket, presenting the same interface as a TinyTapeout ASIC.

```
┌──────────────────────────────┐
│    FPGA Breakout Board       │
│    (iCE40UP5K)               │
│                              │
│    ┌────────────────────┐    │
│    │  Pin headers down  │    │
│    └────────────────────┘    │
└──────────────┬───────────────┘
               │ (plugs into)
┌──────────────┴───────────────┐
│    TinyTapeout Demo PCB      │
│                              │
│  [USB-C] [RP2350] [7-seg]   │
│  [DIP SW] [3 x PMOD header] │
└──────────────────────────────┘
```

## TinyTapeout I/O Interface

The FPGA implements a TinyTapeout-compatible interface with the following signals:

| Signal Group | Width | Direction | Description |
|-------------|-------|-----------|-------------|
| `ui_in[7:0]` | 8 bits | Input | User inputs (directly from DIP switches or RP2350) |
| `uo_out[7:0]` | 8 bits | Output | User outputs (directly to 7-segment display or RP2350) |
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

The RP2350 on the demo PCB can act as a USB-to-UART bridge, forwarding serial data between the USB-C port and the FPGA's UART pins.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## PMOD Headers

The demo PCB has 3 standard PMOD headers following the Digilent specification, one for each signal group (`ui_in`, `uio`, `uo_out`); which one is cabled to which Pmod HAT port is in [tt-fpga-cables.md](../wiring/tt-fpga/generated/tt-fpga-cables.md):

- Each header is a 12-pin connector (8 signal + 2 GND + 2 VCC)
- Signal voltage: 3.3V

These PMOD headers can be used for loopback testing in the fpgas.online infrastructure.

Source: [TinyTapeout PCB Specs](https://tinytapeout.com/specs/pcb/)

## Clock

The RP2350 generates a 50 MHz clock via PWM on GPIO16 (`RP_PROJCLK`). The
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

The RP2350 programs the iCE40UP5K over SPI using the `fabricfox` MicroPython
module (PIO-accelerated or bitbang fallback).

```bash
python3 designs/_host/tt_fpga_program.py /dev/ttyACM0 bitstream.bin
```

**Programming workflow:**

1. `mpremote mount` shows a temporary directory on the Pi, holding a copy of the bitstream and nothing else, to
   the RP2350 as `/remote`, served over the serial link. **Nothing is written to the demo board's filesystem**: no file is copied to it and no directory
   is made on it.
2. A MicroPython script, run in the raw REPL, reads the bitstream from `/remote` and:
   - Asserts `CRESET` (GPIO1) to reset the FPGA
   - Transfers the bitstream over SPI (SCK=GPIO6, MOSI=GPIO3, SS=GPIO5)
   - Releases `CRESET` (`CDONE` is not read: the tests that follow are what show the design is running)
   - Starts the 50 MHz clock on GPIO16
3. For PMOD tests: release all GPIO pins to high-Z (`--gpio-release`)

**No SPI flash:** the breakout has no flash. In its published design
([TinyTapeout/breakout-pcb, `ASIC-simulator/ttdbv3-fpga-ICE40UP5k`](https://github.com/TinyTapeout/breakout-pcb/tree/6e3725f7fc5707d0cbe7632c39b867da740d10d7/ASIC-simulator/ttdbv3-fpga-ICE40UP5k),
checked 2026-10-04) the iCE40's configuration SPI (SPI_SS=pin 16, SPI_SCK=pin 15,
SPI_SO=pin 14, SPI_SI=pin 17) goes only to the demo board's microcontroller, which
loads the bitstream at every power-up. So there is no SPI Flash ID test for
this board ([#52](https://github.com/fpgas-online/fpgas.online-test-designs/issues/52)).

## LiteX Integration

| Property | Value |
|----------|-------|
| FPGA | iCE40UP5K (same as Fomu) |
| Toolchain | Yosys + nextpnr-ice40 (open source, IceStorm flow) |

The TT FPGA board does not have a dedicated LiteX platform file in litex-boards. Designs target the iCE40UP5K with a custom pin constraint file matching the TinyTapeout I/O interface.

## Deployment

Eight TT FPGA Demo Boards across two sites. Four are deployed at
Welland on S3300 ports 33–36 (Tim's rule for that switch: port N carries
Tiny Tapeout board N; the FPGA emulation boards take the 33–36 block), four
are pending deployment at PS1. The Welland four are the public
**fpga-1 … fpga-4** boards on [tinytapeout.fpgas.online](https://tinytapeout.fpgas.online).
Probed live 2026-09-03.

| Site    | Host       | Board page | RPi (rev)                | IP         | Switch Port | RPi MAC           | RP2350 Serial      | `verify_hardware.py` |
|---------|------------|------------|--------------------------|------------|-------------|-------------------|--------------------|----------------------|
| Welland | pi-sw2-p33 | [fpga-1](https://tinytapeout.fpgas.online/board/fpga-1/) | RPi 4 2 GB Rev 1.5 (b03115) | 10.21.2.33 | S3300 33 | e4:5f:01:97:0e:77 | `4df39a7a6856f86f` | welland-pi27 |
| Welland | pi-sw2-p34 | [fpga-2](https://tinytapeout.fpgas.online/board/fpga-2/) | RPi 4 2 GB Rev 1.5 (b03115) | 10.21.2.34 | S3300 34 | e4:5f:01:97:27:f2 | `fd1a167bd863a198` | welland-pi29 |
| Welland | pi-sw2-p35 | [fpga-3](https://tinytapeout.fpgas.online/board/fpga-3/) | RPi 4 2 GB Rev 1.5 (b03115) | 10.21.2.35 | S3300 35 | e4:5f:01:97:0c:e3 | `8c46329b33590ecb` | welland-pi31 |
| Welland | pi-sw2-p36 | [fpga-4](https://tinytapeout.fpgas.online/board/fpga-4/) | RPi 4 8 GB Rev 1.5 (d03115) | 10.21.2.36 | S3300 36 | e4:5f:01:8e:02:27 | `a2961e5cac65b25f` | welland-pi33 |
| PS1     | TBD        | —          | TBD                      | TBD        | TBD         | TBD               | TBD                | —                    |
| PS1     | TBD        | —          | TBD                      | TBD        | TBD         | TBD               | TBD                | —                    |
| PS1     | TBD        | —          | TBD                      | TBD        | TBD         | TBD               | TBD                | —                    |
| PS1     | TBD        | —          | TBD                      | TBD        | TBD         | TBD               | TBD                | —                    |

Each RPi connects to a TT FPGA board via USB-C, has a Digilent Pmod HAT for
GPIO-level control of the TT I/O pins, and an ov5647 camera publishing a live
feed of the board. RPis are powered and networked through PoE switches at
each site. Each board's `status.json` (e.g.
`https://tinytapeout.fpgas.online/board/fpga-1/status.json`) reports the Pi
daemon's `/health` plus `reachable`, and is the quickest liveness check.

**Board firmware:** all four run TT SDK **3.1.0** (the stock `ttdbv3` build
stalls at boot). With 3.1.0 the SDK's `tt` object comes up as `Shuttle FPGA`
and the Commander connects.

**USB device:** `/dev/ttyACM0` (VID:PID `2e8a:0005` — MicroPython Board in FS
mode), with a udev symlink **`/dev/ttboard`** that the Pi daemon opens.

**The serial port has a permanent owner.** Every TT host runs the
[`fpgas-tt`](https://github.com/fpgas-online/fpgas.online-tt) daemon
(`fpgas-online-tt` 0.0.post52, reports version 0.1.0), which holds
`/dev/ttboard` open at 115200 baud and fans it out as a WebSocket on port 8765
(`WS /serial`, `GET /health`, reachable only from the gateway thanks to the
per-port VLANs). Verified 2026-09-03: `fuser /dev/ttyACM0` shows the daemon's
python3 process on all ten TT hosts. Consequences for this repo's tooling:

- `mpremote` / `tt_fpga_program.py` cannot open `/dev/ttyACM0` while the
  daemon runs. Stop it first (`sudo systemctl stop fpgas-tt`) and start it
  again afterwards, or drive the board through the daemon's `/serial` socket.
- The bitstream-loading and design-listing features live in the daemon
  (`/designs`, `/bitstream`, demos via the `fpgas-online-tt-demos` package),
  which is what the public site uses.

| Site    | Gateway                               | Network       |
|---------|---------------------------------------|---------------|
| Welland | [welland.fpgas.online](https://welland.fpgas.online) / [tinytapeout.fpgas.online](https://tinytapeout.fpgas.online) (10.21.0.1) | 10.21.0.0/16, one VLAN per switch port: Pi = `10.21.<switch>.<port>` |
| PS1     | [ps1.fpgas.online](https://ps1.fpgas.online) (10.21.0.1)         | 10.21.0.0/24 |

See the [deployment checklist](deployment-checklist.md) for the steps
to bring up the PS1 boards.

## Test Infrastructure

The RP2350 provides bitstream loading, clock generation, and USB-to-UART
bridging. Three host-side wrapper scripts handle the RP2350 interaction:

| Script                                                              | Purpose                                          |
|---------------------------------------------------------------------|--------------------------------------------------|
| [`tt_fpga_program.py`](../../designs/_host/tt_fpga_program.py)      | Program the iCE40 from the Pi via mpremote        |
| [`tt_test_wrapper.py`](../../designs/_host/tt_test_wrapper.py)      | Program + UART bridge (PTY) + run test            |
| [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)      | Program + release GPIOs + hand off to RPi GPIO test |

### Available Tests

| Test           | Bitstream                                                                            | Wrapper                                                            | What it verifies                     |
|----------------|--------------------------------------------------------------------------------------|--------------------------------------------------------------------|--------------------------------------|
| UART echo      | [`uart/.../tt_fpga_platform.bin`](../../designs/uart/build/tt-fpga-yosys-nextpnr/gateware/)              | [`tt_test_wrapper.py`](../../designs/_host/tt_test_wrapper.py)     | Serial TX/RX via RP2350 bridge       |
| PMOD loopback  | [`pmod-loopback/.../tt_fpga_platform.bin`](../../designs/pmod-loopback/build/tt-fpga-yosys-nextpnr/gateware/) | [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)     | GPIO inversion across wired pin pairs |
| PMOD pin ID    | [`pmod-pin-id/.../tt_fpga_platform.bin`](../../designs/pmod-pin-id/build/tt-fpga-yosys-nextpnr/gateware/) | [`tt_pmod_wrapper.py`](../../designs/_host/tt_pmod_wrapper.py)     | UART TX on each GPIO pin             |

### Test Execution

Tests are orchestrated by [`verify_hardware.py`](../../verify_hardware.py), which uploads the wrapper
scripts and bitstreams to the RPi, then runs the appropriate test:

```bash
uv run python verify_hardware.py --board tt --host welland-pi33
```

`verify_hardware.py`'s `HOSTS` table names these boards `welland-pi27` …
`welland-pi33`, with flat `10.21.0.1xx` addresses that Welland does not use
([#17](https://github.com/fpgas-online/fpgas.online-test-designs/issues/17));
the boards are `pi-sw2-p33` … `pi-sw2-p36` at `10.21.2.33` … `10.21.2.36`. The
`fpgas-tt` daemon must be stopped before the wrapper can open the serial port
(see [Deployment](#deployment)).

## Known Workarounds

### GPIOMap firmware mismatch

The stock `ttdbv3` firmware loads `GPIOMapTT04`, but the TTDBv3 hardware uses
different GPIO assignments, so `pin_indices()` returns wrong pin numbers.
**Workaround:** all host scripts hardcode the correct GPIO pins (SPI: SCK=6,
MOSI=3, SS=5, CRESET=1; UART: TX=GPIO20, RX=GPIO37). SDK 3.1.0's map has not
been checked; the hardcoded pins are correct either way.

### The SDK's main.py

The board's `main.py` is the Tiny Tapeout SDK's. It builds the `tt` object when the board starts
(`DemoboardDetect.probe()`, `DemoBoard.get()`), and that start-up state is what everything else relies on:
`rpi-hwid tinytapeout` reads it to say what the board is (it reads only what the SDK built; it does not start
the SDK), and the public site and the `fpgas-tt` daemon expect the SDK to be there.

**Nothing replaces `main.py`.** Until 2026-10, `tt_test_wrapper.py` overwrote it with a no-op ("TT FPGA board
ready") after every load, as a workaround for the stock `ttdbv3` firmware hanging in `DemoBoard()`.
SDK 3.1.0 boots cleanly, and with the no-op the SDK never started, so the boot check could not identify the
board ([#117](https://github.com/fpgas-online/fpgas.online-test-designs/issues/117)). The wrapper no longer
touches it.

The boot check starts the SDK before it asks who the board is: `tt_sdk_start.py` soft-resets the board from the
friendly REPL, which runs `main.py`, and waits for the SDK's last boot line (`tt.sdk_version=...`; a 1.x
release, which a TT03p5 board runs, has no such line and is recognised by its `TT SDK v1...` line once it is
back at the prompt). This is
needed even with the right `main.py`: a soft reset from the raw REPL, which is what `mpremote` does, does not
run `main.py`, so after any load the `tt` object is gone until the next start. A board whose `main.py` does not
start the SDK fails the check with that reason.

**A visitor can change the board; the check says so.** The Commander on tinytapeout.fpgas.online gives every
visitor the board's Python prompt, and with it the board's files (Tim, 2026-10-05: the prompt stays). So the
boot check first reads the SHA-256 of the board's `main.py` (`tt_main_py.py`) and compares it with the one
recorded for the SDK release the board runs: a `main.py` that was replaced or edited is an `error` with that
reason, not a pass. Every release from 1.0.0 to 3.1.1 is recorded (the releases demo boards with a Tiny
Tapeout chip run are among them: 1.2.x and 2.0.x); a board on a release with no recorded `main.py` fails the
same way until the release is added to `tt_main_py.py`.

**No code of ours writes to a demo board.** The boot check and the debug tools change no file on it: not
`main.py`, and no bitstream (see [Programming](#programming)); `tests/test_tt_host_scripts.py` holds every
string the host scripts send to a board, or give to `mpremote`, to that. The one file that does change is not
ours: the SDK's own `main.py` rewrites its `boot.log` every time it starts, at power-on and at the check's
soft reset alike. A board whose `main.py` was overwritten before this change keeps failing its check, with the reason, until
the SDK's own `main.py` (`src/main.py` of the SDK release the board runs) has been put back on it by hand. That
is a deliberate one-off per board, not something the tooling does.

Boards the old loader ran on still hold a `/bitstreams/custom.bin`: the last test bitstream it copied there.
Nothing reads it, nothing removes it, and it is not the design that is loaded.

After a check the board is at the raw-REPL's state again (the loads soft-reset it from the raw REPL), so the
`tt` object is gone until the next friendly-REPL soft reset: the Commander makes one when it connects.

If a board does hang in `DemoBoard()` (the stock `ttdbv3` build does), a power cycle of its Pi resets it; the
RP2's mass-storage bootloader path stalls on Pi 3B+ hosts, so reflashing from a Pi 3B+ needs the PICOBOOT path
rather than MSC.

### RP2350 PWM first-call bug

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
