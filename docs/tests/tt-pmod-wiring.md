# TT PMOD Wiring Test

## Purpose

Verify that the three ribbon cables between a Tiny Tapeout demo board's PMOD
connectors and the Raspberry Pi PMOD HAT are the right ribbons on the right
ports with every bit in the right place. The demo board's own RP2040/RP2350
(running the Tiny Tapeout MicroPython SDK) drives one TT signal at a time
while the Pi samples every HAT GPIO, so a swapped bit, an open line and a
short each produce a distinct, attributable result.

No bitstream, no ASIC design and no FPGA toolchain are involved, which is what
makes this the only wiring test that runs on the deployed TT **ASIC** boards.

## Target Boards

| Board | Controller | Cabling checked | Status |
|-------|------------|-----------------|--------|
| TT ASIC demo board v2 (TT06-TT08) | RP2040 | JC → `ui_in`, JB → `uio`, JA → `uo_out` | Active |
| TT ASIC demo board (TT04, TT05) | RP2040 | same | Active |
| TT ASIC demo board (TT03p5, firmware 1.2.2) | RP2040 | `ui_in` and floating `uio` bits only (`--asic-project none`) | Active |
| [TT FPGA Demo Board v3](../hardware/tt-fpga.md) / TT09+ | RP2350 | `--controller rp2350`; `uo_out` needs a loopback design | Untested |

## Prerequisites

- Raspberry Pi with the PMOD HAT and the demo board's USB connected
- `python3-libgpiod` on the Pi (`apt install python3-libgpiod`, v1.6+ or v2.x)
- Root or passwordless sudo (the script stops/starts `fpgas-tt`, sets
  `kernel.sysrq`, stops the serial getty and unloads `spidev`/`spi_bcm2835`)
- The board's SDK must know the shuttle's `tt_um_factory_test` project for
  full coverage (TT SDK 2.x+)

## How It Works

### Who drives what

Only one party ever drives a net, and the RP2 reads every pin back after
driving it so a lost fight is seen within one step:

| Net | Driven by | Observed by |
|-----|-----------|-------------|
| `ui_in[k]` | RP2 (as in the SDK's `ASIC_RP_CONTROL` mode), unless something holds the bit | Pi, HAT port JC |
| `uio[k]` | RP2, once the factory test is confirmed on-board (or, without it, only bits that follow the RP2's pulls) | Pi, HAT port JB (and JA through the chip) |
| `uo_out[k]` | the ASIC only | Pi, HAT port JA |

The chip's `tt_um_factory_test` (identical on every shuttle) does
`uo_out = uio_in` with `uio_oe = 0` while `ui_in[0]` is low, so walking `uio`
also exercises the `uo_out` ribbon through the chip. `ui_in` is held low for
the whole `uio` phase. The project is reset (clocked inside the reset) first
so its counter, which it puts on `uo_out` and `uio` whenever `ui_in[0]` is
high, is zero.

The HAT wires JA2-4 and JB2-4 to the same Pi lines (GPIO10/9/11, the SPI0
bus). With the factory test active the chip drives `uo_out[1:3]` to what it
sees on `uio[1:3]`, i.e. the same line, so each RP2 transition is a brief
hand-over that the RP2 drives at 12 mA and confirms by reading back. Without
the factory test those three bits are held by the chip's `uo_out` and are
left untested. Pi GPIO2/3 (JB10/JB9 = `uio[7:6]`) carry the Pi's fixed 1.8 kΩ
I2C pull-ups: the RP2 can drive them, but no weak pull can move them, so
they too are untested without the confirmed loopback.

### Sequence

1. Pi: stop `fpgas-tt` (and arm a ten-minute restart timer),
   `sysctl kernel.sysrq=0`, stop `serial-getty@*`, record the UART function
   of GPIO14/15, `rmmod spidev spi_bcm2835`, request the 21 HAT GPIOs as
   inputs with pull-down in a single request.
2. RP2 (raw REPL): start the command server; through the SDK, record the mode,
   stop the project clock, enable `tt_um_factory_test`, reset it with clocks.
3. `ui_in` pre-check: RP2 pull-up/pull-down probe with the Pi's bias off; bits
   that do not follow are held by a DIP switch or the console and are skipped.
   The rest are driven low and stay low.
4. Reverse walk: RP2 `ui_in[1:7]` and `uio` as pull-less inputs; the Pi pulls
   every line down, then each line up in turn, and the RP2 reports which pin
   followed. Lines the Pi cannot move (the chip's `uo_out`, GPIO2/3) are
   recorded as *held*.
5. Confirm the factory test: drive `0x5A`, `0xA5`, `0x00` on the `uio` bits
   that floated in a pull probe and read the RP2's own `uo_out` pins; then
   raise `ui_in[0]` and require `uo_out` and `uio` to read 0.
6. Walk `ui_in`: for each bit, drive it high then low; a Pi GPIO reading 1
   then 0 belongs to that bit. `readall` on the RP2 flags other RP2 inputs
   that followed (a board-side short).
7. Walk `uio` the same way (all eight bits at 12 mA when confirmed; only the
   floating bits at 2 mA otherwise, with the chip's reactions discounted).
8. Latch test on the shared bits (confirmed only): drive high, release to
   pull-down, read; 0 means one of the two ribbon wires is open.
9. Restore: RP2 pins released and `tt.mode` re-applied, friendly REPL; Pi
   lines released; UART function restored; `sysrq` restored; `fpgas-tt`
   started if it was running; restart timer cancelled.

Every walk runs twice and both passes must agree; every sample is three
consecutive reads that must agree. Disagreement fails the run.

### Protocol

The RP2 runs a line-oriented command server (`out g v [drive]` replying with
the read-back level, `in g none|up|down`, `read g`, `readall`, `release`,
`sdk init|project|reset|restore`, `ping`, `quit`); every command is answered
by one `TTW OK|VAL|VALS|ERR|PONG|BYE` line, optionally preceded by `TTW WARN`
lines, and the server releases every pin on exit. The Pi side is plain
termios, no pyserial.

## Pass/Fail Criteria

| Signal | Expected Pi GPIO | Required |
|--------|------------------|----------|
| `ui_in[k]` | its JC line | always |
| `uio[k]` | its JB line + its JA line through the chip | when the loopback is confirmed (strict) |
| `uio[k]` | its JB line | bits the pull probe found floating (no loopback) |

| Status | Meaning |
|--------|---------|
| `ok` | observed exactly the expected line(s), and the cross-checks agree |
| `open` | nothing followed the bit (ribbon unplugged or broken) |
| `short` | expected line plus others followed it, or another RP2 input followed on the board |
| `miswired` | a different line followed it, or the reverse walk put its own line elsewhere |
| `partial` | only some expected lines (e.g. the through-the-chip pin missing), or the latch test found one wire of a shared pair open |
| `contention` | the RP2 could not impose its level: something else drives that net |
| `untested` | not driven (held bit, chip-driven line, or `uo_out` without loopback) |

PASS requires every required row `ok`. With `--asic-project` set (the
default) the run is strict: the loopback must be confirmed and every `uio`
row is required. With `--asic-project none` only `ui_in` and the floating
`uio` bits are required and `uo_out` is reported as not tested. `--discover`
prints the measured map only.

Output ends with the measured map in the format of
[`tt-fpga-pin-mapping.md`](../hardware/tt-fpga-pin-mapping.md), the verdict
table, and `RESULT: PASS` / `RESULT: FAIL` (exit 0/1) as the last line for
`verify_hardware.py`.

## Usage

```sh
# On the Pi
sudo python3 check_tt_pmod_wiring.py
sudo python3 check_tt_pmod_wiring.py --discover
sudo python3 check_tt_pmod_wiring.py --asic-project none

# From the repo, over SSH
uv run python verify_hardware.py --test tt-pmod-wiring

# Dev-machine tests (simulated board)
uv run --extra dev pytest designs/tt-pmod-wiring
```

## Caveats

- The kernel console on `serial0` (GPIO14/15 = JC2/JC3) is taken over for
  the run; its pin function is put back afterwards where `pinctrl` or
  `raspi-gpio` exist. On these hosts the console is wired to the demo board
  anyway, which is the SysRq hazard the script guards against.
- A ribbon short between two `ui_in` (or two `uio`) lines makes two RP2
  outputs fight briefly during a walk. That is inherent to any walking-1 test
  and harmless at the RP2040's drive; the chip is never a party, and the
  read-back reports it as `contention`.
- `uo_out` can only be observed, never driven, so without a confirmed
  loopback it stays "not tested".
- `python3-libgpiod` is not yet in the Ansible role; on the read-only NFS
  root an `apt install` lasts until the next reboot.

## Pin Mapping Reference

- [RPi PMOD HAT](../hardware/rpi-hat-pmod.md) — HAT port to Pi GPIO
- [TinyTapeout PMOD layouts](../hardware/pmod-tt.md) — TT signal to PMOD pin and RP2 GPIO
- [TT FPGA pin mapping](../hardware/tt-fpga-pin-mapping.md) — the measured standard cabling
- [Design](../plans/2026-09-04-tt-pmod-wiring-test.md) — why the sequence is what it is
