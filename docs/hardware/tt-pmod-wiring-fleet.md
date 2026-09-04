\[[top](./README.md)\] \[[tt-fpga](./tt-fpga.md)\] \[[pmod hat](./rpi-hat-pmod.md)\] \[[test spec](../tests/tt-pmod-wiring.md)\]

# TT PMOD HAT wiring — measured fleet tables

Measured on 2026-09-04 with the [TT PMOD wiring test](../tests/tt-pmod-wiring.md)
(`designs/tt-pmod-wiring/host/check_tt_pmod_wiring.py`) on every Tiny Tapeout
host at Welland: the demo board's RP2040/RP2350 walks a 1 across its
`ui_in`/`uio` pins and transmits each pin's name at 1200 baud, the Pi reads
every PMOD HAT line, and on the ASIC boards the shuttle's `tt_um_factory_test`
(`uo_out = uio_in`) carries the `uio` stimulus back out on `uo_out`.

## Summary

| Host | Board | Chip | Controller | Ribbons (HAT port → TT group) | Chip loopback | Result |
| ---- | ----- | ---- | ---------- | ----------------------------- | ------------- | ------ |
| pi-sw2-p3 | tt03p5 | TT03p5 | rp2040 | JA→ui_in, JB→uio, JC→uo_out | no (SDK 1.2.2) | PASS (uo_out and 6 uio bits untested) |
| pi-sw2-p4 | tt04 | TT04 | rp2040 | all three ribbons seated one position off, see below | no | **FAIL** |
| pi-sw2-p5 | tt05 | TT05 | rp2040 | JA→ui_in, JB→uio, JC→uo_out | yes | PASS |
| pi-sw2-p6 | tt06 | TT06 | rp2040 | JA→ui_in, JB→uio, JC→uo_out | yes | PASS |
| pi-sw2-p7 | tt07 | TT07 | rp2040 | JA→ui_in, JB→uio, JC→uo_out | yes | PASS |
| pi-sw2-p8 | tt08 | TT08 | rp2040 | JA→ui_in, JB→uio, JC→uo_out | yes | PASS |
| pi-sw2-p33 | fpga-1 | TT FPGA | rp2350 | JA→ui_in, JB→uio, JC→uo_out | no (iCE40 in reset) | PASS (uo_out untested) |
| pi-sw2-p34 | fpga-2 | TT FPGA | rp2350 | JA→ui_in, JB→uio, JC→uo_out | no (iCE40 in reset) | PASS (uo_out untested) |
| pi-sw2-p35 | fpga-3 | TT FPGA | rp2350 | JA→ui_in, JB→uio, JC→uo_out | no (iCE40 in reset) | PASS (uo_out untested) |
| pi-sw2-p36 | fpga-4 | TT FPGA | rp2350 | JA→ui_in, JB→uio, JC→uo_out | no (iCE40 in reset) | PASS (uo_out untested) |

**The fleet convention is the `asic` profile: HAT JA carries `ui_in`, JB
carries `uio`, JC carries `uo_out`, TT bit k on PMOD pin k straight
through** (pins 1-4 and 7-10). This is the mirror of the older
[tt-fpga-pin-mapping.md](tt-fpga-pin-mapping.md) measurement (JC → `ui_in`,
JA → `uo_out`); the four FPGA hosts are cabled the `asic` way now too.

Consequences of the HAT's [JA2-4/JB2-4 short](rpi-hat-pmod.md) under this
cabling: **`ui_in[1:3]` and `uio[1:3]` are the same three Pi lines**
(GPIO10, 9, 11). A project whose `uio_oe` drives `uio[1:3]` fights the RP2
driving `ui_in[1:3]` in `ASIC_RP_CONTROL` mode, and from the Pi those six
signals cannot be told apart. Pi GPIO2/3 (JB10/JB9 = `uio[7:6]`) carry the
Pi's fixed 1.8 kΩ I2C pull-ups.

Other findings:

- TT03p5 (`pi-sw2-p3`) has a DIP switch on `ui_in[1]`; TT08 (`pi-sw2-p8`)
  on `ui_in[1]` and `ui_in[2]`. The RP2 out-drives them, as the SDK does,
  so the bits verified.
- The deployed boards' MicroPython lacks `machine.Pin(drive=)`; the RP2
  drove the shared lines at its default 4 mA and still won every hand-over
  against the chip's `uo_out` (read-back checked on every step).
- `designs/pmod-loopback/host/test_pmod_loopback.py`'s `tt` entry still
  encodes the old JC/JA permutation and does not match any host.

## pi-sw2-p4 (TT04): ribbons seated one position off

Every line the test could attribute on this host lands on **HAT pin
12 − TT pin** instead of HAT pin = TT pin:

| TT signal | TT PMOD pin | Measured HAT pin | Pi GPIO | Note |
| --------- | ----------- | ---------------- | ------- | ---- |
| ui_in[0] | 1 | 11 (GND) | — | held hard low: the pin is on the HAT's ground |
| ui_in[1] | 2 | JC10 | 6 | |
| ui_in[2] | 3 | JC9 | 5 | |
| ui_in[3] | 4 | JC8 | 12 | |
| ui_in[4] | 7 | 5 (GND) | — | held hard low: on the HAT's ground |
| ui_in[5] | 8 | JC4 | 17 | |
| ui_in[6] | 9 | JC3 | 15 | |
| ui_in[7] | 10 | JC2 | 14 | |
| uio[3] | 4 | JB8 | 13 | the only uio bit the running project left undriven |
| uo_out[3] | 4 | JA8 | 21 | seen through the project's uio → uo_out path |

So on this host the `ui_in` ribbon goes to JC, `uio` to JB and `uo_out` to
JA (the `fpga` orientation), and all three connectors are shifted by one
position: TT pin 1 and 7 sit on HAT ground pins, TT's ground pins 5/11 sit
on HAT signal pins 7/1, and the remaining bits are reversed within each row.
Re-seat the three ribbons at the HAT end (or the board end) and re-run; the
rest of the fleet shows the intended orientation is JA → `ui_in`.

## Per-host tables

Signal → RP2 GPIO → HAT pin → Pi GPIO, as measured. "walk + pin-id" means the
line followed the RP2's walking 1 and decoded the signal's transmitted name;
"loopback via uio[k]" means the `uo_out` line followed `uio[k]` through the
chip's factory-test project.

### pi-sw2-p3 (tt03p5, TT03p5, RP2040)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: no. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 10 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 11 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 12 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 17 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 18 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 19 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 20 | JA10 | 18 | walk + pin-id |
| uio[0] | 21 | JB1 | 7 | walk + pin-id |
| uio[1] | 22 | — | — | not tested |
| uio[2] | 23 | — | — | not tested |
| uio[3] | 24 | — | — | not tested |
| uio[4] | 25 | JB7 | 26 | walk + pin-id |
| uio[5] | 26 | — | — | not tested |
| uio[6] | 27 | — | — | not tested |
| uio[7] | 28 | — | — | not tested |
| uo_out[0] | 5 | — | — | not tested |
| uo_out[1] | 6 | — | — | not tested |
| uo_out[2] | 7 | — | — | not tested |
| uo_out[3] | 8 | — | — | not tested |
| uo_out[4] | 13 | — | — | not tested |
| uo_out[5] | 14 | — | — | not tested |
| uo_out[6] | 15 | — | — | not tested |
| uo_out[7] | 16 | — | — | not tested |

Notes:

- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- uio[1] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[2] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[3] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[5] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[6] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[7] is held (chip, a shared line, or a Pi pull-up): not driven

### pi-sw2-p4 (tt04, TT04, RP2040)

Cabling profile `fpga`: ui_in ← HAT JC, uio ← JB, uo_out ← JA. Loopback through the chip: no. Result: **FAIL**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | — | — | not tested |
| ui_in[1] | 10 | JC10 | 6 | walk + pin-id |
| ui_in[2] | 11 | JC9 | 5 | walk + pin-id |
| ui_in[3] | 12 | JC8 | 12 | walk + pin-id |
| ui_in[4] | 17 | — | — | not tested |
| ui_in[5] | 18 | JC4 | 17 | walk + pin-id |
| ui_in[6] | 19 | JC3 | 15 | walk + pin-id |
| ui_in[7] | 20 | JC2 | 14 | walk + pin-id |
| uio[0] | 21 | — | — | not tested |
| uio[1] | 22 | — | — | not tested |
| uio[2] | 23 | — | — | not tested |
| uio[3] | 24 | JB8 | 13 | walk + pin-id |
| uio[4] | 25 | — | — | not tested |
| uio[5] | 26 | — | — | not tested |
| uio[6] | 27 | — | — | not tested |
| uio[7] | 28 | — | — | not tested |
| uo_out[0] | 5 | — | — | not tested |
| uo_out[1] | 6 | — | — | not tested |
| uo_out[2] | 7 | — | — | not tested |
| uo_out[3] | 8 | — | — | not tested |
| uo_out[4] | 13 | — | — | not tested |
| uo_out[5] | 14 | — | — | not tested |
| uo_out[6] | 15 | — | — | not tested |
| uo_out[7] | 16 | — | — | not tested |

Notes:

- ui_in[0] is held hard by something else (shorted to a rail? console UART?): not driven
- ui_in[4] is held hard by something else (shorted to a rail? console UART?): not driven
- ui_in[0] is held externally, so the factory-test loopback cannot be used
- no known cabling profile fits well (best: fpga, score 0)
- uio[0] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[1] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[2] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[4] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[5] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[6] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[7] is held (chip, a shared line, or a Pi pull-up): not driven
- uio[3] also seen on GPIO21 (JA8): chip-driven line, ignored

### pi-sw2-p5 (tt05, TT05, RP2040)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: yes. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 10 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 11 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 12 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 17 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 18 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 19 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 20 | JA10 | 18 | walk + pin-id |
| uio[0] | 21 | JB1 | 7 | walk + pin-id |
| uio[1] | 22 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 23 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 24 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 25 | JB7 | 26 | walk + pin-id |
| uio[5] | 26 | JB8 | 13 | walk + pin-id |
| uio[6] | 27 | JB9 | 3 | walk + pin-id |
| uio[7] | 28 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 5 | JC1 | 16 | loopback via uio[0] |
| uo_out[1] | 6 | JC2 | 14 | loopback via uio[1] |
| uo_out[2] | 7 | JC3 | 15 | loopback via uio[2] |
| uo_out[3] | 8 | JC4 | 17 | loopback via uio[3] |
| uo_out[4] | 13 | JC7 | 4 | loopback via uio[4] |
| uo_out[5] | 14 | JC8 | 12 | loopback via uio[5] |
| uo_out[6] | 15 | JC9 | 5 | loopback via uio[6] |
| uo_out[7] | 16 | JC10 | 6 | loopback via uio[7] |

### pi-sw2-p6 (tt06, TT06, RP2040)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: yes. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 10 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 11 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 12 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 17 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 18 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 19 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 20 | JA10 | 18 | walk + pin-id |
| uio[0] | 21 | JB1 | 7 | walk + pin-id |
| uio[1] | 22 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 23 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 24 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 25 | JB7 | 26 | walk + pin-id |
| uio[5] | 26 | JB8 | 13 | walk + pin-id |
| uio[6] | 27 | JB9 | 3 | walk + pin-id |
| uio[7] | 28 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 5 | JC1 | 16 | loopback via uio[0] |
| uo_out[1] | 6 | JC2 | 14 | loopback via uio[1] |
| uo_out[2] | 7 | JC3 | 15 | loopback via uio[2] |
| uo_out[3] | 8 | JC4 | 17 | loopback via uio[3] |
| uo_out[4] | 13 | JC7 | 4 | loopback via uio[4] |
| uo_out[5] | 14 | JC8 | 12 | loopback via uio[5] |
| uo_out[6] | 15 | JC9 | 5 | loopback via uio[6] |
| uo_out[7] | 16 | JC10 | 6 | loopback via uio[7] |

### pi-sw2-p7 (tt07, TT07, RP2040)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: yes. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 10 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 11 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 12 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 17 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 18 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 19 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 20 | JA10 | 18 | walk + pin-id |
| uio[0] | 21 | JB1 | 7 | walk + pin-id |
| uio[1] | 22 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 23 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 24 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 25 | JB7 | 26 | walk + pin-id |
| uio[5] | 26 | JB8 | 13 | walk + pin-id |
| uio[6] | 27 | JB9 | 3 | walk + pin-id |
| uio[7] | 28 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 5 | JC1 | 16 | loopback via uio[0] |
| uo_out[1] | 6 | JC2 | 14 | loopback via uio[1] |
| uo_out[2] | 7 | JC3 | 15 | loopback via uio[2] |
| uo_out[3] | 8 | JC4 | 17 | loopback via uio[3] |
| uo_out[4] | 13 | JC7 | 4 | loopback via uio[4] |
| uo_out[5] | 14 | JC8 | 12 | loopback via uio[5] |
| uo_out[6] | 15 | JC9 | 5 | loopback via uio[6] |
| uo_out[7] | 16 | JC10 | 6 | loopback via uio[7] |

### pi-sw2-p8 (tt08, TT08, RP2040)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: yes. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 9 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 10 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 11 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 12 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 17 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 18 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 19 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 20 | JA10 | 18 | walk + pin-id |
| uio[0] | 21 | JB1 | 7 | walk + pin-id |
| uio[1] | 22 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 23 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 24 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 25 | JB7 | 26 | walk + pin-id |
| uio[5] | 26 | JB8 | 13 | walk + pin-id |
| uio[6] | 27 | JB9 | 3 | walk + pin-id |
| uio[7] | 28 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 5 | JC1 | 16 | loopback via uio[0] |
| uo_out[1] | 6 | JC2 | 14 | loopback via uio[1] |
| uo_out[2] | 7 | JC3 | 15 | loopback via uio[2] |
| uo_out[3] | 8 | JC4 | 17 | loopback via uio[3] |
| uo_out[4] | 13 | JC7 | 4 | loopback via uio[4] |
| uo_out[5] | 14 | JC8 | 12 | loopback via uio[5] |
| uo_out[6] | 15 | JC9 | 5 | loopback via uio[6] |
| uo_out[7] | 16 | JC10 | 6 | loopback via uio[7] |

Notes:

- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[2] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway

### pi-sw2-p33 (fpga-1, TT FPGA, RP2350)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: no. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 17 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 18 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 19 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 20 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 21 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 22 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 23 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 24 | JA10 | 18 | walk + pin-id |
| uio[0] | 25 | JB1 | 7 | walk + pin-id |
| uio[1] | 26 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 27 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 28 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 29 | JB7 | 26 | walk + pin-id |
| uio[5] | 30 | JB8 | 13 | walk + pin-id |
| uio[6] | 31 | JB9 | 3 | walk + pin-id |
| uio[7] | 32 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 33 | — | — | not tested |
| uo_out[1] | 34 | — | — | not tested |
| uo_out[2] | 35 | — | — | not tested |
| uo_out[3] | 36 | — | — | not tested |
| uo_out[4] | 37 | — | — | not tested |
| uo_out[5] | 38 | — | — | not tested |
| uo_out[6] | 39 | — | — | not tested |
| uo_out[7] | 40 | — | — | not tested |

Notes:

- iCE40 held in reset for the test (CRESET_B low); it reloads from flash afterwards
- ui_in[0] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[2] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[3] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[4] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[5] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[6] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[7] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway

### pi-sw2-p34 (fpga-2, TT FPGA, RP2350)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: no. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 17 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 18 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 19 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 20 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 21 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 22 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 23 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 24 | JA10 | 18 | walk + pin-id |
| uio[0] | 25 | JB1 | 7 | walk + pin-id |
| uio[1] | 26 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 27 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 28 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 29 | JB7 | 26 | walk + pin-id |
| uio[5] | 30 | JB8 | 13 | walk + pin-id |
| uio[6] | 31 | JB9 | 3 | walk + pin-id |
| uio[7] | 32 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 33 | — | — | not tested |
| uo_out[1] | 34 | — | — | not tested |
| uo_out[2] | 35 | — | — | not tested |
| uo_out[3] | 36 | — | — | not tested |
| uo_out[4] | 37 | — | — | not tested |
| uo_out[5] | 38 | — | — | not tested |
| uo_out[6] | 39 | — | — | not tested |
| uo_out[7] | 40 | — | — | not tested |

Notes:

- iCE40 held in reset for the test (CRESET_B low); it reloads from flash afterwards
- ui_in[0] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[2] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[3] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[4] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[5] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[6] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[7] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway

### pi-sw2-p35 (fpga-3, TT FPGA, RP2350)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: no. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 17 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 18 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 19 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 20 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 21 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 22 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 23 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 24 | JA10 | 18 | walk + pin-id |
| uio[0] | 25 | JB1 | 7 | walk + pin-id |
| uio[1] | 26 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 27 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 28 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 29 | JB7 | 26 | walk + pin-id |
| uio[5] | 30 | JB8 | 13 | walk + pin-id |
| uio[6] | 31 | JB9 | 3 | walk + pin-id |
| uio[7] | 32 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 33 | — | — | not tested |
| uo_out[1] | 34 | — | — | not tested |
| uo_out[2] | 35 | — | — | not tested |
| uo_out[3] | 36 | — | — | not tested |
| uo_out[4] | 37 | — | — | not tested |
| uo_out[5] | 38 | — | — | not tested |
| uo_out[6] | 39 | — | — | not tested |
| uo_out[7] | 40 | — | — | not tested |

Notes:

- iCE40 held in reset for the test (CRESET_B low); it reloads from flash afterwards
- ui_in[0] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[2] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[3] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[4] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[5] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[6] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[7] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway

### pi-sw2-p36 (fpga-4, TT FPGA, RP2350)

Cabling profile `asic`: ui_in ← HAT JA, uio ← JB, uo_out ← JC. Loopback through the chip: no. Result: **PASS**.

| Signal | RP2 GPIO | PMOD HAT pin | RPi GPIO | How |
| ------ | -------- | ------------ | -------- | --- |
| ui_in[0] | 17 | JA1 | 8 | walk + pin-id |
| ui_in[1] | 18 | JA2/JB2 | 10 | walk + pin-id |
| ui_in[2] | 19 | JA3/JB3 | 9 | walk + pin-id |
| ui_in[3] | 20 | JA4/JB4 | 11 | walk + pin-id |
| ui_in[4] | 21 | JA7 | 19 | walk + pin-id |
| ui_in[5] | 22 | JA8 | 21 | walk + pin-id |
| ui_in[6] | 23 | JA9 | 20 | walk + pin-id |
| ui_in[7] | 24 | JA10 | 18 | walk + pin-id |
| uio[0] | 25 | JB1 | 7 | walk + pin-id |
| uio[1] | 26 | JA2/JB2 | 10 | walk + pin-id |
| uio[2] | 27 | JA3/JB3 | 9 | walk + pin-id |
| uio[3] | 28 | JA4/JB4 | 11 | walk + pin-id |
| uio[4] | 29 | JB7 | 26 | walk + pin-id |
| uio[5] | 30 | JB8 | 13 | walk + pin-id |
| uio[6] | 31 | JB9 | 3 | walk + pin-id |
| uio[7] | 32 | JB10 | 2 | walk + pin-id |
| uo_out[0] | 33 | — | — | not tested |
| uo_out[1] | 34 | — | — | not tested |
| uo_out[2] | 35 | — | — | not tested |
| uo_out[3] | 36 | — | — | not tested |
| uo_out[4] | 37 | — | — | not tested |
| uo_out[5] | 38 | — | — | not tested |
| uo_out[6] | 39 | — | — | not tested |
| uo_out[7] | 40 | — | — | not tested |

Notes:

- iCE40 held in reset for the test (CRESET_B low); it reloads from flash afterwards
- ui_in[0] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[1] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[2] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[3] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[4] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[5] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[6] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway
- ui_in[7] is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway

