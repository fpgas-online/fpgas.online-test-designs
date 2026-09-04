# TT PMOD Wiring

Checks the three ribbon cables between a Tiny Tapeout demo board's PMOD
connectors (`ui_in`, `uio`, `uo_out`) and the Raspberry Pi PMOD HAT ports
(JA, JB, JC), bit for bit. The demo board's RP2040/RP2350 (running the Tiny
Tapeout MicroPython SDK) is the stimulus and the Pi's GPIOs are the observer,
so no bitstream and no ASIC design are needed. This is the only wiring test
that works on the deployed TT **ASIC** boards.

Unlike the [PMOD loopback](../pmod-loopback/) test, whose drive and read
sides use the same pin permutation, this test can tell a swapped bit from a
correct one, and an open from a short.

## How it works

1. The Pi stops the `fpgas-tt` daemon (it owns the serial port; a systemd
   timer restarts it in ten minutes regardless), disables SysRq (the serial
   console shares GPIO14/15 with HAT port JC), unloads the SPI modules (they
   claim GPIO7-11), and requests all 21 HAT GPIOs as inputs in one go.
2. A small command server is pushed to the RP2 over the raw REPL. Through the
   SDK it stops the project clock, selects the shuttle's `tt_um_factory_test`
   and resets it. That project does `uo_out = uio_in` with `uio` as inputs
   while `ui_in[0]` is low.
3. `ui_in` bits that something else holds (a DIP switch, the console) are
   found with the RP2's pulls and left alone; the rest are driven low.
4. **Reverse walk**: the Pi pulls one HAT line up at a time and the RP2 reads
   which of its inputs follows. Contention-free, and independent of the chip,
   so a JA/JB ribbon swap cannot hide behind the loopback.
5. The factory test is **confirmed on-board**: the RP2 drives patterns on the
   `uio` bits that float and reads them back on its own `uo_out` pins, then
   checks the project's counter is zero. Only then is the loopback trusted.
6. **Forward walks**: the RP2 walks a 1 across `ui_in`, then across `uio`;
   the Pi records which HAT line follows each bit. With the loopback, each
   `uio` bit is expected on its JB line and, through the chip, its JA line.
   (JA2-4 and JB2-4 are the same Pi lines on the HAT; the chip agrees with
   the RP2 there once it has propagated, so the RP2 drives them at 12 mA and
   reads back.)
7. **Latch test** on those shared lines: drive, release to a pull-down, read.
   The loop through both ribbon wires holds a 1 only if both are present.
8. Everything is restored: RP2 pins released and the SDK mode re-applied, Pi
   lines released, the UART function back on GPIO14/15, SysRq and the daemon
   back as they were.

Every walk runs twice and every sample is taken three times; disagreement
fails the run rather than guessing. `uo_out` is only ever driven by the chip;
without a confirmed loopback it is reported as **not tested**.

## Usage (on the Pi)

```sh
sudo python3 check_tt_pmod_wiring.py                     # verify the standard cabling
sudo python3 check_tt_pmod_wiring.py --discover          # print what is wired where
sudo python3 check_tt_pmod_wiring.py --asic-project none # leave the ASIC project alone
sudo python3 check_tt_pmod_wiring.py --controller rp2350 # demo board v3 (TT09+, TT FPGA)
```

Prints a per-signal table, the measured map in the
[`tt-fpga-pin-mapping.md`](../../docs/hardware/tt-fpga-pin-mapping.md) format
for pasting into the docs, and `RESULT: PASS` or `RESULT: FAIL`.

From the repo, `uv run python verify_hardware.py --test tt-pmod-wiring`
uploads and runs it on every `tt-asic` host.

Requirements on the Pi: `python3-libgpiod` (v1.6+ or v2.x), root or
passwordless sudo. The SDK on the board must know `tt_um_factory_test`
(TT SDK 2.x+); on TT03p5 (firmware 1.2.2) use `--asic-project none`.

## Unit tests

```sh
uv run --extra dev pytest designs/tt-pmod-wiring
```

The tests drive the real measurement sequence against a simulated board
(fake RP2 over a socket, an electrical model of the ribbons, the HAT short,
the Pi's fixed I2C pull-ups and the chip) for correct, swapped, open and
shorted wirings, and check that no step ever settles with two drivers on
one net.

## Key files

- `host/check_tt_pmod_wiring.py` — the Pi-side script, with the MicroPython
  command server embedded
- `host/test_tt_pmod_wiring.py` — unit and simulated end-to-end tests
- [`docs/tests/tt-pmod-wiring.md`](../../docs/tests/tt-pmod-wiring.md) — test specification
- [`docs/plans/2026-09-04-tt-pmod-wiring-test.md`](../../docs/plans/2026-09-04-tt-pmod-wiring-test.md) — design
