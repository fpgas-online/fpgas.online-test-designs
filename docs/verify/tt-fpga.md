# fpgas-verify: the Tiny Tapeout demo boards

You have a Tiny Tapeout demo board and want to know how the check tells which board it is, what it leaves
running, what its `sdk` test judges, and how its identity is read.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Which Tiny Tapeout board it is

The same demo board carries an FPGA breakout or a Tiny Tapeout chip, and its microcontroller looks the same on
USB either way (an FPGA board's RP2350 and a chip board's RP2040 both read `2e8a:0005`). So the check never
guesses: finding the board gives no variant (`fpga-board-found` carries `variant` `-`), and the variant is the
board's own word, read once the check holds its port ([below](#tt-fpga-identity)) and before any design is
chosen.

| The board says (rpi-hwid's `chip`) | Variant | What the check does |
|---|---|---|
| `fpga` | `tt-fpga` | runs [`sdk`](#the-sdk-test), then loads and runs `pin-id` and `uart` |
| `asic`, and a shuttle | `tt-asic` | runs [`sdk`](#the-sdk-test); nothing is loaded. The result is `fail`: its Pmod cabling cannot be tested yet (the report's `not_run`), and a board is not passed untested |
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
* A board with a Tiny Tapeout chip is left as it was: the design is an FPGA bitstream, and goes only to a
  board that said it carries the FPGA.

## The `sdk` test

The first test of every Tiny Tapeout board, and so far the only test of a board with a Tiny Tapeout chip
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
* **What it does not test** on a board with a Tiny Tapeout chip: the chip itself, and the Pmod cabling between
  the demo board and the Pi. The FPGA board's cabling is tested by `pin-id`; a chip board has no wiring test
  in the boot check yet.
* **So a board with a Tiny Tapeout chip does not pass yet, however healthy it is.** Its `sdk` test runs and is
  reported, the report lists the cabling in `not_run` (`wiring`), and the board's result is `fail` with the
  reason `wiring not run: the Pmod wiring test is not yet part of the boot check, …`. `fpga-verified` carries
  `board0_not_run`. The report then shows a board that is identified and whose firmware is right, and that is
  not yet fully tested. This ends when the wiring test
  ([PR #15](https://github.com/fpgas-online/fpgas.online-test-designs/pull/15)) is a test of the boot check.
* None of this has run on a board with a Tiny Tapeout chip: none was powered when it was written (5 October
  2026). The FPGA board's row is what the three boards at Welland read.

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
