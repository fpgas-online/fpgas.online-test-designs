# fpgas-verify: what it must do

These are the goals for `fpgas-verify`, as set by Tim Ansell on 2026-10-01. Where the code, an older plan
(such as [plans/2026-09-26-fpgas-online-verify-design.md](plans/2026-09-26-fpgas-online-verify-design.md)) or
[fpgas-verify](verify.md) disagrees with this page, this page is what the tool should do; change the tool, or ask
before changing this page.

## Words used on this page

| Word | Means |
|---|---|
| board | one FPGA board (Arty A7, NeTV2, Acorn/LiteFury, Fomu, TT FPGA demo board, ...) |
| setup | a kind of board and how it is wired to its Pi. Normally one per kind of board; the Acorn/LiteFury has two (see [below](#every-board-of-a-setup-is-wired-the-same)) |
| full test design | the one fpgas.online bitstream for a board: every function the board has (soft CPU, UART, DDR, SPI flash, Ethernet, PCIe, Wishbone bridges, device DNA, temperature sensor, ...) in one design. On a board that boots from its own flash, it is written there and the board boots it |
| single-function test design | a bitstream that tests one function (the UART, the DDR, the Pmod pins, ...) on its own |
| golden bitstreams | the set of bitstreams currently approved for every fpgas.online board. The tool checks boards against them |
| site | the fpgas.online website of one location, such as `welland.fpgas.online` |

## 1. Main job: prove a board is set up correctly

The tool answers one question per Pi: **is this Pi and its FPGA board ready for users?** The answer is pass
or fail. It passes only when all of these hold:

| # | Check | What that means |
|---|---|---|
| 1 | Every connection is wired correctly and works | Every link between the Pi and the board carries what it should: the Pi's GPIO header (UART, JTAG, Pmod, other GPIO), USB, Ethernet, PCIe, and any other link. Each function over each link is used, not just detected |
| 2 | Every part on the board works properly | Each part works. Sensitive parts with an expected throughput are measured against it: DDR memory (calibration, error-free memtest, bandwidth), PCIe (link width and speed, transfer rate), Ethernet (link, packets, throughput) |
| 3 | The board runs the right bitstream | The flash holds the current golden full test design, and the board booted it (on the Fomu and TT FPGA: the tool loaded it) |
| 4 | Everything in the full test design works | Every feature of the running design does its job: the Wishbone bridges (over UART, JTAG, PCIe, Ethernet), device DNA and temperature readout, the soft CPU and its BIOS, and the rest |
| 5 | Everything about the board is reported | Everything the tool can read, including: board type and variant, serial numbers, FPGA IDCODE and device DNA, flash part and unique ID, MAC addresses, bitstream and package versions, and every measurement from 1-4 |

### Decisions for the main job

* **At boot, test the board as it booted from flash.** The check does not load any other design (except on the
  Fomu and TT FPGA, below). The single-function test designs are used only when a person is debugging (job 2.1).
* **So the full test design must contain every function the single-function designs test.** A function that is
  only in a single-function design is not checked at boot, so it does not count as checked.
* **Fomu and TT FPGA: the tool loads the full test design itself, then tests it.** Neither boots the test design
  on its own: the Fomu's iCE40 boots foboot, a USB bootloader, from its flash, and on the TT demo board the
  RP2350 loads the iCE40.
* **A flash without the golden full test design is reported, not fixed.** The check fails; a person writes the
  flash (job 2.2). Letting the site trigger the fix may come later.
* **There is one result: pass or fail.** Any problem fails the check, whether it is in the board, the wiring or
  the tool itself. The report lists every problem found, so the check keeps going after the first failure
  wherever it can: a board can have more than one fault.
* **A Pi with no board fails.** Every Pi runs the check and reports that it started; a Pi with no FPGA board
  found (an Orange Pi, a board powered off) reports that and fails.
* **GPIO pins are checked in both directions.** Today
  [pmod-pin-id](../designs/pmod-pin-id/) checks every pin FPGA to Pi: each FPGA pin sends its own name, and the
  Pi reads it. [pmod-loopback](../designs/pmod-loopback/) checks pins in pairs: the Pi drives one pin of each
  pair and reads the inverted value back on the other. So each pin is checked in one direction only. The full
  test design must check every pin both ways.
* **On the fleet, the check runs at every boot, and only then.** To check a Pi again, reboot it.
* **Users are assumed not to write the flash.** Most never touch it. If one does, the check sees the flash no
  longer holds the golden design and fails the board. Letting users have part of the flash, locking the
  golden region, and restoring a flash a user changed are
  [#68](https://github.com/fpgas-online/fpgas.online-test-designs/issues/68).
* **Each setup's expected wiring and expected figures** (DDR bandwidth, PCIe link width and speed, Ethernet
  throughput, ...) **are data files in this repository.**

## 2. Second job: help a person find and fix problems

| # | Feature | What it is for |
|---|---|---|
| 1 | Load and run each single-function test design on its own | When a function fails in the full test design, this shows whether that function is broken, or whether it only breaks when combined with the other functions in one bitstream |
| 2 | Write the golden full test design to the board's flash | To bring a board to the golden version |
| 3 | Report what changed since the last run, on a machine that keeps its state | A board, flash content, or wiring that differs from what the same machine saw before |
| 4 | Report what changed compared with the site's records | Match the board to the site's record by its FPGA and flash IDs first; if those do not match any record, by the switch port the Pi is on. Then report what differs (a board moved, swapped, rewired, reflashed) |
| 5 | Make [rpi-hwid](https://github.com/mithro/rpi-hwid) labels | Labels for the Pi, the FPGA board, extra Ethernet adapters and other attached hardware, so every piece is labelled correctly |

### Decisions for the second job

* **A board that passes is good, wherever it is.** Pis and boards on the fleet move between switch ports quite
  often. A Pi and its board are normally kept together, but may be split when hardware fails or new hardware
  is deployed. So a difference from the site's records never fails the check. It is reported, as a debugging
  aid.
* **A stateful host is different.** On a machine that keeps its state, what is attached and how it is wired is
  not expected to change, so a change fails the check. When a person runs the check by hand after changing
  something, the report shows the change, so they can confirm it is the one they meant.

## 3. Third job: tell the site what it is doing, as it goes

The tool reports the board's configuration and state to the site, sending an event at each step, not only the
final result:

| Event | Carries |
|---|---|
| Verification started | which Pi |
| Board found, or no board found | the kind of board, or that none was found |
| Board identified | the first identifying details: serial numbers, IDCODE, flash ID, ... |
| Test started / progress / finished | per test; finished carries its result |
| Final result | pass (ready for users) or fail (needs an admin or technician), with the full report: every problem found and every detail from check 5 |

The site uses the final result to decide whether users can be given the Pi.

## 4. Fourth job: check new bitstreams before they become golden

A new or changed test design must be shown to still work on real boards before it replaces the golden one:

1. Pick one board of each setup.
2. Run the check with the current golden bitstreams, then with the candidates, and compare the two results and
   their measurements.
3. Decide from that comparison whether to make the candidates golden.
4. Separately, update the whole fleet to the new golden set, recording each board's result before and after
   the update, and compare them.

From then on the tool checks every board against the new golden set. For the comparisons, results must be
comparable between two runs: the same tests and the same named measurements, in a stable machine-readable form.

## Expect most boards to fail at first

fpgas.online has never been checked this thoroughly, so most boards are expected to fail when the tool first
runs. Fixes might be, for example:

* changing the documentation to match the real hardware;
* fixing or changing the test designs;
* changing the wiring of the boards, or adding missing wiring.

## Every board of a setup is wired the same

All boards of one setup are wired to their Pis in exactly the same way. The tool holds one expected wiring per
setup and treats any difference on a board as a fault on that board.

The only known exceptions:

| Board | Exception |
|---|---|
| NeTV2 | Ethernet and USB may not be wired yet; their gateware is not ready either |
| NeTV2 | HDMI input and output may not be wired yet; their gateware is not ready either |
| NeTV2 not on a Pi 5 | no PCIe |
| Acorn/LiteFury | two setups, each with its own wiring: on a Raspberry Pi Compute Module, and on a Pi 5 with a Waveshare HAT. Within each setup every board is wired the same |

Any other difference found (in this repository, the docs or the hardware) is a fault to fix. Report it to Tim.
Assume it needs fixing; only ask whether it is a valid exception if there is real evidence that it is
deliberate or that the rule has not considered it.
