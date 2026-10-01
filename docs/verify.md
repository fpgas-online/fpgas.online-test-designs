# fpgas-verify: checking an FPGA board from its Raspberry Pi

`fpgas-verify` checks that an FPGA board, and its wiring to the Raspberry Pi it hangs off, works. It finds the
board, loads the fpgas.online test designs into it one at a time, runs each design's host test, and says
`pass` or what is wrong. It is the `fpgas_online_verify` Python package in [`verify/`](../verify/), shipped as
Debian packages from <https://apt.fpgas.online>.

This page has two parts:

1. [Using verify as a standalone tool](#1-using-verify-as-a-standalone-tool): on any Pi (or PC) with a
   board, from the apt packages.
2. [How verify is used in fpgas.online](#2-how-verify-is-used-and-integrated-in-fpgasonline): at every boot of
   every netbooted Pi, and as the gate that decides which boards the site offers. It ends with the
   [current results](#current-results) on the Welland Pis.

Goals for the tool: [verify-goals.md](verify-goals.md). The design notes are in [plans/2026-09-26-fpgas-online-verify-design.md](plans/2026-09-26-fpgas-online-verify-design.md).
`verify_hardware.py` ([verify-hardware.md](verify-hardware.md)) is a different tool: a developer's script that
uploads freshly built bitstreams from a workstation over SSH. `fpgas-verify` runs on the Pi, from packages.

---

## 1. Using verify as a standalone tool

### Installing

**Add the repository** once per host. It serves `bookworm` (Debian 12) and `trixie` (Debian 13). The packages
are `Architecture: all`, so this works on Raspberry Pi OS and on an x86 machine alike (the NeTV2 and Acorn
need a Pi's GPIO header; the Arty, Fomu and TT FPGA board only need USB):

```bash
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
sudo apt update
```

This is the setup every fpgas.online apt repository uses
([convention](https://github.com/mithro/apt-repo-action/blob/main/docs/conventions.md)).

For openFPGALoader, add the [fpgas.online-fpga-tools repository](https://github.com/fpgas-online/fpgas.online-fpga-tools#debian-packages-bookworm-trixie-sid-arm64-armhf)
**before** installing. Without it apt installs Debian's `openfpgaloader`, which is enough for the Arty and
Fomu, but has no `rp1pio` cable (a NeTV2 on a Pi 5) and, in bookworm, no SPI-over-JTAG bridge for the NeTV2's
XC7A35T-FGG484 (its flash readback fails).

**Say which board the host has** by installing exactly one *mode* package:

| Install | The host has | If no board is found |
|---|---|---|
| `fpgas-online-<board>` | that one board; nothing else is looked for | `missing` (fatal) |
| `fpgas-online-all-boards` | any of the boards: every board's tools, and whichever is found is checked. For a netboot root shared by every Pi | `missing` (fatal) |
| `fpgas-online-multi-board` and the `fpgas-online-<board>-tools` you want | any of the boards you chose | `missing` (fatal) |

The mode packages conflict with each other, so a host is never set up for two boards by accident. Each pulls
in the packages below. `<board>` is one of:

| Board | Mode package | Commands | Board page |
|---|---|---|---|
| Sqrl Acorn CLE-215+ / CLE-101 (and LiteFury/NiteFury) | `fpgas-online-acorn` | `fpgas-acorn-verify`, `fpgas-acorn-debug`, `fpgas-acorn-flash` | [acorn.md](hardware/acorn.md#installing-the-acorn-packages) |
| Digilent Arty A7-35T | `fpgas-online-arty` | `fpgas-arty-verify`, `fpgas-arty-debug` | [arty-a7.md](hardware/arty-a7.md#installing-the-arty-packages) |
| Kosagi NeTV2 (XC7A35T or XC7A100T) | `fpgas-online-netv2` | `fpgas-netv2-verify`, `fpgas-netv2-debug` | [netv2.md](hardware/netv2.md#installing-the-netv2-packages) |
| Fomu EVT | `fpgas-online-fomu` | `fpgas-fomu-verify`, `fpgas-fomu-debug` | [fomu-evt.md](hardware/fomu-evt.md#installing-the-fomu-packages) |
| TT FPGA Demo Board | `fpgas-online-tt-fpga` | `fpgas-tt-fpga-verify`, `fpgas-tt-fpga-debug` | [tt-fpga.md](hardware/tt-fpga.md#installing-the-tt-fpga-packages) |

| Package | Contains |
|---|---|
| `fpgas-online-verify` | the `fpgas_online_verify` package, the host test scripts (`designs/*/host/`), `fpgas-verify`, and `fpgas-verify.service` (installed, but enabled only by a mode package) |
| `fpgas-online-<board>-tools` | the board's module and `fpgas-<board>-verify`, with exactly the programmer and libraries that board's boot check needs; depends on one exact version of the bitstreams |
| `fpgas-online-<board>-bitstreams` | the test bitstreams and a sha256 `manifest.json`, in `/usr/share/fpgas-online/<board>/bitstreams/` (the Acorn's: `/usr/share/fpgas-online/acorn-pcie/images/`, the Vivado release pinned in [`packaging/acorn-pcie/release.toml`](../packaging/acorn-pcie/release.toml)); the others are built by the same commit's CI |
| `fpgas-online-<board>-debug` | `fpgas-<board>-debug`, and what the tests the boot check leaves out need (`python3-libgpiod`; for the Acorn, openFPGALoader and `python3-serial`) |
| `fpgas-online-<board>` | only `/usr/share/fpgas-online/verify/mode.d/fpgas-online-<board>.ini` (`[verify] fpga-board = <board>`); its postinst enables `fpgas-verify.service` |
| `fpgas-online-multi-board` | `mode.d/fpgas-online-multi-board.ini` (`fpga-board = auto`); enables the unit |
| `fpgas-online-all-boards` | depends on `fpgas-online-multi-board` and every `-tools`; recommends every `-debug` |

Versions are `0.0.postN` from `git describe` against the `v0.0` tag (for example `0.0.post673`); every
package of one build depends on the others at exactly that version, so an upgrade moves them together:
`sudo apt update && sudo apt upgrade`. The
packages are built and their install rules checked in clean bookworm and trixie by
[`collect-bitstreams.yml`](../.github/workflows/collect-bitstreams.yml)
([`packaging/debs/build_debs.py`](../packaging/debs/build_debs.py),
[`install_test.sh`](../packaging/debs/install_test.sh)).

Installing does **not** run the check: it loads test designs into the board, so it waits for the next boot,
or for you.

### Commands

```bash
sudo fpgas-verify                                  # what the boot unit runs: check, report, publish; exit 0 only for pass
sudo fpgas-arty-verify --no-publish --report -     # one board, whatever the configuration, the JSON report on stdout
fpgas-verify --list                                # the installed board modules, and the configured mode
sudo fpgas-verify --update                         # accept a board or flash that changed on purpose (see below)
```

| Option | Does |
|---|---|
| `--board B` | `fpgas-verify` only: check board `B`, whatever the configuration says (as `fpgas-B-verify` does) |
| `--no-probe` | `fpgas-verify` only: with `fpga-board = auto`, never drive anything to find a board (no NeTV2 JTAG scan) |
| `--test T` | run only test `T` (repeatable): any test in `fpgas-<board>-debug list`, boot check or not. This is part of the check, not the board's result: it is never published (no `fpga-verifying` / `fpga-verified`, so the site's gate never sees it), its report goes to stdout unless `--report` says otherwise (never over the boot's `/run/fpgas-online/verify.json`), and it neither records nor compares the state, so it never causes a later `changed`. Not with `--update`. Configured for one board, a name it does not have is an `error`. With `auto`, each board found runs the named tests it has (the rest are listed as `tests_skipped`); a board with none of them is not checked (`not_checked`), and if no board has any of them the result is `error` |
| `--variant V`, `--port P`, `--images DIR` | override the detected variant, the board's UART on the Pi, the installed bitstreams |
| `--report PATH` | where the JSON report goes (default `/run/fpgas-online/verify.json`, or stdout with `--test`; `-` for stdout) |
| `--state PATH` | the recorded state (default `/var/lib/fpgas-online/verify-state.json`) |
| `--update` | record what is found now as the state, instead of failing on a difference |
| `--no-publish` | do not send any fleet-events |

Which board a host has is read from `[verify] fpga-board = <board>|auto` in `*.ini` files: the mode package's
in `/usr/share/fpgas-online/verify/mode.d/`, then the admin's in `/etc/fpgas-verify/`, which wins. Two files
in one directory that disagree are an `error`. Options for the boot unit (`--no-probe`, say) go in
`FPGAS_VERIFY_ARGS` in `/etc/default/fpgas-verify`.

Only one user drives a board at a time: the check and `fpgas-<board>-debug` hold
`/run/fpgas-online/<board>.lock` (the Acorn's is `/run/lock/fpgas-acorn.lock`, shared with
`fpgas-acorn-flash`), and the second waits,
saying so.

From a checkout, without installing: `PYTHONPATH=verify/src uv run --no-project python -m fpgas_online_verify --help`.

### What each board's check tests

For the LiteX-design boards (Arty, NeTV2, Fomu, TT) each boot-check test is the same sequence
([`testbench.py`](../verify/src/fpgas_online_verify/testbench.py)): check the bitstream against the
`-bitstreams` package's manifest (a damaged file is an `error`, never loaded), load it into the FPGA, run its
host test script, and keep the last 20 lines of its output. A test passes when its script exits 0. The
board's result is the worst of its tests'.

| Test | Host script | Passes when |
|---|---|---|
| `uart` | [`test_uart.py`](../designs/uart/host/test_uart.py) | the design's LiteX BIOS banner arrives (the NeTV2, Fomu and TT skip this wait) and printable ASCII echoes back |
| `ddr` | [`test_ddr.py`](../designs/ddr-memory/host/test_ddr.py) | the BIOS reports DRAM calibration and `Memtest OK` |
| `spiflash` | [`test_spiflash.py`](../designs/spi-flash-id/host/test_spiflash.py) | the firmware reads a JEDEC ID from the configuration flash and prints `SPI_FLASH_TEST: PASS` |
| `ethernet` | [`test_ethernet.py`](../designs/ethernet-test/host/test_ethernet.py) | the design answers ARP and ping through the Pi's USB Ethernet adapter cabled to the board (static 192.168.1.100/24 on that adapter only) |
| `pin-id` | [`identify_pmod_pins.py`](../designs/pmod-pin-id/host/identify_pmod_pins.py) | every Pmod HAT GPIO receives the FPGA ball name the expected cabling puts there (each pin transmits its own name at 1200 baud) |
| `pmod` | [`test_pmod_loopback.py`](../designs/pmod-loopback/host/test_pmod_loopback.py) | never at boot: needs loopback wiring; `fpgas-<board>-debug test pmod` |

| Board | Found by | Loaded with | Boot-check tests, in order | Only in `-debug` | State (a change is `changed`) |
|---|---|---|---|---|---|
| Arty A7 | USB `0403:6010` (FT2232H) | `openFPGALoader -b arty` | `uart`, `ddr`, `spiflash`, `ethernet`, `pin-id` (UART `/dev/ttyUSB1`) | `pmod` | FTDI serial, flash JEDEC ID, sha256 of the flash's first 2.1 MiB (read back over openFPGALoader's SPI-over-JTAG bridge, which is left loaded) |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22, which also gives the variant | openocd `bcm2835gpio` (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `uart`, `ddr`, `spiflash` (UART `/dev/ttyAMA0`; `spiflash` listens before the load, its ID is printed only once) | `ethernet`, `pmod`, `pin-id` | IDCODE, flash JEDEC ID, sha256 of the flash's boot image region |
| Fomu EVT | USB `1209:5bf0` (foboot DFU) | openFPGALoader over DFU | `uart` only (UART `/dev/serial0`): a DFU load replaces the bootloader until the next power cycle | `spiflash`, `pmod`, `pin-id` | foboot's USB serial (every load rewrites the user image) |
| TT FPGA | USB `2e8a:*` (the demo board's Raspberry Pi microcontroller) | `tt_fpga_program.py` over `mpremote` | `pin-id`, then `uart`, `spiflash` through the microcontroller's UART bridge (`tt_test_wrapper.py`, `/dev/ttyACM0`); `fpgas-tt.service` is stopped for the tests and started again | `pmod` | the microcontroller's USB serial (every load rewrites the bitstream file on it) |
| Acorn | PCI `10ee:*` / `1e24:*` | nothing: runs from its flash | `pcie-link`, `pcie-bar0`, `jtag`, `flash`, `p2-uart`, `scratch`, `p2-gpio` (see below) | | PCI slot and IDs, device DNA, flash part, JEDEC ID and unique ID, sha256 of both flash slots |

The board is left running the last design loaded, except where the flash is read back afterwards: the Arty
and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge. Each comes back to its flash image at
its next power cycle.

The NeTV2 has no USB, so finding it means driving the GPIO header. On a host set up for `netv2` that is all
it looks for; with `auto` the JTAG scan runs only when nothing was found by USB/PCI IDs (or only a Xilinx PCIe
design the Acorn module cannot name, which may be a NeTV2 on PCIe), and `--no-probe` rules it out.

The **Acorn** check ([`boards/acorn/suite.py`](../verify/src/fpgas_online_verify/boards/acorn/suite.py),
[`check.py`](../verify/src/fpgas_online_verify/boards/acorn/check.py),
[`links.py`](../verify/src/fpgas_online_verify/boards/acorn/links.py)) loads nothing, never writes the flash and
never reconfigures the FPGA. It runs every test it can, in the order below, and a fault in one does not stop
the others: the board's reason lists every fault.

**Which board it is.** From the PCI IDs alone:

| PCI IDs | Is | Result |
|---|---|---|
| `10ee:7021`, subsystem `1e24:021f` (CLE-215+) or `1e24:0101` (CLE-101) | the fpgas.online Acorn SoC | tested |
| `1e24:021f` or `1e24:0101` as vendor:device | an Acorn on SQRL's factory image | `fail`, `unconverted: …`; only `pcie-link` and `jtag` run |
| `10ee:7011` | the vendor XDMA sample (an Acorn or a NeTV2) | `fail`, `unconverted: …` |
| `10ee:0666` | a PCIe Screamer running PCILeech | `fail`: fpgas.online has no test design for this board yet |
| `10ee:7021`, subsystem `10ee:0007`, class `070001`, with a BAR2 | a stock Xilinx XDMA design (most likely a PicoEVB) | `fail`: fpgas.online has no test design for this board yet |
| any other Xilinx or SQRL ID | not a design we built | `fail` |

The XDMA design and an old LitePCIe build of ours have the same IDs, since both keep the Xilinx default
subsystem `10ee:0007`, so the class code and the BAR2 that only the XDMA IP has tell them apart.

Nothing is sent to the BARs of a board whose PCI IDs are not ours. On ours, nothing past the identifier read
is sent over BAR0 or over the P2 UART unless that identifier is a build of the installed release (one the
release's manifest lists). The CSR addresses then come from that build's `csr.json` in the release, and a
`csr.json` that puts a CSR the check uses outside the 64 KiB of BAR0 it maps is an `error`.

**Which setup the host is.** The Acorn has two setups, each with its own wiring, both in
[`docs/wiring/acorn/wiring.toml`](wiring/acorn/wiring.toml), which the tools package installs:

| Host (`/proc/device-tree/model`) | Setup | JTAG `--pins` (TDI:TDO:TCK:TMS) | GPIO chip | J5 / H5 |
|---|---|---|---|---|
| `Raspberry Pi 5 Model B` | Pi 5 with the Waveshare HAT | `10:9:11:8` | `raspberrypi,rp1-gpio` | GPIO3 / GPIO4 |
| `Raspberry Pi Compute Module 4` | Compute Blade | `2:3:4:14` | `brcm,bcm2711-gpio` | not wired |
| `Raspberry Pi Compute Module 5` | Compute Blade | `2:3:4:14` | `raspberrypi,rp1-gpio` | not wired |

Both use openFPGALoader's `libgpiod` cable (a CM4 has no RP1, so `rp1pio` cannot be used there), and the P2
UART is `/dev/ttyAMA0`. Any other host is an `error`; the tests that do not need the wiring still run. The
figures each setup must meet are in [`expected.toml`](wiring/acorn/expected.toml) beside it.

**The tests:**

| Test | Over | Passes when |
|---|---|---|
| `pcie-link` | sysfs | `current_link_speed` and `current_link_width` are the setup's (5.0 GT/s, x1) |
| `pcie-bar0` | BAR0 | the operational build runs (the golden build means the operational slot did not boot), the flash identifies itself, the device DNA is neither all zeros nor all ones, and the XADC temperature and VCCINT, VCCAUX and VCCBRAM are in range |
| `jtag` | P1 | `openFPGALoader --detect` finds one device with the variant's IDCODE, and `openFPGALoader --read-dna` reads the DNA BAR0 gave. The IDCODE read does not use TDI; the DNA read does |
| `flash` | BAR0 | both 4 MiB slots (golden at `0x000000`, operational at `0x400000`), read whole with read opcodes only, hold the release's images |
| `p2-uart` | P2 | the UARTBone identifier at 1200 baud is BAR0's; the link moves to 921600 baud; there the identifier, DNA and XADC readings are right and the DNA is BAR0's. The link is left at 1200 baud |
| `scratch` | BAR0 and P2 | the `ctrl` scratch register holds two patterns written over each bridge; its value is put back |
| `p2-gpio` | BAR0 and the Pi's GPIO | Pi 5 setup only. Through the `p2_gpio` CSR, the FPGA drives J5/H5 and the Pi reads GPIO3/GPIO4, then the Pi drives and the FPGA reads, each ball at 0 and at 1, with the reading side's pull set against the driven level. Both sides go back to inputs |

openFPGALoader leaves the JTAG pins driven, so they are put back as they were found (`pinctrl`): on a Compute
Blade GPIO14 is both TMS and the UART's TX, and goes back to its UART function.

A test that cannot run because of an earlier fault (no BAR0 on a factory image, say) is listed in the
report's `not_run` with why; the fault that stopped it is in the reason. A test that fails in a way the
check did not foresee is an `error` naming what went wrong, and the others still run.

A kernel driver bound to the board (`litepcie.ko`) is unbound for the check, but only when a test asked for
uses BAR0 (`pcie-bar0`, `flash`, `scratch`, `p2-gpio`), and bound again after it. The events of the tests
run meanwhile are held and sent once it is bound again.

`--test` runs any of these on their own: `--test pcie-link --test pcie-bar0 --test flash` only reads.

The PCIe transfer rate (DMA) is not measured yet.

### Reading the result

The run's result is the worst of its boards'. Only `pass` exits 0; anything else is a fail of the check, and
also leaves `fpgas-verify.service` failed. The other results say what kind of fail it is.

| Result | Meaning |
|---|---|
| `pass` | every test passed, and the board and its flash are the ones recorded |
| `changed` | a different board, or a different flash, from the recorded state |
| `fail` | a test, a load or a flash comparison failed, or the board runs a design that is not ours (`unconverted: …` for an Acorn on SQRL's image) |
| `missing` | the configured board (or with `auto`, any board) is not there |
| `error` | the check itself could not run: a missing tool, a damaged package, no configuration |

The summary goes to stderr, so to the journal at boot (`journalctl -b -u fpgas-verify`). Anything but `pass`
is framed in a banner, with the last 8 output lines of each failed test:

```text
******************************************************************************
*** FPGA VERIFY: FAIL *******************************************************
fpgas-verify: fail (mode auto, auto: probed (netv2))
  netv2 a7-35: fail: ddr fail: the test exited 1
    uart       pass
    ddr        fail: the test exited 1
        ...
        RESULT: FAIL — DDR memory test had failures
    spiflash   pass
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json
  more: fpgas-<board>-debug (fpgas-online-<board>-debug)
******************************************************************************
```

### The report

The full result is JSON in `/run/fpgas-online/verify.json` (tmpfs: this boot's). Its main fields
(`schema_version` 2):

| Field | Holds |
|---|---|
| `result`, `reason` | the run's result, and why, when it found no board |
| `checked_at` | when (UTC, ISO 8601) |
| `mode`, `configured_by`, `chosen_by` | `auto` or the board, the file (or "command line") that said so, and how the boards were found |
| `boards[]` | per board: `board`, `variant`, `found` (what identified it), `result`, `reason`, `bitstreams` (the package or release version), `tests[]` (`test`, `bitstream`, `result`, `reason`, `output` lines, `flash_jedec`), `state`, and `flash_note` / `flash_error`. The Acorn's tests also carry what they read (`speed_gt_s`, `width`, `dna`, `xadc`, `idcode`, `baud`, ...), and the board has `setup`, `identity` (PCI slot and IDs, build, DNA, IDCODE, flash IDs), `running` (`identifier`, `build`), `flash` (`part`, `jedec`, `unique_id`, `slots[]` with `match`/`mismatch` and `first_difference`), `not_run`, and `driver` when a driver was unbound |
| `state` | `file`, and `recorded` (`first run` or `--update`) or `changes` |

```bash
python3 -c 'import json; r = json.load(open("/run/fpgas-online/verify.json")); print(r["result"]); [print(b["board"], t["test"], t["result"]) for b in r["boards"] for t in b.get("tests", [])]'
```

### The recorded state and `changed`

On a host with persistent storage the first run records each board's identity and a fingerprint of its
flash in `/var/lib/fpgas-online/verify-state.json`. A later run that sees a different board, or a flash that
was rewritten, is `changed` (fatal) until `sudo fpgas-verify --update` records the new state: run it after
flashing or swapping a board on purpose. Loading a design into SRAM (every check does) and upgrading the
packages are not changes. A flash that could not be read this time is not compared. A fact the record does
not have is a change ("not recorded before"): it may not have been readable last time, on a board since
swapped. The exception is a fact a newer version of the record added (the record has a `schema_version`; 2
added the Acorn's device DNA): on an older record it is added quietly, unless the run's result is `error`.

### The debug tool

`fpgas-online-<board>-debug` brings `fpgas-<board>-debug`, which does the check's steps one at a time with the
output live, and has the tests the boot check leaves out:

```bash
sudo fpgas-arty-debug detect                 # is the board there, and what identifies it
fpgas-arty-debug list                        # every test, boot check or debug only, and its installed bitstream
sudo fpgas-arty-debug check                  # every installed bitstream against the manifest
sudo fpgas-arty-debug program uart           # load a test's design and leave it running
sudo fpgas-arty-debug test ddr               # load it and run its host test
sudo fpgas-arty-debug test pin-id -- --hat-port JA   # after --: arguments for the test script
sudo fpgas-acorn-debug detect                # the Acorn: the Acorn-family endpoints on PCI
sudo fpgas-acorn-debug identify              # the running build, and the flash's part, JEDEC ID and unique ID
```

Each takes `--port`, `--variant` and `--images` like the check. `fpgas-acorn-flash` (in
`fpgas-online-acorn-tools`) identifies, dumps, verifies and (only when asked) writes the Acorn's flash; see
[acorn.md](hardware/acorn.md) and [acorn-pcie-programming.md](hardware/acorn-pcie-programming.md).

### Common failures

| What it says | What it means, and what to do |
|---|---|
| `missing`: `no <board> found: this host is set up for one` | the board is not on USB/PCI (or the NeTV2 not on JTAG). Check power and the cable. A Fomu that has run a design is not in DFU until it is power-cycled |
| `missing`: `none of the installed boards … was found` | an `auto` host with nothing attached; expected on Pis with no FPGA |
| `error`: `… is not installed` | a tool the board needs is missing: `mpremote` (bookworm: from bookworm-backports), openocd, openFPGALoader |
| `error`: `no FPGA board is configured` / `conflicting fpga-board settings` | install one mode package, or fix `/etc/fpgas-verify/*.ini` |
| `error`: `… does not match its manifest` / `manifest.json is missing` | a damaged or partly installed `-bitstreams` package: `sudo apt install --reinstall fpgas-online-<board>-bitstreams` |
| `fail`: `loading it failed (exit N)` | the programmer could not load the design: JTAG wiring, cable, or a programmer without support for this part or cable |
| `fail`: `python3 did not finish within 300 s` | the design never said what the test waits for (no BIOS banner, nothing on the UART). Wrong UART, or a design that does not run |
| `fail`: `the test exited 1` | the test ran and failed; its last lines are in the report and the banner. `fpgas-<board>-debug test <test>` shows all of it |
| `fail`: `pin-id …` (`N/18 pins match expected wiring`) | the Pmod HAT cabling differs from the board's expected map |
| `fail`: `unconverted: …` | an Acorn still on SQRL's factory image (or the XDMA sample): convert it ([acorn-pcie-programming.md](hardware/acorn-pcie-programming.md)) |
| `fail`: `… is not a design we built` | a Xilinx PCIe design the Acorn module does not know; its flash is not read |
| `fail`: `no device on the P1 JTAG chain` / `no UARTBone reply on /dev/ttyAMA0` | an Acorn whose JTAG or P2 UART cable to the Pi is off or miswired |
| `fail`: `device DNA over JTAG … is not the one over BAR0` | the P1 TDI wire does not carry, or the DNA readout is wrong |
| `fail`: `J5 -> GPIO3: the FPGA drove 0, the Pi read 1` (or the other way) | a P2 spare wire is cut or miswired |
| `fail`: `running the golden image` | the Acorn's operational slot did not boot; it fell back to golden |
| `fail`: `… has no test design for this board yet` | a Xilinx PCIe board that is not an Acorn (a PCIe Screamer, a PicoEVB) |
| `error`: `this host (…) is not an Acorn setup in wiring.toml` | an Acorn on a host neither setup has: add the host to `wiring.toml` if it is a real setup |
| `changed` | see [above](#the-recorded-state-and-changed) |
| `could not publish fpga-verified` (warning) | no `fleet-event` (not a fleet Pi) or the broker is down; the result is unchanged and still in the report |
| `waiting for another user of the <board> to finish...` | someone is using the board with `fpgas-<board>-debug` or `fpgas-acorn-flash`; the check waits for them |

---

## 2. How verify is used and integrated in fpgas.online

### The netbooted Pis

At a site such as Welland every Pi netboots from one NFS root on the site gateway (tweed), mounted read-only
with a tmpfs overlay ([fpgas.online-infra](https://github.com/fpgas-online/fpgas.online-infra)). That root is
built with `fpgas-online-all-boards` (infra `roles/onpi/tasks/fpga_verify.yml`, `onpi_fpga_verify_package`),
so every Pi carries every board's check and each finds whichever board it has (`fpga-board = auto`). A Pi with
no FPGA (the Orange Pis, a Pi whose board is off) reports `missing`. It still boots and takes ssh, so someone
can log in and look.

Because `/var/lib` is on the tmpfs overlay, every boot is a first run: the recorded state starts afresh, and
`changed` never fires on the fleet.

### At boot

`fpgas-verify.service` ([`packaging/debs/fpgas-verify.service`](../packaging/debs/fpgas-verify.service)) is a
oneshot that runs `fpgas-verify` once per boot:

* `After=network-online.target fpgas-fleet-agent.service`: the site already knows the Pi is up when the
  check starts.
* `Before=fpgas-tt.service`: the TT site's bridge, which holds the TT board's serial port, starts only once
  the check is done (ordering only: a failed check still lets it start). Nothing holds up ssh.
* `TimeoutStartSec=1800`: each test loads a design (openocd on a Pi 3 takes a minute or more) and the Arty
  and NeTV2 flash are read back after.

Anything but `pass` leaves the unit failed; the banner is in `journalctl -b -u fpgas-verify`.

### Publishing the result

The check publishes fleet-events through `fleet-event` (from
[fpgas.online-setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi)), which sends them over MQTT to
the site's broker (`fpgas/<site>/pi/<serial>/event`). Each is small, and its details are flat strings with
fixed names (`EVENTS` in [`runner.py`](../verify/src/fpgas_online_verify/runner.py)):

| Event | When | Details |
|---|---|---|
| `fpga-verifying` | the check starts (15 s timeout, so a dead broker does not hold up the check) | `started_at` |
| `fpga-board-found` | for each board found | `board`, `variant`, `where` (PCI slot, USB path or JTAG IDCODE) |
| `fpga-no-board` | no board was found | `reason` |
| `fpga-board-identified` | an Acorn, once PCIe and JTAG have said who it is | `board`, `bdf`, `pci_ids`, `subsystem`, `variant`, `identifier`, `build`, `dna`, `idcode`, `flash_part`, `flash_jedec`, `flash_unique_id` |
| `fpga-test-started` | each test starts | `board`, `test` |
| `fpga-test-finished` | each test ends | `board`, `test`, `result`, `reason` |
| `fpga-verified` | the check is done | the report flattened: `result`, `mode`, `reason`, and per board `board0` (`netv2 a7-35 fail`), `board0_reason`, `board0_tests` (`uart=pass ddr=fail spiflash=pass`), `board0_bitstreams`, `board0_state_*` and `board0_identity_*` |

`board` is the board's name, or `name@where` when there are two of a kind. Every event but the first and the
last is progress: if one cannot be sent, no more progress events are tried this run, but `fpga-verified` is.

A failure to publish is reported on stderr but does not change the result; the report stays in
`/run/fpgas-online/verify.json`.

The fleet agent (`fpgas-fleet-agent.service`) has already registered the Pi by its serial number and reported the boot it is running. The site's fleet app
([fpgas.online-site](https://github.com/fpgas-online/fpgas.online-site) `fleet/src/fleet/services.py`) records each event
as a `BootEvent`. `fpga_states()` gives each Pi's check for **the boot it is running now**: `verifying` from
`fpga-verifying` until an `fpga-verified` follows, then that event's `result`. An earlier boot's result says
nothing about the board now. `/fleet/` lists every Pi with that state, and `/fleet/<serial>/` shows this boot's
events with their details.

### The site's gate

`verified_serials()` is the set of Pis whose state is `pass`. With `FPGAS_REQUIRE_VERIFIED = True` in the
site's settings (infra `site_require_fpga_verified`, `true` for Welland in
`ansible/inventory/host_vars/fpgas.online.yml`), the `/fpgas/` pages offer only those Pis. A Pi whose check
failed, found nothing, is still running, or has not reported this boot is not offered to users.

### How a deploy picks up new debs

1. A commit lands on `main` here. `collect-bitstreams.yml` builds every package and, when CI is green,
   uploads them to this repository's rolling series release, `v0.0`.
2. [fpgas-online/apt](https://github.com/fpgas-online/apt) pulls that release into <https://apt.fpgas.online>,
   within about 15 minutes.
3. The infra CI (`nfsroot-build.yml`, run by `vm-test.yml` on infra pushes, PRs, its schedule or a manual
   dispatch) converges the NFS root image, whose `fpga_verify.yml` installs `fpgas-online-all-boards` with
   `state: latest`, and publishes it as `ghcr.io/fpgas-online/nfsroot:ci-<run>`. On infra `main` it moves the
   rolling `bookworm-armhf` tag once a virtual Pi has netbooted the image.
4. An operator runs infra `site.yml` against tweed (whole playbook, `--limit fpgas.online`, optionally
   `-e img_nfsroot_image=ghcr.io/fpgas-online/nfsroot:ci-<run>` to pin the image CI tested). Its `img` role
   pulls and extracts the image into `/srv/nfs/rpi/<dist>`, and `fixpi` applies the site layer. The run bumps
   the root's generation marker.
5. Each Pi's `nfsroot-watchdog` sees its root go stale and reboots in its own slot (slot
   `(switch - 1) × 48 + (port - 1)`, 20 s apart: a two-switch site is done within about 33 minutes).
6. Each Pi boots the new root, runs `fpgas-verify` with the new packages, and publishes the result; the site's
   gate follows it.

To see what the Pis report after a deploy, run the collector below; the `fpgas-online-verify` column shows
which build each Pi ran.

### Collecting every Pi's result

[`scripts/collect_verify_status.py`](../scripts/collect_verify_status.py) reads every Pi's latest result over
SSH, read-only (the report, the unit's state, the installed version, and the journal when there is no report),
and prints the tables below. It never loads, runs, stops or reboots anything, so it is safe while the boards
are in use.

```bash
uv run --no-project python scripts/collect_verify_status.py \
    --ssh-config ../fpgas.online-infra/ansible/ssh.cfg            # every port on both Welland switches
uv run --no-project python scripts/collect_verify_status.py --host 10.21.2.47 --json tmp/verify.json
```

By default it goes through the jump host `ansible@10.99.21.2` (tweed) as `root` to `10.21.<switch>.<port>`
for switch 1 ports 1-40 and switch 2 ports 1-48, except sw2 p30, the Orange Pis' FEL host, which is not on
the fpgas root (`--jump`, `--user`, `--ports`, `--exclude`, `--host`, or `FPGAS_JUMP_HOST` /
`FPGAS_SSH_CONFIG`). A port counts as having no Pi only when the jump host cannot forward to it.

It checks the jump host first and exits 2 if that cannot be reached. It exits 1 if it read no Pi at all, if a
Pi answered but could not be read (a refused key, a timeout, a broken report), or if an address given with
`--host` did not answer; otherwise 0.

Every Pi boots the same root, so they all have one host key. That key survives root rebuilds: infra keeps
the root's `/etc/ssh/ssh_host_*` out of the image rsync. The collector checks it under the
alias `fpgas-netboot-pi` in its own known-hosts file, `~/.config/fpgas-online/netboot_known_hosts`
(`--known-hosts`, `FPGAS_NETBOOT_KNOWN_HOSTS`), learning it on first use (`StrictHostKeyChecking=accept-new`,
`CheckHostIP=no`, unhashed, no agent forwarding). After a deliberate rekey of the netboot root, forget the
old key with `ssh-keygen -R fpgas-netboot-pi -f ~/.config/fpgas-online/netboot_known_hosts`, never with
`-H`. The jump host's key is checked as the SSH config says.

The site's `/fleet/` page shows the same overall result per Pi, but not the tests.

### Current results

Collected 2026-10-01T01:51:27Z by `scripts/collect_verify_status.py`, from the Welland Pis running `0.0.post673`.
Rerun it to refresh this section.

| Board | Pis | Result | Tests (passed / run) |
|---|---|---|---|
| Acorn | 2 | pass 2 | jtag 2/2, p2-uart 2/2 |
| Arty A7 | 4 | fail 4 | uart 0/4, ddr 0/4, spiflash 4/4, ethernet 3/4, pin-id 0/4 |
| NeTV2 | 5 | fail 5 | uart 5/5, ddr 0/5, spiflash 5/5 |
| TT FPGA | 3 | fail 3 | pin-id 0/3, uart 3/3, spiflash 0/3 |
| Unrecognised PCIe FPGA | 2 | fail 2 | - |
| (no board) | 8 | missing 8 | - |

| Host | Pi | Board | Variant | Result | Tests | Reason | Checked (UTC) | fpgas-online-verify |
|---|---|---|---|---|---|---|---|---|
| pi-sw1-p10 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-09-30T17:42:32Z | 0.0.post673 |
| pi-sw1-p12 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-09-30T17:43:30Z | 0.0.post673 |
| pi-sw1-p14 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-09-30T17:44:44Z | 0.0.post673 |
| pi-sw1-p16 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-09-30T17:45:01Z | 0.0.post673 |
| pi-sw1-p17 | Pi 3B+ | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T17:45:16Z | 0.0.post673 |
| pi-sw1-p18 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-09-30T17:45:25Z | 0.0.post673 |
| pi-sw1-p38 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | 10ee:0666 subsystem 10ee:0007 is not a design we built | 2026-09-30T17:52:10Z | 0.0.post673 |
| pi-sw2-p9 | Pi 4B | Arty A7 | a7-35 | fail | uart=**fail** ddr=**fail** spiflash=pass ethernet=pass pin-id=**fail** | uart fail: python3 did not finish within 300 s: ; ddr fail: the test exited 1; pin-id fail: the test exited 1 | 2026-09-30T17:57:44Z | 0.0.post673 |
| pi-sw2-p10 | Pi 4B | Arty A7 | a7-35 | fail | uart=**fail** ddr=**fail** spiflash=pass ethernet=**fail** pin-id=**fail** | uart fail: python3 did not finish within 300 s: ; ddr fail: the test exited 1; ethernet fail: the test exited 1; pin-id fail: the test exit… | 2026-09-30T17:58:58Z | 0.0.post673 |
| pi-sw2-p12 | Pi 4B | Arty A7 | a7-35 | fail | uart=**fail** ddr=**fail** spiflash=pass ethernet=pass pin-id=**fail** | uart fail: python3 did not finish within 300 s: ; ddr fail: the test exited 1; pin-id fail: the test exited 1 | 2026-09-30T17:59:07Z | 0.0.post673 |
| pi-sw2-p15 | Pi 4B | Arty A7 | a7-35 | fail | uart=**fail** ddr=**fail** spiflash=pass ethernet=pass pin-id=**fail** | uart fail: python3 did not finish within 300 s: ; ddr fail: the test exited 1; pin-id fail: the test exited 1 | 2026-09-30T17:59:23Z | 0.0.post673 |
| pi-sw2-p18 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:01:52Z | 0.0.post673 |
| pi-sw2-p19 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:01:33Z | 0.0.post673 |
| pi-sw2-p20 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:01:45Z | 0.0.post673 |
| pi-sw2-p21 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:02:28Z | 0.0.post673 |
| pi-sw2-p22 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:03:32Z | 0.0.post673 |
| pi-sw2-p23 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:03:05Z | 0.0.post673 |
| pi-sw2-p24 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-09-30T18:03:19Z | 0.0.post673 |
| pi-sw2-p33 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-09-30T18:06:29Z | 0.0.post673 |
| pi-sw2-p35 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-09-30T18:06:50Z | 0.0.post673 |
| pi-sw2-p36 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-09-30T18:07:57Z | 0.0.post673 |
| pi-sw2-p37 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | 10ee:7021 subsystem 10ee:0007 is not a design we built | 2026-09-30T18:06:51Z | 0.0.post673 |
| pi-sw2-p47 | Pi 5B | Acorn | cle-215+ | pass | jtag=pass p2-uart=pass |  | 2026-09-30T18:11:30Z | 0.0.post673 |
| pi-sw2-p48 | Pi 5B | Acorn | cle-215+ | pass | jtag=pass p2-uart=pass |  | 2026-09-30T21:09:08Z | 0.0.post673 |

No Pi answered on 63 ports: sw1 p1-9,p11,p13,p15,p19-37,p39-40; sw2 p1-8,p11,p13-14,p16-17,p25-29,p31-32,p34,p38-46.

What the failures are:

* **NeTV2 `ddr`** (all five): read leveling fails on every lane, so the memtest reads nothing back right (on
  pi-sw1-p10: 256/256 bus errors, every word a data error). Cause: nextpnr-xilinx does not know `SSTL15_R`,
  the NeTV2's DDR3 I/O standard, so the DQ pins are built with no input buffer. The fix is in main's
  bitstreams (`fix_openxc7_reduced_drive_iostandards` builds them as `SSTL15`, and a FASM step sets the bank
  VREF and the reduced drive); the devices run `0.0.post673`. `uart` and `spiflash` pass.
* **Arty `ddr`** (all four): DRAM calibration is never reported. Cause: the `0.0.post673` DDR build misses
  100 MHz timing (it reaches 70 MHz). Main's bitstreams run the Arty DDR design at 75 MHz under openXC7, and its
  build fails if it misses timing; the devices run `0.0.post673`.
* **Arty `uart`** (all four): the design prints nothing and the test times out. Cause: the build misses
  timing (82.8 MHz achieved against 100 MHz). Tracked by
  [#64](https://github.com/fpgas-online/fpgas.online-test-designs/pull/64), which fails CI on missed timing
  and runs the Arty UART design at 75 MHz.
* **Arty and TT `pin-id`**: the Pmod HAT cabling differs from the expected maps
  ([#58](https://github.com/fpgas-online/fpgas.online-test-designs/issues/58)), pending recabling.
* **Arty `ethernet` on pi-sw2-p10**: no ARP reply through the USB adapter.
* **TT `spiflash`** (all three): the JEDEC ID reads `0x000000`
  ([#52](https://github.com/fpgas-online/fpgas.online-test-designs/issues/52)).
* **pi-sw1-p38 and pi-sw2-p37**: Pi 5s with a Xilinx PCIe design that is not an fpgas.online Acorn image.
* **pi-sw1-p17**: only its OpenVizsla is on USB; its Fomu does not enumerate, so `missing`.
* **pi-sw2-p18 … p24**: Orange Pi PCs on the same root with no FPGA: `missing` is expected. pi-sw2-p30, their
  FEL host, is not on the fpgas root and is not read.
* Nothing answers on pi-sw2-p34, the fourth TT FPGA board.
