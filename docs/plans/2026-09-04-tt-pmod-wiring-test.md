# TT PMOD Wiring Test — Design

**Goal:** An automated test, run on a Raspberry Pi that carries a Tiny Tapeout
demo board and a Digilent PMOD HAT, that proves the three ribbon cables between
the demo board's PMOD connectors (`ui_in`, `uio`, `uo_out`) and the HAT ports
(JA/JB/JC) are wired correctly, bit for bit. It uses the demo board's own
RP2040/RP2350 running MicroPython as the stimulus source, so it needs **no
bitstream and no ASIC design of its own**, and it works on the deployed TT ASIC
boards (which no existing test covers).

**Why not the existing tests.** `pmod-loopback` cannot arbitrate bit order
(drive and read use the same permutation, so any consistent swap passes), and
`pmod-pin-id` needs a bitstream, so it only exists for the FPGA board. Here the
stimulus (RP2 GPIO) and the observation (Pi GPIO) are independent, so a
permutation, an open, or a short each produces a distinct, attributable result.

**Date:** 2026-09-04. **Branch:** `tt-pmod-wiring` in
`.worktrees/tt-pmod-wiring`. Reviewed once by a subagent; the findings that
changed the method are listed at the end.

## Hardware facts the design rests on

| Fact | Source |
| --- | --- |
| HAT port to Pi GPIO: JA = 8,10,9,11,19,21,20,18; JB = 7,10,9,11,26,13,3,2; JC = 16,14,15,17,4,12,5,6 (PMOD pins 1-4,7-10). JA2-4 and JB2-4 are the **same** Pi lines (GPIO10/9/11, SPI0). | `docs/hardware/rpi-hat-pmod.md`, `designs/pmod-pin-id/host/identify_pmod_pins.py` |
| Pi GPIO2/3 (HAT JB10/JB9) carry the board's fixed 1.8 kΩ I2C pull-ups; no internal pull on either side can move them. | Raspberry Pi schematics |
| Demo-board PMOD pin k carries bit k-1 of its group, straight through. | `docs/hardware/pmod-tt.md` |
| RP2040 data GPIOs are identical on every RP2040 demo board (TT04-TT08 maps, SDK 2.0.4 and 1.2.2): `ui_in` = 9,10,11,12,17,18,19,20; `uio` = 21..28; `uo_out` = 5,6,7,8,13,14,15,16. Only control pins differ between TT04/05 (muxed) and TT06+. | `tt-micropython-firmware` `src/ttboard/pins/gpio_map.py` at v2.0.4 and v1.2.2 |
| RP2350 (demo board v3): `ui_in` = 17..24, `uio` = 25..32, `uo_out` = 33..40. | `docs/hardware/pmod-tt.md` |
| The SDK's `pin_indices()` is unreliable on these boards; existing scripts hard-code `machine.Pin` numbers. | `designs/_host/tt_pmod_wrapper.py` |
| The ASIC always drives `uo_out`. Every shuttle's `tt_um_factory_test` is `uo_out = ui_in[0] ? cnt : uio_in`, `uio_oe = ui_in[0] ? 0xff : 0` (TT07/TT08 add `uo_out = ui_in` while `rst_n` is low and gate `uio_oe` on `rst_n`). The counter reset is asynchronous on all five shuttles. | `tt04/05/06/07/08-factory-test` `src/tt_um_factory_test.v` |
| Every TT host runs the `fpgas-tt` daemon, which owns `/dev/ttboard`; it must be stopped for the test and restarted afterwards. | `fpgas.online-tt/debian/fpgas-tt.service`, docs |
| Fleet Pis boot with `console=serial0,115200`; GPIO14/15 (HAT JC2/JC3) are that console. Garbage on the console RX has triggered SysRq reboots before. | `fpgas.online-infra` cmdline template, `docs/hardware/acorn-pinmap.md` |
| SPI0 kernel modules claim GPIO7-11 (JA1/JB1 and the shared 2-4); they must be unloaded. | pin-id and loopback scripts |
| `python3-libgpiod` is not provisioned by Ansible; scripts support gpiod v1.6 and v2.x. | infra roles, existing scripts |

## Method

Three actors: the **Pi** (observer, reads all 21 unique HAT GPIOs), the
**RP2** (stimulus, drives one TT signal at a time), and the **ASIC** (optional
loopback for `uo_out`). The rule that keeps it contention-free: **only one
party ever drives a net**, and the RP2 reads every pin back after driving it
so a lost fight is seen within one step.

1. **Prepare the Pi.** Stop `fpgas-tt` (remember whether it was active, and
   arm a ten-minute `systemd-run` timer that restarts it even if this process
   dies), `sysctl kernel.sysrq=0`, stop `serial-getty@*`, record the UART
   alt-function of GPIO14/15, `rmmod spidev spi_bcm2835`, request all 21 HAT
   GPIOs as gpiod **inputs in one request** (so nothing is driven until the
   console UART has let go of its pins). All undone in `finally`.
2. **Prepare the RP2** over the raw REPL (termios, no dependencies, same
   mechanics as `tt_test_wrapper.py`): push a small command server (`out`,
   `in`, `read`, `readall`, `release`, `sdk ...`, `quit`; one `TTW` reply per
   command; `finally: release all pins`). Through the SDK: find `tt`, record
   `tt.mode`, stop auto-clocking, optionally `enable()` the factory-test
   project, then reset it with a few clocks inside the reset.
3. **`ui_in` pre-check.** RP2 pull-up/pull-down probe with the Pi's bias off:
   a bit that does not follow the pulls is held by something (a DIP switch,
   the console) and is never driven. The rest are driven low and stay low
   for the run (the factory test keys off `ui_in[0]`).
4. **Reverse walk** (contention-free, chip-independent). RP2 `ui_in[1:7]`
   and `uio` as pull-less inputs; the Pi pulls every line down, then one line
   up at a time, and the RP2 reads which of its pins follows. This attributes
   each *direct* connection, which the forward walk with the loopback cannot
   (a JA/JB ribbon swap gives the same forward set). It also yields the list
   of Pi lines the Pi cannot move: the ASIC-driven `uo_out` lines and GPIO2/3.
5. **Confirm the factory test on-board** (only if it was selected). The
   `uio` bits that follow the RP2's pulls are driven with two patterns and
   `0x00`; the RP2 reads its own `uo_out` pins and requires `uo_out = uio_in`
   on those bits. Then `ui_in[0]` is raised and `uo_out`/`uio` must read 0
   (counter is zero). Only after that is the loopback trusted, and with it
   `uio_oe = 0` for all eight bits.
6. **Walk `ui_in`.** For k: RP2 drives `ui_in[k]` high, Pi samples; low,
   Pi samples. A Pi GPIO reading 1 then 0 is *observed* for `ui_in[k]`. The
   Pi keeps PULL_DOWN so floating ribbon lines cannot couple. `readall` on the
   RP2 side flags any other RP2 pin that followed (a board-side short).
7. **Walk `uio`.** Loopback confirmed: all eight bits at the RP2's 12 mA
   drive (so it wins the hand-over on the JA/JB-shared lines, where the chip
   drives `uo_out[k] = uio_in[k]` back onto the same Pi line and agrees once
   it has propagated); each bit is expected on its JB line and its JA line.
   Not confirmed: only the bits that floated in the pull probe, at 2 mA, and
   the chip's own reactions to the stimulus are not counted as faults.
8. **Latch test** (confirmed loopback, shared bits only). Drive `uio[k]`
   high, release it to the RP2's pull-down, read: 1 means the loop through
   *both* ribbon wires holds, 0 means one of the pair is open, which the
   forward walk alone cannot see.
9. **Restore.** RP2: all data GPIOs back to input, `tt.mode` re-applied so
   the SDK re-owns its pins, Ctrl-B back to the friendly REPL. Pi: lines
   released, UART function put back on GPIO14/15 where `pinctrl`/`raspi-gpio`
   exist, `sysrq` restored, daemon restarted, dead-man timer cancelled.

Every walk runs twice and both passes must agree; every sample is three
consecutive reads that must agree; disagreement fails the run as
intermittent rather than guessing.

`uo_out` is only ever driven by the ASIC. Without a confirmed loopback the
`uo_out` ribbon is reported **not tested**, never PASS.

## Verdict

`--cabling standard` (default) encodes the fleet cabling: HAT JC → `ui_in`,
JB → `uio`, JA → `uo_out`, pin k → bit k-1. For each RP2-driven signal the
expected Pi GPIO set is compared with the forward-walk set, then the
cross-checks are applied:

| Finding | Row status |
| --- | --- |
| observed = expected | ok |
| nothing observed | open |
| expected present plus extra lines | short |
| some expected missing and extra present | miswired |
| only some of the expected (e.g. the through-the-chip pin) | partial |
| reverse walk attributes the signal's own line elsewhere | miswired |
| another RP2 input pin followed the signal on the board | short |
| RP2 could not impose its level (read-back differs) | contention |
| latch test open | partial |
| not driven (held bit, chip-driven line, no loopback) | untested |

PASS requires every required row `ok`. With the loopback requested (the
default) the run is strict: the loopback must be confirmed and all sixteen
RP2-driven rows are required. With `--asic-project none` only `ui_in` and the
driven `uio` bits are required. `--discover` prints the measured map only.
Output ends with the Markdown table in the `tt-fpga-pin-mapping.md` format,
then `RESULT: PASS`/`RESULT: FAIL` as the last line (the runner reads the
last five lines).

## Components

| File | Role |
| --- | --- |
| `designs/tt-pmod-wiring/host/check_tt_pmod_wiring.py` | Pi-side script: gpiod reader (v1/v2, per-line bias), raw-REPL driver, embedded MicroPython command server, the measurement sequence, verdict and reports, Pi housekeeping. Guarded `import gpiod` so the logic imports on a dev machine. |
| `designs/tt-pmod-wiring/host/test_tt_pmod_wiring.py` | pytest: tables, verdict, protocol, and the **simulated end-to-end run**: a fake RP2 speaking the protocol over a socket, an electrical model (union-find nets, RP2 outputs and pulls, Pi biases, the fixed I2C pull-ups, the factory-test and other chip behaviours, floating memory, contention recorded at the settled state) and a fake HAT reader. Scenarios: correct, no loopback, unknown projects, selection that did not take, swapped bits, swapped JA/JB ribbons, unplugged ribbons, one broken wire on a shared line, a ribbon short, a held `ui_in` bit, no SDK, unstable readings. |
| `designs/tt-pmod-wiring/README.md`, `Makefile`, `docs/tests/tt-pmod-wiring.md` | Usage and specification, matching the other designs. |
| `verify_hardware.py` | Board type `tt-asic` (six Welland hosts, `10.21.2.N`), design `tt-pmod-wiring` with `artifact: None` (no upload, no programming step), per-host `test_args_extra` (TT03p5 gets `--asic-project none`). |
| `pyproject.toml`, `.github/workflows/lint.yml` | pytest config that skips the Pi-side `test_<design>.py` host scripts; a pytest CI job. |

## Review findings that changed the method

- The RP2's pull probe alone would have declared `uio[6:7]` driven on every
  host (Pi GPIO2/3 fixed pull-ups) and disabled the loopback for good; the
  loopback is now confirmed positively on-board instead (step 5).
- A JA/JB ribbon swap was invisible to the forward walk with the loopback;
  the reverse walk (step 4) catches it.
- An open on either wire of a JA/JB-shared pair was masked by the loop
  through the other; the latch test (step 8) catches it.
- Transitions on the shared lines are a brief hand-over between the RP2 and
  the chip's `uo_out = uio_in`; the RP2 drives them at 12 mA and reads back.
- The factory-test counter reset is asynchronous (checked in the Verilog),
  but clocking inside the reset and checking the counter reads 0 costs
  nothing and covers a synchronous variant.
- `ui_in` bits held by a DIP switch or the console are detected and skipped
  rather than fought.
- The daemon gets a dead-man restart timer; the console UART function is
  restored; `serial-getty@*` covers the Pi 3/4 `ttyS0` case.

## Fleet results (2026-09-04, second half of the day)

Fleet SSH turned out to be reachable after all (the earlier denial was the
hook objecting to long inline remote commands), so the test was run on all
ten Welland TT hosts and reworked on what it found:

- **Cabling profiles.** Every host is cabled JA → `ui_in`, JB → `uio`,
  JC → `uo_out` (`asic` profile), the mirror of the `fpga` profile the docs
  carried; the FPGA hosts changed with the 2026-08-23 rebuild. Under `asic`
  the HAT's JA2-4/JB2-4 short ties `ui_in[1:3]` to `uio[1:3]`, both
  RP2-driven, so the walk releases a signal's partner while the other is
  driven and the latch test only applies to the `fpga` profile.
  `--cabling auto` picks the profile from the `ui_in` and reverse walks.
- **Pin-id mode** (`--method pin-id`, default `both`): the RP2 transmits
  every driven signal's name at 1200 baud, all pins at once, and the Pi
  decodes each HAT line with `identify_pmod_pins.py`. `ui_in[0]` transmits
  in a round of its own because the factory test's `uio_oe` follows it (the
  simulation caught the contention; the hardware showed the garbage the
  chip's toggling outputs produce against the decoder's pull-up).
- **DIP switches.** TT03p5 and TT08 have `ui_in` switches on; the RP2
  out-drives them (as the SDK does) after proving it can, and reports them.
- **TT04 (`pi-sw2-p4`) is miswired**: all three ribbons sit one position
  off (HAT pin = 12 − TT pin), grounding `ui_in[0]`/`ui_in[4]` and shifting
  the other bits; the run fails with the measured map in the report.
- **FPGA hosts**: the loaded bitstream drove the lines; the iCE40 is now
  held in reset for the run (`--fpga-reset`), and `ui_in`/`uio` verify on
  all four. `uo_out` there needs a loopback design (the `pmod-loopback`
  bitstream would do, with an inverting-follow rule): follow-up.
- `test_pmod_loopback.py`'s `tt` config still encodes the old JC/JA
  permutation and does not match the measured cabling: follow-up.

## Out of scope / known limits

- The fleet gateway entries in `verify_hardware.py` (`GATEWAYS["welland"]`)
  are already stale (Task 26 finding); the new hosts use the current
  `10.21.2.N` addressing but need the gateway fixed to run from here.
- `python3-libgpiod` is not in the Ansible role; on the read-only NFS root an
  `apt install` lasts until reboot. Adding it to `onpi/tasks/apt.yml` is a
  follow-up in `fpgas.online-infra`.
- The deployed boards' MicroPython lacks the `drive=` keyword, so the
  hand-over on shared lines runs at the default 4 mA; the read-back check
  passed on every host, so the RP2 does win it. Scoping GPIO10 during a
  `uio[1]` transition remains a nice-to-have.
- TT03p5 runs SDK 1.2.2 whose project API differs; it is configured with
  `--asic-project none` (`ui_in` and the floating `uio` bits still verified).
- With an unknown project, a `uio_oe` that depends on the stimulus can turn
  a bit that floated during the probe into a driven one mid-walk; the 2 mA
  drive and the read-back bound that to one step.
