# fpgas-verify: the Tiny Tapeout demo boards

You have a Tiny Tapeout demo board and want to know how the check tells which board it is, what it leaves
running, what its `sdk` and `wiring` tests judge, and how its identity is read.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Which Tiny Tapeout board it is

The same demo board carries an FPGA breakout or a Tiny Tapeout chip, and its microcontroller looks the same on
USB either way (an FPGA board's RP2350 and a chip board's RP2040 both read `2e8a:0005`). So the check never
guesses: finding the board gives no variant (`fpga-board-found` carries `variant` `-`), and the variant is the
board's own word, read once the check holds its port ([below](#tt-fpga-identity)) and before any design is
chosen.

| The board says (rpi-hwid's `chip`) | Variant | What the check does |
|---|---|---|
| `fpga` | `tt-fpga` | runs [`sdk`](#the-sdk-test), then loads and runs [`dip-switches`](#the-dip-switches), `pin-id` and `uart` |
| `asic`, and a shuttle | `tt-asic` | runs [`sdk`](#the-sdk-test), then [`wiring`](#the-wiring-test) (its three Pmod ribbons); nothing is loaded, and the board's SDK is started again afterwards |
| nothing usable: rpi-hwid is not installed, could not read the board, or gave no shuttle for a chip | none | nothing is loaded and no test runs: the result is `error`, and the reason says what could not be read |
| (an RP2 in its USB boot loader, `2e8a:0003`) | none | `fail`: `a Raspberry Pi RP2 is on USB but is not running the Tiny Tapeout firmware` |

* An FPGA bitstream only ever goes to a board that said it is an FPGA board.
* The check has one port for a demo board (`/dev/ttyACM0`). With two such RP2 boards on one Pi it cannot tell
  which board that port is, so each is an `error` (`2 Raspberry Pi RP2 boards that can be Tiny Tapeout demo
  boards are on this Pi's USB, …`): none is asked what it is and nothing is loaded. No host has two.
* Other Raspberry Pi USB products (a debug probe, say) are not Tiny Tapeout boards and are not looked at.
* `--variant tt-fpga` does not override the board: asked for on a board that says otherwise, it is an `error`.
* `fpgas-tt-fpga-debug program` and `test` are for use by hand: they do not ask the board, so they need
  `--variant tt-fpga` said out loud, and load what they are told to.
* A board whose `main.py` is not the one the check knows is not asked at all (the check will not run a
  `main.py` it does not know), so it has no variant. The check knows the `main.py` of every SDK release from
  1.0.0 to 3.1.1 (`tt_main_py.py`); only 3.1.0's has been compared with a board.
* A TT04 chip cannot be read by its SDK (2.0.x reports its shuttle as `unknown`), so a TT04 board gives no
  shuttle and is the `error` of the third row, unless the board's own `config.ini` names the shuttle
  (`force_shuttle`). The check never writes that file.
* rpi-hwid looks at `2e8a:0005` only, so a board showing `2e8a:000f` is found and then cannot be asked.
* A board that says `asic` is still a `tt-asic` when it named no demo board or microcontroller (an FPGA board
  that named neither is an `error`); a chip board that named no microcontroller then fails the `sdk` test.
* `variant` in the report, in `fpga-board-identified` and in `fpga-verified` is the decided one; it is absent
  when the board did not say.

## The DIP switches

The demo board has eight DIP switches on the design's inputs, `ui_in`: switch 1 on `ui_in[0]` to switch 8 on
`ui_in[7]`. A switch that is on ties its line to 3.3 V through 1 kΩ (Tiny Tapeout's
[demo board schematic](https://github.com/TinyTapeout/tt-demo-pcb)). The check drives and reads `ui_in` from
the Pi and from the board's microcontroller, so it needs every switch off, as Tiny Tapeout's own guides say.
The `dip-switches` test checks it, before any other test loads a design
([#166](https://github.com/fpgas-online/fpgas.online-test-designs/issues/166)).

* **Set every DIP switch off.** A switch that is on fails the board, named:
  `dip-switches fail: switch 4 is on: set all DIP switches off`.
* The board's microcontroller reads the switches, over its REPL and in its memory only: nothing is written to
  the board. For each line it drives the pin low for a moment, then reads it as an input with its pull-down,
  so a switch that is on reads high and one that is off reads low.
* Nothing else may hold the lines while they are read. So the check first streams
  [`tt-display`](../../designs/tt-display/README.md) with `--gpio-release`: it drives only `uo_out`, and leaves
  `ui_in` and `uio` undriven with the FPGA's pull-up off. The Pi's eight GPIOs on HAT JA are made inputs with
  their pull-down for the read, and are then put back as they were (with `pinctrl`). JA pins 2 to 4 are also
  JB's, `uio[1]` to `uio[3]`: for switches 2 to 4 the board's microcontroller sets its `uio[1]` to `uio[3]`
  pins the same way as the `ui_in` pin it reads.
* The test is an `error`, not a `fail`, when it could not make the read:
  * the board did not answer (`the DIP switches could not be read from the board …`);
  * `pinctrl` could not set the Pi's GPIOs, or cannot read their pull (a Pi 3 and older), so they could not
    be put back;
  * the Pi's GPIOs could not be put back afterwards (the reason says so, after the switches' result).
  * the check was stopped during the read (the Pi's GPIOs are put back first).
* A load of `tt-display` that fails is a `fail` of this test (`loading it failed (exit N)`), as for any test.
  A `tt-display` file that is damaged or missing in the bitstreams package makes the test an `error`: the
  switches cannot be read without it.

## What the TT FPGA is left running

The check of an FPGA board ends by streaming one more design, [`tt-display`](../../designs/tt-display/README.md),
so that the board's seven-segment display moves and the board looks alive on its camera
([#139](https://github.com/fpgas-online/fpgas.online-test-designs/issues/139)): one segment runs round the
ring, the middle segment changes at each lap, the dot blinks once a second. It is not a test, and nothing
reads it.

* It is loaded last, after every test (also after a failed one, and after single tests named with `--test`),
  and nothing is done to the board after it. Like every load it is streamed: nothing is stored on the board.
* It runs from the FPGA's own oscillator and drives only `uo_out`, so it needs nothing from the board's
  microcontroller once it is loaded: no clock, no reset, no input.
* The report says so: `left_running` (`design`, `bitstream`) on the board, a `left running:` line in the
  summary, `board0_left_running` in `fpga-verified`.
* **A load of it that fails does not fail the board**: the board was tested before it, and the design is for
  the camera. It is said, though: `warnings` on the board in the report (`the display design, which the check
  leaves running, could not be loaded (…): the board is left as its last test left it`), a `WARNING:` line in
  the summary, and `board0_warnings` in `fpga-verified`.
* **How long it lasts**: until the board's own SDK next starts, which happens when a visitor's Commander
  connects or a design is run from the site. SDK 3.1.0 then loads its own default project
  (`tt_um_factory_test`), which on an FPGA board shows a still pattern. What the display shows after that is
  the SDK's and the site bridge's, not the check's.
* A board with a Tiny Tapeout chip is not given it: the design is an FPGA bitstream, and goes only to a board
  that said it carries the FPGA. Such a board is left with its SDK started again after
  [the wiring test](#the-wiring-test).

## The `sdk` test

The first test of every Tiny Tapeout board
([#132](https://github.com/fpgas-online/fpgas.online-test-designs/issues/132)). It loads nothing and asks the
board nothing more: it judges what the board said when it was asked what it is. The chip, the shuttle, the
microcontroller and the SDK release must be a combination the SDK's releases support, since an SDK that does
not know the board's chip cannot select a project on it:

| The board carries | Microcontroller | SDK release |
|---|---|---|
| the FPGA breakout | RP2350 | 3.1.x |
| a TT03p5 chip | RP2040 | 1.2.x |
| a TT04, TT05, TT06, TT07 or TT08 chip | RP2040 | 2.0.x |

* Anything else fails the test, with what the board said: `a tt06 chip needs SDK 2.0.x on an RP2040, and the
  board runs SDK 1.2.2 on an RP2040`. A shuttle with no row fails as `no SDK release is recorded as supporting
  a tt09 chip`: the table (`SDK_SUPPORTED` in `boards/tt_fpga.py`) gains a row when a release is known to
  support it.
* Together with the `main.py` read (the board's `main.py` is that release's own) and the SDK having started,
  a pass means: the board answers, says what it is, and what it says is a combination the SDK's releases
  support. It compares what the board said with a table; it measures nothing on the chip.
* An FPGA board on another release line (3.0.x, or a later 3.2.x) fails `sdk` until its row is added; its
  designs are still loaded and tested, and the board's result is `fail`.
* **What it does not test**: the chip itself, and the Pmod cabling between the demo board and the Pi. The
  cabling is the next test's: [`wiring`](#the-wiring-test) on a board with a Tiny Tapeout chip, `pin-id` on
  the FPGA board.
* It has passed on the one board with a Tiny Tapeout chip powered at Welland (a TT07 chip, an RP2040, SDK
  2.0.4: 6 October 2026), and on the three FPGA boards there.

## The wiring test

The `wiring` test of a board with a Tiny Tapeout chip (`tt-asic`) checks the three ribbon cables between the demo
board's Pmod connectors and the Pi's Pmod HAT, wire by wire. It loads nothing: the board's microcontroller and
the chip's own factory-test project make the signals
([#132](https://github.com/fpgas-online/fpgas.online-test-designs/issues/132), first written as
[PR #15](https://github.com/fpgas-online/fpgas.online-test-designs/pull/15)). The cabling it expects is the one the
FPGA board's `pin-id` expects too:

* the demo board's `ui_in` Pmod to HAT **JA**, its `uio` Pmod to HAT **JB**, its `uo_out` Pmod to HAT **JC**;
* pin for pin: Pmod pin 1 to HAT pin 1, and so on (pins 1 to 4 and 7 to 10 carry bits 0 to 7).

A wire that is wrong fails the board, named by its ribbon, its signal and its pins:

* `wiring fail: the ui_in ribbon (HAT JA): ui_in[2] (pin 3) did not reach JA3: it reached JA4/JB4`
* `wiring fail: the uo_out ribbon (HAT JC): none of its 8 signals reached the Pi (not plugged in, or on another port)`
* `wiring fail: the ribbons look cabled as ui_in on HAT JC, uio on HAT JB, uo_out on HAT JA, not as …`
* `wiring fail: the uo_out ribbon (HAT JC): uo_out[1] (pin 2) did not reach JC2 (driven by the chip from uio[1])`

A ribbon names up to four of its faults, and counts the rest (`; and 3 more`). What to do: seat the ribbon
named, or move it to its port, and run the check again.

How it tests:

* **Nothing is written to the board.** The board's RP2040 runs a small command server in its memory, sent over
  its raw REPL. Through the SDK it selects the chip's `tt_um_factory_test` project, which on every shuttle
  copies `uio` to `uo_out` while `ui_in[0]` is low, and resets it. The RP2040 then drives each `ui_in` and
  `uio` signal in turn while the Pi reads all 21 HAT lines, so a swapped, open or shorted wire each show as
  that. The `uio` walk reaches `uo_out` through the chip, which tests the `uo_out` ribbon. The RP2040 also
  sends each signal's name at 1200 baud, and the Pi decodes it on every line, as `pin-id` does on the FPGA board.
* HAT pins JA2 to JA4 and JB2 to JB4 are the same three Pi GPIOs (10, 9, 11), so `ui_in[1..3]` and `uio[1..3]`
  share them: while one of a pair is driven, the other is an input. A ribbon swap between JA and JB is still
  seen, by a second walk in which the Pi pulls each line up in turn and the RP2040 reads which of its pins
  follows.
* On the Pi, for the test only: the serial getty is stopped and SysRq is off (the console's GPIO14/15 are HAT
  JC2/JC3), and the SPI drivers are unloaded (they hold GPIO7 to 11). Every HAT GPIO's function, pull and
  output level is read with `pinctrl` first and set back afterwards. A Pi 3 cannot read back its pulls: there
  the 21 lines are left with the pull-down the test reads them with, and the test's output says so.
* **Afterwards the board's SDK is started again** (`tt_sdk_start.py`, as before rpi-hwid), so the chip is back
  on the project the board starts with. The SDK rewrites its own `boot.log` then, as at every power-on. An SDK
  that does not start again is a warning in the report, not the board's result.
* A DIP switch that is on does not change the result: the RP2040 drives `ui_in` as the SDK does, stronger than
  a switch's 1 kΩ, and the test's output notes the line.

The test is an `error`, not a `fail`, when it could not make its reading: the board did not answer its raw REPL,
gpiod or `pinctrl` is missing or could not read the HAT GPIOs, the test was stopped (the Pi is put back first),
or what it changed on the Pi was not put back (the reason says what). It is a `fail` when the readings were not
steady (a loose contact?), and when the chip's factory test could not be confirmed, since `uo_out` is then not
tested: a board on SDK 1.x (a TT03p5 board) cannot select it this way, so it fails there until the test learns
that SDK's interface.

It has run in this form on one board with a TT07 chip (see the pull request that brought it into the check);
[PR #15](https://github.com/fpgas-online/fpgas.online-test-designs/pull/15)'s form of it ran on every Tiny
Tapeout host at Welland on 4 September 2026.


## TT FPGA identity

The site makes [rpi-hwid](https://github.com/mithro/rpi-hwid)'s Tiny Tapeout label for a TT board from the
[Tiny Tapeout fields](../identity.md#tiny-tapeout-fields) in its identity. Only rpi-hwid reads them: it asks the
Tiny Tapeout SDK on the board's RP2350 over its REPL, which needs the board's port, `/dev/ttyACM0`. Outside the
check, `fpgas-tt.service` holds that port.

So the boot check reads them while it holds the port: with `fpgas-tt.service` stopped (when it was running),
and before the first test loads a design, it first checks that the board's `main.py` is still the SDK's own
(`tt_main_py.py`: a read of its SHA-256, compared with the one recorded for the SDK release the board runs;
visitors have the board's Python prompt and can change it; this step does not need rpi-hwid), then starts the board's SDK (`tt_sdk_start.py`: a soft reset from the
friendly REPL, which runs the board's `main.py`; rpi-hwid reads only what the SDK built at start-up) and then
runs `rpi-hwid tinytapeout --json --no-stop-service`. A board whose `main.py` is not the SDK's own, or whose SDK does not start, is an
`error` with that reason, and rpi-hwid is not run. It then
starts `fpgas-tt.service` again after the tests, as it always does, whatever rpi-hwid did.
`--no-stop-service` tells rpi-hwid to leave the service alone.

* The packages do not depend on rpi-hwid (it comes from its own apt repository). The check looks for the
  `rpi-hwid` command on `PATH` and runs it; it never imports it.
* rpi-hwid lists every MicroPython RP2 board on USB. The check uses the one whose `usb_serial` is the board's
  USB serial, and copies its fields into the identity under rpi-hwid's names.
* Without rpi-hwid, the fields are left out and `tinytapeout_note` says why. The board cannot then say which
  Tiny Tapeout board it is, so the check is an `error` and nothing is loaded: install `python3-rpi-hwid`.
* When rpi-hwid is installed but cannot say who the board is, `tinytapeout_error` says why, and the check is
  an `error` and nothing is loaded. That is the case when rpi-hwid fails, prints no JSON, does not list the board, finds no Tiny
  Tapeout SDK on it, or gives `null` for `mcu`, `chip`, `demoboard` or `sdk`, which every TT FPGA board has.
* A field rpi-hwid leaves out is left out of the identity too, so `--identify` says it is missing.
* The identity always has `usb_serial` (the same as `serial`): the site drops a TT board without one.
* A check that stops before its tests (no bitstreams installed, an unknown test) does not run rpi-hwid.

`fpgas-verify --identify` does not take the port. It takes these fields from the boot report, matching the
board there by `usb_serial`.
