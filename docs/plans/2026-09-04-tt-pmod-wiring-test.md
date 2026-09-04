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
`.worktrees/tt-pmod-wiring`.

## Hardware facts the design rests on

| Fact | Source |
| --- | --- |
| HAT port to Pi GPIO: JA = 8,10,9,11,19,21,20,18; JB = 7,10,9,11,26,13,3,2; JC = 16,14,15,17,4,12,5,6 (PMOD pins 1-4,7-10). JA2-4 and JB2-4 are the **same** Pi lines (GPIO10/9/11, SPI0). | `docs/hardware/rpi-hat-pmod.md`, `designs/pmod-pin-id/host/identify_pmod_pins.py` |
| Demo-board PMOD pin k carries bit k-1 of its group, straight through. | `docs/hardware/pmod-tt.md` |
| RP2040 data GPIOs are identical on every RP2040 demo board (TT04-TT08 maps, SDK 2.0.4 and 1.2.2): `ui_in` = 9,10,11,12,17,18,19,20; `uio` = 21..28; `uo_out` = 5,6,7,8,13,14,15,16. Only control pins differ between TT04/05 (muxed) and TT06+. | `tt-micropython-firmware` `src/ttboard/pins/gpio_map.py` at v2.0.4 and v1.2.2 |
| RP2350 (demo board v3): `ui_in` = 17..24, `uio` = 25..32, `uo_out` = 33..40. | `docs/hardware/pmod-tt.md` |
| The SDK's `pin_indices()` is unreliable on these boards; existing scripts hard-code `machine.Pin` numbers. | `designs/_host/tt_pmod_wrapper.py` |
| The ASIC always drives `uo_out`. Every shuttle's `tt_um_factory_test` does `uo_out = uio_in`, `uio_oe = 0` while `ui_in[0] = 0` (TT07/TT08 additionally require `rst_n` high for that; with `rst_n` low they give `uo_out = ui_in`). After a reset with no clock the counter stays 0. | `tt04/05/06/07/08-factory-test` `src/tt_um_factory_test.v` |
| Every TT host runs the `fpgas-tt` daemon, which owns `/dev/ttboard`; it must be stopped for the test and restarted afterwards. | `fpgas.online-tt/debian/fpgas-tt.service`, docs |
| Fleet Pis boot with `console=serial0,115200`; GPIO14/15 (HAT JC2/JC3) are that console. Garbage on the console RX has triggered SysRq reboots before. | `fpgas.online-infra` cmdline template, `docs/hardware/acorn-pinmap.md` |
| SPI0 kernel modules claim GPIO7-11 (JA1/JB1 and the shared 2-4); they must be unloaded. | pin-id and loopback scripts |
| `python3-libgpiod` is not provisioned by Ansible; scripts support gpiod v1.6 and v2.x. | infra roles, existing scripts |

## Method

Three actors: the **Pi** (observer, reads all 21 unique HAT GPIOs), the
**RP2** (stimulus, drives one TT signal at a time), and the **ASIC** (optional
loopback for `uo_out`). The rule that keeps it contention-free: **only one
party ever drives a net.**

1. **Prepare the Pi.** Stop `fpgas-tt` (remember whether it was active),
   `sysctl kernel.sysrq=0`, stop `serial-getty@serial0/ttyAMA0`, `rmmod spidev
   spi_bcm2835`, request every HAT GPIO as a gpiod **input** (this also
   switches GPIO14/15 away from the UART function so the Pi stops driving
   TXD). All undone in `finally`.
2. **Prepare the RP2** over the raw REPL (termios, no dependencies, same
   mechanics as `tt_test_wrapper.py`): find `tt` (the SDK's `DemoBoard`, from
   the REPL globals, `DemoBoard.get()` or `DemoBoard()`), record `tt.mode`,
   stop auto-clocking, optionally `enable()` the factory-test project, reset
   it (`rst_n` low then high, no clock, so the counter is 0), then set the
   eight `ui_in` GPIOs to output-low and every other TT data GPIO to input.
3. **Walk `ui_in`.** For k in 0..7: RP2 drives `ui_in[k]` high, Pi samples;
   RP2 drives it low, Pi samples. A Pi GPIO that reads 1 in the high step and
   0 in the low step is *observed* for `ui_in[k]`. The Pi holds its inputs
   with PULL_DOWN during walks so floating ribbon lines can't couple.
4. **Probe `uio` for safety.** Pi releases its lines (bias disabled). For each
   `uio[k]` the RP2 applies its internal pull-up, reads, then pull-down,
   reads. A net that follows the pull is undriven and may be driven; one that
   does not is *externally driven* (the ASIC, or the HAT short to an
   ASIC-driven `uo_out`) and is skipped. With the factory test active the
   five never-shorted bits (`uio[0]`, `uio[4:7]`) are expected to float; if
   any of them is driven, the project selection did not take and the run
   falls back to "no ASIC loopback" mode.
5. **Walk `uio`.** Same as step 3 over the drivable `uio` bits. With the
   factory test active, `uo_out[k] = uio_in[k]`, so each step is expected to
   show **two** Pi GPIOs: the JB pin (direct) and the JA pin (through the
   chip). For k = 1..3 those are the same Pi line, and the ASIC agrees with
   the RP2 on that line by construction, so driving them is safe.
6. **Restore.** RP2: all data GPIOs back to input, `tt.mode` re-applied so
   the SDK re-owns its pins. Pi: lines released, modules left unloaded (as
   the other tests do), getty untouched, `sysrq` restored, daemon restarted
   if it was running.

Every step is lock-stepped: the RP2 prints `TTW STEP <signal> <level>` and
blocks on `sys.stdin.readline()`; the Pi samples (three reads, must agree)
and sends `\n`. The whole walk runs twice and both passes must agree. A
protocol timeout or a REPL traceback fails the run.

`uo_out` is only ever driven by the ASIC. Without the factory-test loopback
(`--asic-project none`, or a board whose SDK can't select it) the `uo_out`
ribbon is reported **not tested**, never PASS.

## Verdict

`--expect standard` (default) encodes the fleet cabling: HAT JC → `ui_in`,
JB → `uio`, JA → `uo_out`, pin k → bit k-1. For each signal the expected Pi
GPIO set is compared with the observed set:

| Observed vs expected | Row result |
| --- | --- |
| equal | OK |
| expected GPIO missing | **open** (or ribbon unplugged) |
| extra GPIO present | **short / cross-wire** |
| observed on a different GPIO | **miswired** |
| skipped (externally driven) | not tested |

PASS requires every tested row OK and nothing unexpected anywhere; every
`ui_in` row and every drivable `uio` row must have been tested. `--discover`
prints the measured table without a verdict, for recording a host's cabling.
Output ends with `RESULT: PASS`/`RESULT: FAIL` and a Markdown table in the
`tt-fpga-pin-mapping.md` format so it can be pasted into the docs.

## Components

| File | Role |
| --- | --- |
| `designs/tt-pmod-wiring/host/check_tt_pmod_wiring.py` | Pi-side script: gpiod reader (v1/v2), raw-REPL driver, embedded MicroPython probe, discovery + verdict logic, CLI. Guarded `import gpiod` so the logic imports on a dev machine. |
| `designs/tt-pmod-wiring/host/test_tt_pmod_wiring.py` | pytest: the verdict/classification logic, protocol parser, expectation tables, and a **simulated end-to-end run** (a fake RP2 speaking the protocol over a pty against a wiring model, and a fake GPIO backend reading that model) for correct, swapped, open and shorted wirings. |
| `designs/tt-pmod-wiring/README.md`, `Makefile`, `docs/tests/tt-pmod-wiring.md` | Usage and specification, matching the other designs. |
| `verify_hardware.py` | New board type `tt-asic` (six Welland hosts), design `tt-pmod-wiring` with no bitstream and no programming step. |
| `pyproject.toml` | pytest config that skips the Pi-side `test_<design>.py` host scripts. |
| `.github/workflows/lint.yml` | Add a pytest job. |

## Out of scope / known limits

- The fleet gateway entries in `verify_hardware.py` (`GATEWAYS["welland"]`)
  are already stale (Task 26 finding); the new hosts use the current
  `10.21.2.N` addressing but will need the gateway fixed to run from here.
- No hardware run was possible from this session (fleet SSH is blocked by a
  hook), so the first real run is the next step.
- TT03p5 runs SDK 1.2.2 whose project API differs; it is configured with
  `--asic-project none` (ui_in and the unshorted uio bits still verified).
