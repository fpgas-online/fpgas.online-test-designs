# fpgas-verify: checking an FPGA board from its Raspberry Pi

`fpgas-verify` answers one question per Pi: **is this Pi and its FPGA board ready for users?** It finds the
board, tests the board and its wiring to the Pi, and gives one result, pass or fail, with every fault it found.

* What the tool must do: [verify-goals.md](verify-goals.md). Where this page and that one disagree,
  verify-goals.md says what the tool should do.
* The code: [`verify/`](../verify/). The design notes:
  [plans/2026-09-26-fpgas-online-verify-design.md](plans/2026-09-26-fpgas-online-verify-design.md).
* `verify_hardware.py` ([verify-hardware.md](verify-hardware.md)) is a different tool: a developer's script
  that loads freshly built bitstreams from a workstation over SSH.

This page has two parts:

1. [Using verify as a standalone tool](#1-using-verify-as-a-standalone-tool): installing, running, reading the
   result, and what each board's check tests.
2. [How verify is used in fpgas.online](#2-how-verify-is-used-in-fpgasonline): at every boot of every
   netbooted Pi, the events it sends the site, and the [current results](#current-results).

---

## 1. Using verify as a standalone tool

### Installing

```bash
# The fpgas.online apt repository (bookworm or trixie).
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list

# fpgas.online's openFPGALoader; add it before installing. A NeTV2 on a Pi 5 needs it. Elsewhere Debian's own
# works from 0.13.0 on (trixie), but bookworm's (0.10.0) is too old: it cannot read the device DNA.
curl -fsSL https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg \
  | sudo tee /etc/apt/keyrings/fpgas.online-fpga-tools.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list

sudo apt update
sudo apt install fpgas-online-arty         # the package for your board: see the table
sudo apt install fpgas-online-arty-debug   # optional: fpgas-arty-debug, for when the check fails
```

Install **one** of these. They conflict, so a host is never set up for two boards by accident.

| Package | Installs |
|---|---|
| `fpgas-online-acorn` | everything to check a Sqrl Acorn CLE-215+ / CLE-101 (and LiteFury), and turns the boot check on for it |
| `fpgas-online-arty` | everything to check a Digilent Arty A7-35T, and turns the boot check on for it |
| `fpgas-online-netv2` | everything to check a Kosagi NeTV2 (XC7A35T or XC7A100T), and turns the boot check on for it |
| `fpgas-online-fomu` | everything to check a Fomu EVT, and turns the boot check on for it |
| `fpgas-online-tt-fpga` | everything to check a TT FPGA Demo Board, and turns the boot check on for it |
| `fpgas-online-all-boards` | everything to check any of the boards, and turns the boot check on for whichever is found |
| `fpgas-online-multi-board` | turns the boot check on for whichever board is found, of those whose `fpgas-online-<board>-tools` you also install |

* `fpgas-online-<board>-debug` adds `fpgas-<board>-debug` and the tools for the tests the boot check skips.
* Installing does not run the check. It runs at the next boot, or when you run it.
* The packages are `Architecture: all`: they install on Raspberry Pi OS and on an x86 machine alike. The NeTV2
  and the Acorn need a Pi's GPIO header; the Arty, Fomu and TT FPGA board need only USB.
* Versions are `0.0.postN` from `git describe` (for example `0.0.post771`). Each package depends on the others'
  exact version, so `sudo apt upgrade` moves them together.
* Each board's page lists what its packages pull in: [acorn](hardware/acorn.md#installing-the-acorn-packages),
  [arty-a7](hardware/arty-a7.md#installing-the-arty-packages), [netv2](hardware/netv2.md#installing-the-netv2-packages),
  [fomu-evt](hardware/fomu-evt.md#installing-the-fomu-packages), [tt-fpga](hardware/tt-fpga.md#installing-the-tt-fpga-packages).
* CI builds every package and checks its install rules in clean bookworm and trixie
  ([`collect-bitstreams.yml`](../.github/workflows/collect-bitstreams.yml),
  [`build_debs.py`](../packaging/debs/build_debs.py), [`install_test.sh`](../packaging/debs/install_test.sh)).

### Running it

```bash
sudo fpgas-verify                          # check this host's board, as the boot does
sudo fpgas-arty-verify                     # check the Arty, whatever this host is set up for
sudo fpgas-arty-verify --test ddr          # run one test; the JSON report goes to stdout
sudo fpgas-acorn-verify --test pcie-link --test flash   # only some tests (these two only read)
sudo fpgas-verify --update                 # after flashing or swapping a board on purpose
fpgas-verify --list                        # the installed boards, and which this host checks

sudo fpgas-verify --identify               # who the board is, as JSON (see "Identity and labels")
sudo fpgas-verify --label --out labels.pdf # this Pi's and its board's labels, made by rpi-hwid

sudo fpgas-arty-debug test ddr             # load the DDR design and run its test, all output live
sudo fpgas-acorn-debug identify            # the same as fpgas-acorn-verify --identify
```

* Run them with `sudo`; `--help`, `--list` and `fpgas-<board>-debug list` do not need it.
* Nothing is sent anywhere unless a file says `[verify] publish = on` (next to `fpga-board`, below). A host that
  only has the packages installed publishes nothing, at boot or by hand; its summary says so in one line
  (`not published: no file says ...`), and there is no error. The
  fpgas.online Pi root sets it in `/etc/fpgas-verify/fleet.ini`, so a fleet Pi tells its site how the check
  went; there, `--no-publish` is how a run by hand stays private. The transcripts below were taken on fleet
  Pis, which is why they carry it; each shows the line that says whether it was published.
* `--test` runs part of the check. It is never published, never recorded, and its report goes to stdout
  unless `--report` says otherwise.
* Only one command uses a board at a time. A second one prints
  `waiting for another user of the <board> to finish...` and waits. Looking for a NeTV2 drives its JTAG pins,
  so the check and `fpgas-netv2-debug detect` take its lock for that too, waiting as for the check, and let
  it go before the check takes it again.
* The locks are files: `/run/fpgas-online/<board>.lock`, and the Acorn's `/run/lock/fpgas-acorn.lock` (shared
  with `fpgas-acorn-flash`). The packages' `/usr/lib/tmpfiles.d/fpgas-online-*.conf` create them at boot,
  root-owned and 0644, so no other user can create one first. A lock file that cannot be opened is an error
  naming the file and its owner: remove it, or reboot.
* Which board a host checks is `[verify] fpga-board = <board>` or `auto`, in `*.ini` files: the board's
  package puts one in `/usr/share/fpgas-online/verify/mode.d/`; one in `/etc/fpgas-verify/` overrides it.
* `[verify] publish = on` in the same files makes the check tell the fleet how it went ([events](#events)). It
  is off unless a file says so; a value that is neither `on` nor `off`, or two files that disagree, is an
  error and nothing is sent. Accepted values are `on`, `yes`, `true`, `1` and `off`, `no`, `false`, `0`, as for `power-cycle-check`.
  Every report and summary says whether the run was published and why: `"publish": {"on": true,
  "configured_by": "/etc/fpgas-verify/fleet.ini"}` and `published to the fleet: ...`, or `"publish": {"on":
  false, "why": "..."}` and `not published: ...`. On a fleet Pi, `not published: no file ...` in
  `journalctl -b -u fpgas-verify` means the root lost its `fleet.ini`.
* `[verify] power-cycle-check = on` in the same files switches on the Acorn's [power-cycle
  check](#the-acorns-power-cycle-check-opt-in). It is off unless a file says so: the fpgas.online Pi root sets it
  in `/etc/fpgas-verify/`; elsewhere it stays off.
* Options for the boot run go in `FPGAS_VERIFY_ARGS` in `/etc/default/fpgas-verify`. The package installs that
  file with every line a comment (it is what `EnvironmentFile=` in `systemctl cat fpgas-verify` names), so
  the boot run is plain `fpgas-verify` until you edit it. It is a configuration file: an upgrade keeps your
  edit.
* From a checkout, without installing: `PYTHONPATH=verify/src python3 -m fpgas_online_verify --help`.

### Identity and labels

Two commands say who the board is, for [rpi-hwid](https://github.com/mithro/rpi-hwid)'s labels. Neither runs
the check, publishes anything or records any state.

| Command | Does |
|---|---|
| `fpgas-verify --identify` (also `--board B`, `fpgas-<board>-verify --identify`, `fpgas-acorn-debug identify`) | prints one identity document (JSON) for every board found |
| `fpgas-verify --label [--out F] [--list]` | reads the identity, then runs `rpi-hwid labels --this-host [--out F] [--list]` to make this Pi's and its board's labels |

`--identify`:

* The document and every field in it are described in [identity.md](identity.md). It is printed with sorted
  keys and an indent of 1.
* What it reads live:

  | Board | Read live |
  |---|---|
  | Acorn | the running build, device DNA and flash identity over BAR0 (the check's `pcie-bar0`), and the IDCODE and DNA over P1 JTAG (`jtag`) |
  | Arty | the JTAG IDCODE and the device DNA ([the device DNA](#the-device-dna)) |
  | NeTV2 | the JTAG IDCODE, from the scan that finds it, and the device DNA |
  | Fomu, TT FPGA | how the board was found (its USB serial) |

  A TT board's [Tiny Tapeout fields](identity.md#tiny-tapeout-fields) are not read live: they come from the
  boot report (see below).

* Nothing is loaded into a board and no flash is written. Some reads do change state on the way, and each
  is put back:
  * Acorn, BAR0: memory decoding is switched on in the board's PCI COMMAND register for the read and
    switched off again if it was off. If a kernel driver (litepcie) is bound to the board, it is unbound for
    the read and bound again afterwards. To read the flash's IDs (RDID and OTPR) and its SFDP header (Read
    SFDP), the SoC's SPI master registers and the flash's chip select are written. No other CSR of the SoC
    is written; `--identify` refuses any other write, so the SoC is never reset through `ctrl_reset`.
  * Acorn, P1 JTAG, and NeTV2: openFPGALoader (or openocd) drives the Pi's JTAG GPIOs. Their state is read
    with `pinctrl` first and put back afterwards; a pin that was an output goes back as an input. Without
    `pinctrl` neither the scan nor the DNA read is run.
  * A SIGTERM during the read (rpi-hwid sends one to a slow `--identify`, then SIGKILL) exits 143 after
    putting all of this back and letting go of the locks; a second SIGTERM meanwhile is ignored.
* Each board is read under its lock, as a check is. `--identify` waits at most 30 s for it; a board still in
  use then has its fields missing, for the reason `board busy`. A NeTV2 is also looked for under its lock,
  since finding it drives its JTAG pins; one that could not be looked for, its lock busy, is in the document
  all the same, with its fields missing for that reason, even when other boards were found (`--identify`
  then exits 1). `--identify` holds one board's lock at a time: the NeTV2's is let go after its scan and
  taken again for its read, so no two locks are ever taken in an order that could deadlock with rpi-hwid's
  (acorn < arty < netv2).
* A field only the boot check reads comes from the boot report, `/run/fpgas-online/verify.json`, when the
  board there is this one by a key no other board has: a TT board's `usb_serial`, the Arty's USB serial, the
  Acorn's PCI slot, or the device DNA. These are the Arty's and NeTV2's flash fields, which need a design
  loaded for openFPGALoader's SPI-over-JTAG bridge, and a TT board's Tiny Tapeout fields with
  `tinytapeout_note` or `tinytapeout_error`, which need the port `fpgas-tt.service` holds. Those fields are
  listed in the board's `from_report`. An IDCODE names a part, not a board, so a board known only by its
  IDCODE (a NeTV2 whose DNA could not be read) gets nothing from the report: the fields stay missing, for
  the reason
  `no board-unique match in the boot report`.
* The exit status is 0 when every board's identity is whole (no field missing, no `<field>_error`), 1
  otherwise. Each missing field is printed on stderr with why. The document is printed either way; readers
  use it and ignore the exit status.
* For an Arty or a NeTV2, `--identify` always exits 1 for now: their labels need the flash's unique ID
  (`flash_uid`), and neither the boot check nor `--identify` reads it yet (see [Not done yet](#not-done-yet)).
  Their IDCODE and device DNA, and any flash fields the boot report has for them, are still in the document.
* For a TT board, `--identify` exits 0 only when the boot report has the fields rpi-hwid's Tiny Tapeout label
  needs (`mcu`, `chip`, `demoboard`, `demoboard_version`, `sdk`, besides `usb_serial`). So it exits 1 when
  rpi-hwid was not installed at boot.

`--label`:

1. reads the identity, as `--identify` does;
2. releases every board's lock;
3. writes the document to `/run/fpgas-online/identity-<pid>.json`, a new file readable by root alone (it never
   writes over a file or through a link already there);
4. runs `rpi-hwid labels --this-host [--out F] [--list]` with `FPGAS_VERIFY_IDENTITY` set to that file;
5. deletes the file, whatever happened: an error, Ctrl-C, or a SIGTERM (which exits 143).

Its exit status is rpi-hwid's, or 128 + N when rpi-hwid was killed by signal N, as a shell reports it (137
for SIGKILL). It exits 2, saying why, when rpi-hwid is not installed or when the file cannot be written: run it
as root. `--list` (with `--label`) lists the labels rpi-hwid would make; `--out F` is where rpi-hwid writes
them. `--label` writes no report or state and publishes nothing, so `--report`, `--state` and `--no-publish`
are refused with it (exit 2).

Nesting: rpi-hwid gets the board's identity by running `fpgas-verify --identify`. So that the inner run never
waits on a lock the outer run holds, reads a board twice or starts rpi-hwid again, a run with
`FPGAS_VERIFY_IDENTITY` set (an empty value counts as not set):

| Mode | Does |
|---|---|
| `--identify` (and `fpgas-acorn-debug identify`) | checks that the file is an identity document with `identity_version` 1 and prints it unchanged, byte for byte. It takes no lock and runs no board code |
| a missing or bad file | an error (exit 1). It never falls back to reading the hardware |
| any other mode, `--label` included | refuses (exit 2) |

rpi-hwid is a soft dependency:

* fpgas-verify finds the `rpi-hwid` command on `PATH` and runs it. It never imports rpi-hwid's Python code.
* Without it, `--label` exits 2 and says how to install it: `sudo apt install python3-rpi-hwid`, or
  `uv tool install 'rpi-hwid[labels]'` (Python 3.11 or newer).
* The `fpgas-online-verify` deb lists `python3-rpi-hwid` in Suggests. The Python package has a `labels` extra
  (`fpgas-online-verify[labels]`).
* `--identify` does not need rpi-hwid.

### Reading the result

There is one result: **pass** or **fail**. A fail is named for its worst cause:

| Result | Pass or fail | Means |
|---|---|---|
| `pass` | pass | every test passed, and the board and its flash are the ones recorded |
| `changed` | fail | a different board, or a different flash, from the [recorded state](#the-report-and-the-recorded-state) |
| `fail` | fail | a test failed, or the board runs a design that is not ours (`unconverted: …` for an Acorn on SQRL's image) |
| `missing` | fail | no board found (with `auto`: none of the installed boards) |
| `error` | fail | the check itself could not run: a missing tool, a damaged package, no configuration |

* Only `pass` exits 0. Anything else also leaves `fpgas-verify.service` failed.
* The check goes on after a fault wherever it can, so the report lists every fault it found.
* The summary goes to stderr; at boot, to the journal (`journalctl -b -u fpgas-verify`). It has two parts:
  * every test in the order it ran, with its result, and a failed test's last 8 output lines;
  * for a check that did not pass, a plain conclusion, last, so it is what is left on the terminal:
    `RESULT:` and what it means; each board with how many tests passed, failed and were not run; a `fault:`
    line for each thing wrong that is no one test's (the board runs SQRL's image, say), a `failed:` line for
    each failed test with its reason, and a `not run:` line for the tests that did not run and why (a test that
    does not apply to the setup is `not run`, and is not a failure); then `What to do:`, chosen from the
    faults found; then where the JSON report is.
* A reason is always one line, however long, so it can be searched for as it is ([Common
  failures](#common-failures)).
* The JSON report is in `/run/fpgas-online/verify.json`. It is replaced whole (written beside itself and
  renamed), so a reader sees the old report or the new one, never part of one. A `--report` path that is a
  symlink, a device or a pipe is written through instead, not replaced.

**pass**: an Acorn on the Pi 5 setup (pi-sw2-p47, 2026-10-02T03:56:17Z; the summary its report gives):

```text
$ sudo fpgas-verify --no-publish
fpgas-verify: pass (mode auto, auto: USB/PCI IDs)
  not published: --no-publish
  acorn cle-215+: pass
    pcie-link  pass
    pcie-bar0  pass
    rp1-pio    pass
    jtag       pass
    flash      pass
    ddr        pass
    p2-uart    pass
    p2-serial  pass
    scratch    pass
    p2-gpio    pass
    flash 0x000000 match
    flash 0x400000 match
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json
```

**fail, a first install on someone's own hardware**: a Compute Blade with a CM5 and an Acorn CLE-101 still on
SQRL's factory image (ps1's `pi16`, 2026-10-05; the summary its boot report gives). Two things are wrong, and
neither is the installation: the card has not been converted, and on this setup the JTAG test cannot have its
TMS pin ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)).

```text
$ sudo fpgas-verify --no-publish

******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode acorn, configured: acorn)
  not published: --no-publish
  acorn cle-101: fail
    unconverted: runs SQRL's factory image, not the fpgas.online design
    pcie-link  pass
    rp1-pio    pass
    jtag       fail: P1 JTAG: openFPGALoader --detect failed (exit -6) before scanning the JTAG chain: openFPGALoader: line-request.c:199: gpiod_line_request_set_values_subset: Assertion `request' failed.
        openFPGALoader: line-request.c:199: gpiod_line_request_set_values_subset: Assertion `request' failed.
    pcie-bar0  not run: unconverted: runs SQRL's factory image, not the fpgas.online design
    flash      not run: unconverted: runs SQRL's factory image, not the fpgas.online design
    ddr        not run: unconverted: runs SQRL's factory image, not the fpgas.online design
    p2-uart    not run: the board does not run a known build
    p2-serial  not run: unconverted: runs SQRL's factory image, not the fpgas.online design
    scratch    not run: unconverted: runs SQRL's factory image, not the fpgas.online design
    p2-gpio    not run: J5 and H5 are not wired on the Compute Blade setup
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json

RESULT: FAIL: a board did not pass.
  acorn cle-101: fail (2 tests passed, 1 failed, 7 not run)
    fault: unconverted: runs SQRL's factory image, not the fpgas.online design
    failed: jtag: P1 JTAG: openFPGALoader --detect failed (exit -6) before scanning the JTAG chain: openFPGALoader: line-request.c:199: gpiod_line_request_set_values_subset: Assertion `request' failed.
    not run: pcie-bar0, flash, ddr, p2-serial, scratch: unconverted: runs SQRL's factory image, not the fpgas.online design
    not run: p2-uart: the board does not run a known build
    not run: p2-gpio: J5 and H5 are not wired on the Compute Blade setup
What to do:
  * The Acorn still runs the image it was sold with, not the fpgas.online one,
    so only its PCIe link and its JTAG could be tested. It has to be converted
    once (the fpgas.online image loaded over JTAG, then written to its flash
    with fpgas-acorn-flash):
    https://github.com/fpgas-online/fpgas.online-test-designs/blob/main/docs/hardware/acorn-pcie-programming.md
  * openFPGALoader could not have one of the JTAG pins, because a driver holds
    it (on a Compute Blade the serial port holds GPIO14, which is also the
    JTAG TMS wire). The check cannot test JTAG on such a host yet:
    https://github.com/fpgas-online/fpgas.online-test-designs/issues/127
  * To look at the acorn board yourself: sudo fpgas-acorn-debug --help (sudo
    apt install fpgas-online-acorn-debug)
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/fpgas-verify.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************
```

**fail, with two faults**: the check run against the tests' fake Acorn
([`tests/acorn_fakes.py`](../tests/acorn_fakes.py)), with its PCIe link at x2 and a JTAG TDI wire that does not carry:

```text
$ sudo fpgas-verify --no-publish

******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode auto, auto: USB/PCI IDs)
  not published: --no-publish
  acorn cle-215+: fail
    pcie-link  fail: link is x2, expected x1
    pcie-bar0  pass
    rp1-pio    pass
    jtag       fail: device DNA over JTAG 0x1 is not the one over BAR0 0x54b48664b04854: TDI (or the DNA readout) is wrong
        - 0 -> 0x13636093
        - 1 -> 0xffffffff
        {"dna": "0x0000000000000001"}
    flash      pass
    ddr        pass
    p2-uart    pass
    p2-serial  pass
    scratch    pass
    p2-gpio    pass
    flash 0x000000 match
    flash 0x400000 match
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json

RESULT: FAIL: a board did not pass.
  acorn cle-215+: fail (8 tests passed, 2 failed)
    failed: pcie-link: link is x2, expected x1
    failed: jtag: device DNA over JTAG 0x1 is not the one over BAR0 0x54b48664b04854: TDI (or the DNA readout) is wrong
What to do:
  * To look at the acorn board yourself: sudo fpgas-acorn-debug --help (sudo
    apt install fpgas-online-acorn-debug)
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/fpgas-verify.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************
```

**fail**: a NeTV2 whose DDR test fails (pi-sw1-p12, at boot; the summary its report gives):

```text
$ journalctl -b -u fpgas-verify -o cat
******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode auto, auto: probed (netv2))
  published to the fleet: `publish = on` in /etc/fpgas-verify/fleet.ini
  netv2 a7-35: fail
    uart       pass
    ddr        fail: the test exited 1
               Read: 0x40000000-0x401c0000 1.7MiB
               Read: 0x40000000-0x401e0000 1.8MiB
               Read: 0x40000000-0x40200000 2.0MiB
              bus errors:  256/256
              addr errors: 0/8192
              data errors: 524288/524288
              Memtest KO
            RESULT: FAIL — DDR memory test had failures
    spiflash   pass
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json

RESULT: FAIL: a board did not pass.
  netv2 a7-35: fail (2 tests passed, 1 failed)
    failed: ddr: the test exited 1
What to do:
  * To look at the netv2 board yourself: sudo fpgas-netv2-debug --help (sudo
    apt install fpgas-online-netv2-debug)
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/fpgas-verify.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************
```

**missing**: a host set up for an Arty, with none attached:

```text
$ sudo fpgas-verify --no-publish; echo "exit $?"

******************************************************************************
*** FPGA VERIFY: MISSING ***************************************************
fpgas-verify: missing (mode arty, -)
  no Digilent Arty A7 found: this host is set up for one, and nothing else is looked for
  not published: --no-publish

RESULT: MISSING: no board was found.
  no Digilent Arty A7 found: this host is set up for one, and nothing else is looked for
What to do:
  * Check the board's power and cables. `sudo fpgas-arty-debug detect` looks
    for it again without running the tests.
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/fpgas-verify.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************

exit 1
```

### `--help`

```text
$ fpgas-verify --help
usage: fpgas-verify [options]

Check this host's FPGA board and its wiring to this Pi.
Prints a summary to stderr and writes a JSON report.

options:
  -h, --help         show this help message and exit
  --list             list the installed boards and the configured one; with
                     --label, the labels rpi-hwid would make
  --board BOARD      check BOARD, ignoring the configuration
  --no-probe         never scan JTAG to find a board (auto only)
  --test TEST        run only TEST (repeatable); not published or recorded
  --update           accept a changed board or flash: record it
  --identify         print who the board is (an identity document, JSON) and
                     nothing else
  --label            make this host's labels with rpi-hwid (rpi-hwid labels
                     --this-host)
  --out FILE         with --label: where rpi-hwid writes the labels
  --variant VARIANT  use VARIANT's bitstreams, not the detected one
  --port PORT        the board's UART (default: the board's usual one)
  --images DIR       the bitstreams (default: installed)
  --state FILE       the recorded state
  --report FILE      the JSON report; '-' for stdout (the default with --test)
  --no-publish       send nothing to the fleet, even with publish = on

the result is pass (exit 0) or a fail named for its worst cause (exit 1):
  pass          every test passed, and the board and flash are as recorded
  changed       a different board or flash from the recorded one
  fail          a test failed, or the board runs a design that is not ours
  missing       no board found
  error         the check could not run (a missing tool or file)

files:
  /run/fpgas-online/verify.json            the report (--report)
  /var/lib/fpgas-online/verify-state.json  the recorded state (--state)
  /etc/fpgas-verify/*.ini                  fpga-board = BOARD or auto
                                           publish = on or off
                                           power-cycle-check = on or off
```

```text
$ fpgas-arty-verify --help
usage: fpgas-arty-verify [options]

Check this host's Digilent Arty A7 with the fpgas.online test designs.
Prints a summary to stderr and writes a JSON report.

options:
  -h, --help         show this help message and exit
  --test TEST        run only TEST (repeatable); not published or recorded
  --update           accept a changed board or flash: record it
  --identify         print who the board is (an identity document, JSON) and
                     nothing else
  --variant VARIANT  use VARIANT's bitstreams, not the detected one
  --port PORT        the board's UART (default: the board's usual one)
  --images DIR       the bitstreams (default: installed)
  --state FILE       the recorded state
  --report FILE      the JSON report; '-' for stdout (the default with --test)
  --no-publish       send nothing to the fleet, even with publish = on

tests in the boot check:
  uart ddr spiflash ethernet pin-id
tests only fpgas-arty-debug runs:
  pmod

the result is pass (exit 0) or a fail named for its worst cause (exit 1):
  pass          every test passed, and the board and flash are as recorded
  changed       a different board or flash from the recorded one
  fail          a test failed, or the board runs a design that is not ours
  missing       no board found
  error         the check could not run (a missing tool or file)

files:
  /run/fpgas-online/verify.json            the report (--report)
  /var/lib/fpgas-online/verify-state.json  the recorded state (--state)
  /etc/fpgas-verify/*.ini                  publish = on or off
```

```text
$ fpgas-arty-debug --help
usage: fpgas-arty-debug [options] COMMAND [TEST] [-- ARGS]

Run the Digilent Arty A7's check one step at a time, with all its output.
ARGS after -- go to the test's script.

options:
  -h, --help         show this help message and exit
  --port PORT        the board's UART (default: the board's usual one)
  --variant VARIANT  use VARIANT's bitstreams, not the detected one
  --images DIR       the bitstreams (default: installed)

commands:
  detect        find the board; exit 1 if it is not there
  list          list the tests and their bitstreams
  check         check the bitstreams' sha256s
  program TEST  load TEST's design and leave it running
  test TEST     load TEST's design and run its test

tests in the boot check:
  uart ddr spiflash ethernet pin-id
tests only fpgas-arty-debug runs:
  pmod

examples:
  sudo fpgas-arty-debug detect
  fpgas-arty-debug list
  sudo fpgas-arty-debug test uart
  sudo fpgas-arty-debug test pin-id -- --hat-port JA
```

```text
$ fpgas-acorn-verify --help
usage: fpgas-acorn-verify [options]

Check this host's Sqrl Acorn as it booted from its flash.
Prints a summary to stderr and writes a JSON report.

options:
  -h, --help     show this help message and exit
  --test TEST    run only TEST (repeatable); not published or recorded
  --update       accept a changed board or flash: record it
  --identify     print who the board is (an identity document, JSON) and
                 nothing else
  --images DIR   the bitstreams (default: installed)
  --state FILE   the recorded state
  --report FILE  the JSON report; '-' for stdout (the default with --test)
  --no-publish   send nothing to the fleet, even with publish = on

tests in the boot check:
  pcie-link pcie-bar0 rp1-pio jtag flash ddr p2-uart p2-serial scratch p2-gpio
in the boot check only with `power-cycle-check = on`:
  power-cycle

the result is pass (exit 0) or a fail named for its worst cause (exit 1):
  pass          every test passed, and the board and flash are as recorded
  changed       a different board or flash from the recorded one
  fail          a test failed, or the board runs a design that is not ours
  missing       no board found
  error         the check could not run (a missing tool or file)

files:
  /run/fpgas-online/verify.json            the report (--report)
  /var/lib/fpgas-online/verify-state.json  the recorded state (--state)
  /etc/fpgas-verify/*.ini                  publish = on or off
                                           power-cycle-check = on or off
```

```text
$ fpgas-acorn-debug --help
usage: fpgas-acorn-debug [options] COMMAND

Run the Sqrl Acorn's check one step at a time, with all its output.

options:
  -h, --help    show this help message and exit
  --images DIR  the bitstreams (default: installed)

commands:
  detect        find the board; exit 1 if it is not there
  identify      print who the board is (as fpgas-acorn-verify --identify)

examples:
  sudo fpgas-acorn-debug detect
  sudo fpgas-acorn-debug identify
```

```text
$ fpgas-acorn-flash --help
usage: fpgas-acorn-flash [options] COMMAND [FILE ADDR]

Read, check or write the Acorn's SPI flash, through the fpgas.online SoC
running on it. Prints RESULT: PASS or RESULT: FAIL last.

options:
  -h, --help   show this help message and exit
  --bdf BDF    the SoC's PCIe address (default: 0001:01:00.0)
  --uart PORT  use the UART bridge on PORT instead of PCIe

commands:
  id                print the flash's part, size, IDs and SFDP revision as JSON
  dump FILE         read the whole flash into FILE
  verify FILE ADDR  compare the flash at ADDR with FILE
  write FILE ADDR   write FILE at ADDR, then read it back (needs --idcode)

write takes a slot: 0x400000 (operational) or 0x0 (golden, which also
needs --i-know-this-writes-golden). Its --idcode is the FPGA's JTAG IDCODE:
0x03636093 (CLE-215+) or 0x03631093 (CLE-101).

examples:
  sudo fpgas-acorn-flash id
  sudo fpgas-acorn-flash dump backup.bin
  sudo fpgas-acorn-flash verify operational.bin 0x400000
  sudo fpgas-acorn-flash write operational.bin 0x400000 --idcode 0x03636093
```

### What each board's check tests

#### Arty, NeTV2, Fomu and TT FPGA

Each test checks its bitstream's sha256 against the `-bitstreams` package's manifest (a damaged file is an
`error`, never loaded), loads it, runs its host script, and passes when the script exits 0
([`testbench.py`](../verify/src/fpgas_online_verify/testbench.py)).

| Test | Host script | Passes when |
|---|---|---|
| `uart` | [`test_uart.py`](../designs/uart/host/test_uart.py) | the LiteX BIOS banner arrives (Arty only) and printable ASCII echoes back |
| `ddr` | [`test_ddr.py`](../designs/ddr-memory/host/test_ddr.py) | the BIOS reports DRAM calibration and `Memtest OK` |
| `spiflash` | [`test_spiflash.py`](../designs/spi-flash-id/host/test_spiflash.py) | the design reads the flash's JEDEC ID and prints `SPI_FLASH_TEST: PASS` |
| `ethernet` | [`test_ethernet.py`](../designs/ethernet-test/host/test_ethernet.py) | the design answers ARP and ping through the Pi's USB Ethernet adapter (192.168.1.100/24 on that adapter only) |
| `pin-id` | [`identify_pmod_pins.py`](../designs/pmod-pin-id/host/identify_pmod_pins.py) | every Pmod HAT GPIO receives the FPGA ball name the expected cabling puts there |
| `pmod` | [`test_pmod_loopback.py`](../designs/pmod-loopback/host/test_pmod_loopback.py) | the loopback wiring reads back; `-debug` only |

| Board | Found by | Loaded with | UART | Boot-check tests, in order | Only in `-debug` | Recorded state |
|---|---|---|---|---|---|---|
| Arty A7 | USB `0403:6010` | `openFPGALoader -b arty` | `/dev/ttyUSB1` | `uart`, `ddr`, `spiflash`, `ethernet`, `pin-id` | `pmod` | FTDI serial, IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's first 2.1 MiB |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22 | openocd (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `/dev/ttyAMA0` | `uart`, `ddr`, `spiflash` | `ethernet`, `pmod`, `pin-id` | IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's boot image |
| Fomu EVT | USB `1209:5bf0` (DFU bootloader) | openFPGALoader over DFU | `/dev/serial0` | `uart` | `spiflash`, `pmod`, `pin-id` | USB serial |
| TT FPGA | USB `2e8a:0005`, `2e8a:000f` (and `2e8a:0003`, the RP2's boot loader, which fails) | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | `sdk` (loads nothing), `pin-id`, `uart`; a board with a Tiny Tapeout chip: `sdk` only, and it fails until its wiring test exists | `pmod` | USB serial |

* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  others the last test design. Each returns to its flash image at its next power cycle.
* The Arty and NeTV2 have their whole JTAG IDCODE read and decoded before the tests
  ([the JTAG IDCODE](#the-jtag-idcode)): a part that is not the variant's fails the board. Then their device
  DNA is read over the same JTAG ([the device DNA](#the-device-dna)): one that cannot be read, or is all zeros
  or all ones, fails the board.
* The Fomu runs only `uart` at boot: a DFU load replaces the bootloader until the next power cycle.
* That test design has no USB, so a Fomu that has been checked is off USB until it is power-cycled, and the
  check of the next boot does not find it if that boot was a reboot (seen on a Pi 3B+ on 5 October 2026: the
  Fomu left USB 36 seconds into the boot, and the reboot after it reported `missing`). The result is still
  `missing`, since the board was not checked; when the recorded state has a Fomu, the reason says so: `a Fomu
  EVT was found on this host by an earlier check and is not there now: the check's own test design has no
  USB, …`. Power-cycle the Pi. ([#135](https://github.com/fpgas-online/fpgas.online-test-designs/issues/135))
* The TT FPGA's `fpgas-tt.service` is stopped for the tests and started again once the report is written, so
  it never starts against the report of the run before. If it cannot be started again the result is `error`
  and the report says so, in `services_failed` at the top of the report: the board's own entry keeps the
  result of its tests, and the state recorded for it stands, since the board itself was read. The service is
  started even when the check is interrupted or the report cannot be written. While it is stopped, and before the first test, rpi-hwid reads who the board is ([TT FPGA identity](#tt-fpga-identity)).
* The NeTV2 has no USB, so finding it means driving the GPIO header. With `fpga-board = auto` the JTAG scan
  runs only if nothing was found on USB or PCI (or only a Xilinx PCIe design the Acorn check cannot name);
  `--no-probe` turns it off.

#### Which Tiny Tapeout board it is

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

#### The `sdk` test

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

#### TT FPGA identity

The site makes [rpi-hwid](https://github.com/mithro/rpi-hwid)'s Tiny Tapeout label for a TT board from the
[Tiny Tapeout fields](identity.md#tiny-tapeout-fields) in its identity. Only rpi-hwid reads them: it asks the
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

#### Acorn

The Acorn check ([`suite.py`](../verify/src/fpgas_online_verify/boards/acorn/suite.py),
[`check.py`](../verify/src/fpgas_online_verify/boards/acorn/check.py),
[`links.py`](../verify/src/fpgas_online_verify/boards/acorn/links.py),
[`bist.py`](../verify/src/fpgas_online_verify/boards/acorn/bist.py)) tests the board as it booted from its
flash:

* It loads nothing, never writes the flash and never reconfigures the FPGA.
* It runs every test it can, in the order below; a fault in one does not stop the others.
* Nothing is sent to the BARs of a board whose PCI IDs are not ours.
* On ours, nothing past the identifier read is sent over BAR0 or the P2 UART unless that identifier is a build
  of the installed release. The CSR addresses then come from that build's `csr.json`; one that puts a CSR the
  check uses outside the 64 KiB of BAR0 it maps is an `error`.

**Which board it is**, from the PCI IDs alone:

| PCI IDs | Is | Result |
|---|---|---|
| `10ee:7021`, subsystem `1e24:021f` (CLE-215+) or `1e24:0101` (CLE-101) | the fpgas.online Acorn SoC | tested |
| `1e24:021f` or `1e24:0101` as vendor:device | an Acorn on SQRL's factory image | `fail`, `unconverted: …`; only `pcie-link`, `rp1-pio` and `jtag` run |
| `10ee:7011` | the vendor XDMA sample (an Acorn or a NeTV2) | `fail`, `unconverted: …` |
| `10ee:0666` | a PCIe Screamer running PCILeech | `fail`: fpgas.online has no test design for this board yet |
| `10ee:7021`, subsystem `10ee:0007`, class `070001`, with a BAR2 | a stock Xilinx XDMA design (most likely a PicoEVB) | `fail`: fpgas.online has no test design for this board yet |
| any other Xilinx or SQRL ID | not a design we built | `fail` |

**Which setup the host is.** The Acorn has two setups, each wired its own way:

| Host (`/proc/device-tree/model`) | Setup | JTAG `--pins` (TDI:TDO:TCK:TMS) | GPIO chip | J5 / H5 |
|---|---|---|---|---|
| `Raspberry Pi 5 Model B` | Pi 5 with the Waveshare HAT | `10:9:11:8` | `raspberrypi,rp1-gpio` | GPIO3 / GPIO4 |
| `Raspberry Pi Compute Module 4` | Compute Blade | `2:3:4:14` | `brcm,bcm2711-gpio` | not wired |
| `Raspberry Pi Compute Module 5` | Compute Blade | `2:3:4:14` | `raspberrypi,rp1-gpio` | not wired |

* Both use openFPGALoader's `libgpiod` cable, and the P2 UART is `/dev/ttyAMA0`.
* Any other host is an `error`; the tests that do not need the wiring still run.

**The expected data**, one copy each, in the repository and installed by `fpgas-online-acorn-tools`:

| File | Holds | In the repository | Installed |
|---|---|---|---|
| `wiring.toml` | each setup's wiring: which Pi GPIO each P1/P2 signal lands on, the JTAG cable and pins, the UART, and which hosts are that setup | [`docs/wiring/acorn/wiring.toml`](wiring/acorn/wiring.toml) | `/usr/lib/python3/dist-packages/fpgas_online_verify/boards/acorn/data/` |
| `expected.toml` | the figures the board must meet: PCIe link speed and width per setup, XADC ranges, and the least DRAM write and read bandwidth per variant | [`docs/wiring/acorn/expected.toml`](wiring/acorn/expected.toml) | the same |

From a checkout, the check reads them from the repository.

**The tests**, in the order they run:

| Test | Over | Passes when |
|---|---|---|
| `pcie-link` | sysfs | `current_link_speed` and `current_link_width` are the setup's (5.0 GT/s, x1) |
| `pcie-bar0` | BAR0 | the operational build runs (the golden build means the operational slot did not boot), the flash identifies itself and its SFDP header can be read (a flash with no SFDP passes), the device DNA is neither all zeros nor all ones, and the XADC temperature and VCCINT, VCCAUX and VCCBRAM are in range |
| `rp1-pio` | the Pi's kernel | Pi 5 / CM5 (BCM2712) only, not run elsewhere: `/dev/pio0` is a character device that opens read-write, which openfpgaloader-rp1pio needs. No bootloader or `config.txt` setting is read. When it does not, the test also says whether `rp1_fw` and `rp1_pio` are loaded, and the kernel's own `rp1-pio` / RP1 firmware lines say why, e.g. `failed to contact RP1 firmware` on a bootloader rp1_pio cannot talk to (pi-sw2-p47 and p48, bootloader 2024/11/05, 2026-10-03) |
| `jtag` | P1 | `openFPGALoader --detect` finds one device, the variant's part in any silicon version ([the JTAG IDCODE](#the-jtag-idcode)), and `openFPGALoader --read-dna` reads a device DNA that is neither all zeros nor all ones. When BAR0's DNA is good, the two must match; otherwise the JTAG DNA is not compared. The IDCODE read does not use TDI; the DNA read does |
| `flash` | BAR0 | both 4 MiB slots (golden at `0x000000`, operational at `0x400000`), read whole with read opcodes only, hold the release's images |
| `ddr` | BAR0 | after the BIOS console is read out, the DRAM BIST makes two passes over the whole DRAM: no errors, and write and read bandwidth at least the variant's minimum |
| `p2-uart` | P2 | the UARTBone identifier at 1200 baud is BAR0's; at 921600 baud the identifier, DNA and XADC readings are right and the DNA is BAR0's. The link is left at 1200 baud |
| `p2-serial` | BAR0 and the Pi's GPIO | J2/K2, borrowed from the UART by the `p2_serial` switch, carry 0 and 1 both ways; the switch goes back to serial by itself; the UARTBone then answers with BAR0's identifier |
| `scratch` | BAR0 and P2 | the `ctrl` scratch register holds two patterns written over each bridge; its value is put back |
| `p2-gpio` | BAR0 and the Pi's GPIO | Pi 5 setup only: J5/H5 carry 0 and 1 both ways, FPGA to Pi and Pi to FPGA |
| `power-cycle` (opt-in, after `pcie-bar0`) | BAR0 | the FPGA restarted since the last check: see below |

#### The Acorn's power-cycle check (opt-in)

A board is to be tested as its flash configures it. If the FPGA kept its configuration while its Pi restarted
(the card fed from somewhere else, a restart that does not reach the card), it still holds whatever was in it
before, a visitor's design included. With `power-cycle-check = on` the board fails in that case:

```text
power-cycle fail: the FPGA has not restarted since an earlier boot's check (scratch is 0x…, neither its
value after configuration nor this boot's marker): it did not restart with the Pi. Power-cycle the Pi
```

How it tells, on the SoC the boards run (it has no uptime counter): the `ctrl` scratch register holds
`0x12345678` after configuration and only a write changes it. When the `power-cycle` test has passed, the check
ends by leaving a marker there, 32 bits of a hash of the kernel's boot id. At the next check:

| Scratch holds | Means | Result |
|---|---|---|
| `0x12345678` | the FPGA was configured, or its SoC reset, since the last check | pass |
| this boot's marker | the check already ran in this boot (an operator running it again) | pass |
| anything else | the card kept its configuration across the Pi's restart, or something else wrote the register | fail |

A board that fails is left as it was found, so it fails again until the card restarts (a power cycle does it).
`--test scratch` on its own leaves no marker; `--test power-cycle`, when it passes, does leave it. The report says when the check was on: `"power_cycle_check": {"on": true, "configured_by":
"/etc/fpgas-verify/…ini"}`.

**What a restart of the Pi does to the card depends on the setup, so the check is opt-in.** Measured on
5 Oct 2026 on a Pi 5 with the PCIe HAT (the Acorn with DNA `0x0054b48664b04854`): after a plain `systemctl
reboot` the scratch register read `0x12345678` again and the check passed, and the same after a PoE power cycle.
That is one board; whether the soft reboot reloads the FPGA from its flash or only resets the SoC was not
established, and the Compute Module setup has not been measured. Where a restart of the Pi does not reach the
card, every board fails after a restart, so switch the check on only for a setup that has been measured. Outside the fleet nothing says how a host is restarted, which is why it is off by default.

Two limits. A reset of the SoC (a write to `ctrl_reset`) also returns the register to `0x12345678`, and the
check cannot tell that from configuration. And anyone with root on the Pi can write the register; the check is
there to catch a card that did not restart with its Pi, not a visitor who sets out to hide it.

`fpgas-verify --test power-cycle` runs it alone, when the setting is on; with the setting off it is an error
that says how to switch it on.

* `ddr` in detail ([`bist.py`](../verify/src/fpgas_online_verify/boards/acorn/bist.py), the same code
  [`selftest.py`](../designs/acorn-pcie/host/selftest.py) runs):
  1. The BIOS console is read until it has been quiet for 2 s. In the installed release
     (`vivado-bitstreams-acorn-pcie-20261001-ge568a408e7bd`, built from e568a40, which does not have
     [#47](https://github.com/fpgas-online/fpgas.online-test-designs/pull/47)) the BIOS stops while its
     console is full and unread, so reading it lets it finish setting up the DRAM. A build with #47 never
     waits for a reader. The BIOS's memtest line, when still there, is reported as `bios_memtest`.
  2. Two passes over the whole DRAM, in a low and a high half, each written before either is checked, with
     different data in each; the second pass swaps them. A dead top address bit, or half the expected DRAM,
     fails.
  3. Measurements: `bytes`, `passes`, `errors`, `write_MBps`, `read_MBps`, `seconds`.
* The golden image has no DRAM, no P2 switch and no spare GPIO: on it `ddr`, `p2-serial` and `p2-gpio` are
  in `not_run`, and the board fails for running golden.
* A test that cannot run because of an earlier fault is in the report's `not_run`, with why.
* A run in which none of the tests asked for ran (`--test p2-gpio` on a Compute Blade, say) fails.
* A kernel driver bound to the board (`litepcie.ko`) is unbound while a test that uses BAR0 runs, and bound
  again after. The events of those tests are held and sent once it is bound again.
* Every Pi pin a test drives is put back as it was found (function, pull, and an output's level); the FPGA's
  side is left as inputs. On a Compute Blade GPIO14 is both TMS and the UART's TX, and goes back to its UART
  function.
* Before the JTAG tool runs, the check asks the header's GPIO chip whether each JTAG pin can be had. A kernel
  whose pin controller is strict (the RP1's on 6.18, seen on a CM5) does not lend a pin a driver has: on a
  Compute Blade with the serial port on, that is GPIO14. The tool is then not run and `jtag` fails, naming the
  pin and who has it ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)). Which
  boot configuration a Compute Blade needs for both JTAG and the P2 UART is not settled.

#### The JTAG IDCODE

Every board with JTAG has its FPGA's whole 32-bit IDCODE read and decoded
([`idcode.py`](../verify/src/fpgas_online_verify/idcode.py)):

| Board | Read with | Must be | In the report |
|---|---|---|---|
| Acorn | `openFPGALoader --cable libgpiod --pins <setup's> --detect --verbose-level 2` over P1 | CLE-215+ and CLE-215: XC7A200T; CLE-101: XC7A100T | the `jtag` test |
| Arty A7 | `openFPGALoader -b arty --detect --verbose-level 2` over its FT2232H | XC7A35T | the board's `jtag` |
| NeTV2 | the scan that finds it: OpenOCD (Pi 3/4) or `openFPGALoader -c rp1pio ... --detect --verbose-level 2` (Pi 5) | the variant's part: XC7A35T or XC7A100T | the board's `jtag` |

* The Fomu EVT and TT FPGA have no JTAG.
* Plain `openFPGALoader --detect` prints the IDCODE its part table holds, which for these parts has the
  version masked off (`idcode 0x3636093` for an XC7A200T that answers `0x13636093`). Its raw scan, printed at
  `--verbose-level 2` as `- 0 -> 0x13636093`, is the whole value; OpenOCD's `tap/device found:` is too.
* Reading the IDCODE only shifts the data register after a TAP reset: it never reconfigures the FPGA. The
  check holds the board's lock throughout (the Acorn's is `/run/lock/fpgas-acorn.lock`, shared with
  `fpgas-acorn-flash`), and on the Acorn the JTAG pins are put back as they were found.
* The part is compared without the version, so another silicon revision of the right part passes. A part
  that is not the variant's fails the board, and so does an IDCODE with bit 0 clear.
* A JTAG chain of more than one device fails the board, with every IDCODE on it in the reason. That holds for
  the NeTV2 too: finding it picks its part out of the chain, but the check counts every device the scan saw.
* A scan whose tool exits with an error fails, even when it printed the right IDCODE; the reason gives the
  exit code. The IDCODE it printed is still decoded in the report.

| Field | Bits | Example (pi-sw2-p48's Acorn CLE-215+) |
|---|---|---|
| `idcode` | 31:0, 8 hex digits | `0x13636093` |
| `idcode_version` | 31:28, the silicon revision | `1` |
| `idcode_part_number` | 27:12 | `0x3636` |
| `idcode_manufacturer_id` | 11:1, the JEP106 code (bank in 11:8) | `0x049` |
| `idcode_manufacturer` | the JEP106 code's name | `Xilinx` |
| `idcode_device` | the IDCODE without its version, from the table below (`unknown` if not in it) | `XC7A200T` |

| IDCODE, version 0 | Device |
|---|---|
| `0x0362e093` | XC7A15T |
| `0x0362d093` | XC7A35T |
| `0x0362c093` | XC7A50T |
| `0x03632093` | XC7A75T |
| `0x03631093` | XC7A100T |
| `0x03636093` | XC7A200T |

pi-sw2-p48 (Acorn CLE-215+, Pi 5 setup), read holding the Acorn lock, 2026-10-02:

```text
$ sudo openFPGALoader --cable libgpiod --pins 10:9:11:8 --detect --verbose-level 2
libgpiod jtag bitbang driver, dev=/dev/gpiochip0, tck_pin=11, tms_pin=8, tdi_pin=10, tdo_pin=9
Raw IDCODE:
- 0 -> 0x13636093
- 1 -> 0xffffffff
Fetched TDI, end-of-chain
found 1 devices
index 0:
	idcode 0x3636093
	manufacturer xilinx
	family artix a7 200t
	model  xc7a200
	irlength 6
```

Its `jtag` test entry:

```json
{"test": "jtag", "idcode": "0x13636093", "idcode_version": 1, "idcode_part_number": "0x3636",
 "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A200T",
 "dna": "0x54b48664b04854",
 "output": ["- 0 -> 0x13636093", "- 1 -> 0xffffffff", "{\"dna\": \"0x0054b48664b04854\"}"], "result": "pass"}
```

#### The device DNA

The Acorn, Arty and NeTV2 have their FPGA's device DNA read: a 57-bit number fused into each chip, different on
every one ([`dna.py`](../verify/src/fpgas_online_verify/dna.py)).

| Board | Read with | In the report |
|---|---|---|
| Acorn | over BAR0, and `openFPGALoader --cable libgpiod --pins <setup's> --read-dna` over P1 | the `pcie-bar0` and `jtag` tests |
| Arty A7 | `openFPGALoader -b arty --read-dna` over its FT2232H | the board's `jtag` |
| NeTV2, Pi 5 | `openFPGALoader -c rp1pio --pins 27:22:4:17 --read-dna` | the board's `jtag` |
| NeTV2, Pi 3/4 | `openFPGALoader --cable libgpiod --pins 27:22:4:17 --read-dna` (the flash readback's cable; the scan that finds the board is OpenOCD's) | the board's `jtag` |

* The JTAG read runs only once the IDCODE scan has found the one FPGA expected. Otherwise it is not run, the
  scan's fault is the reason, and `dna_error` says the DNA was not read.
* `--read-dna` resets the TAP, shifts in the FUSE_DNA instruction (`0x32`) and shifts out 64 bits. It loads
  nothing and never reconfigures the FPGA, so `--identify` reads it too. The board's lock is held throughout;
  on the NeTV2 the JTAG pins are put back with `pinctrl` as after its scan.
* The FUSE_DNA instruction goes in through TDI and the DNA comes out on TDO, so a good DNA also shows TDI
  works; the IDCODE scan does not use TDI.
* A read that exits with an error or prints no DNA fails the board; the reason ends with its last line of
  output. A DNA of all zeros or all ones fails it too: the DNA port is not being read.
* A good DNA is `dna` in the `jtag` entry, the [identity](identity.md) and the recorded state, as 16 hex digits
  (`0x0054b48664b04854`). Otherwise the identity has `dna_error`, with why.

openFPGALoader has `--read-dna` from 0.13.0:

| openFPGALoader | `--read-dna` |
|---|---|
| Debian bookworm's (0.10.0) | no, so the board packages need 0.13.0 or later: on bookworm, fpgas.online's |
| 0.13.0 and later, and fpgas.online's `openfpgaloader-fpgasonline` (1.1.1) and `openfpgaloader-fpgasonline-git` | yes, over any JTAG cable: the read is in openFPGALoader's Xilinx code (`Xilinx::fuse_dna_read` in `src/xilinx.cpp`), after the cable is open. That covers `-b arty` (its `digilent` FT2232 cable), `libgpiod`, and `rp1pio` (fpgas.online's builds only) |

#### Not done yet

What [verify-goals.md](verify-goals.md) asks for that the check does not do yet:

* The Arty, NeTV2, Fomu and TT FPGA are checked with the single-function test designs, loaded one at a time,
  not with the full test design.
* `pin-id` checks each Pmod pin in one direction only, FPGA to Pi.
* The Acorn's PCIe transfer rate is not measured, nor the Arty's and NeTV2's DDR and Ethernet bandwidth:
  their `ddr` and `ethernet` tests pass or fail only.
* The Arty's and NeTV2's flash is fingerprinted (a sha256 of its boot image region) and compared only with the
  last run's, not checked against a golden full test design.
* Only the Acorn's flash can be written with its golden images (`fpgas-acorn-flash write`).
* The Arty's and NeTV2's flash IDs are not read, nor the flash IDs of the TT and Fomu; their
  [identity](identity.md) has only what finding the board, its IDCODE and its device DNA give, and on the
  TT FPGA what rpi-hwid reads.
* Nothing is compared with the site's records.
* rpi-hwid refuses the Arty's and NeTV2's labels until their flash IDs are read; `--identify` exits 1 for
  them meanwhile.

### Checking an Acorn's wiring

The Acorn's check doubles as a wiring test: each of its tests uses a known set of wires between the card and
the Pi, so which tests pass and what a failing one says point at the wire. The wiring itself (which wire goes
to which pin, and the parts) is on the [Acorn wiring page](https://docs.fpgas.online/en/latest/boards/acorn/wiring.html),
generated from [`docs/wiring/acorn/wiring.toml`](wiring/acorn/wiring.toml); the parts to have on the bench, as a
list to tick off, are generated from the same table for a
[Raspberry Pi 5](wiring/acorn/generated/acorn-pi5-bom.md) and for a
[Compute Blade](wiring/acorn/generated/acorn-blade-bom.md).

#### After a fresh boot

On a host whose root file system is in memory (a netbooted Pi with `overlayroot=tmpfs`, as the Compute Blades
at ps1 are), what you install is gone at the next boot, and so is the boot check's unit. After each boot,
install and run by hand:

```bash
# 1. The two apt repositories the packages come from.
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
curl -fsSL https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg \
  | sudo tee /etc/apt/keyrings/fpgas.online-fpga-tools.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list

# 2. The Acorn's packages.
sudo apt update
sudo apt install fpgas-online-acorn

# 3. What is installed, and which board this host is set up to check.
fpgas-verify --list

# 4. The check. Nothing is sent anywhere unless a file on the host says `publish = on`; --no-publish makes sure.
sudo fpgas-acorn-verify --no-publish
```

* The check never writes the card's flash and never loads a design into the FPGA. It does drive the P1 and P2
  wires, which is how it tests them, and puts the Pi's pins back as it found them; on a converted card it
  writes the design's scratch register and puts the old value back (with the opt-in power-cycle check on, it
  leaves a marker there); and it records what it found on this host
  (`/var/lib/fpgas-online/verify-state.json`).
* It exits 0 only for a pass. The summary is on the terminal; the same as JSON is in
  `/run/fpgas-online/verify.json`.
* To keep the packages across boots, they have to go into the image the host boots from; that is the host
  owner's root image, not something these packages do.
* The check needs no bitstream file of yours. The images it compares the card's flash with, and the design
  that converts a card, are installed with it by `fpgas-online-acorn-bitstreams`, in
  `/usr/share/fpgas-online/acorn-pcie/images/` (for a CLE-101: `acorn-cle-101-sqrl_acorn.bit` and the two
  flash images, [converting a card](hardware/acorn-pcie-programming.md)). No package installs a pin-id or
  loopback design for the Acorn; the check does not use one.

#### Which test uses which wire

| Test | Wires it uses | A pass shows | Runs on a card still on SQRL's image |
|---|---|---|---|
| `pcie-link` | the M.2 slot | the card is seated and the PCIe link is at the setup's speed and width | yes |
| `jtag` | P1: TCK, TMS, TDO for the IDCODE read; TDI as well for the device DNA read | all four JTAG wires, and that the FPGA is the variant's part | yes |
| `pcie-bar0` | the M.2 slot | the fpgas.online design is running and answers over PCIe | no: the board gets `fault: unconverted: …`; this test, `p2-uart`, `p2-serial`, `p2-gpio`, `flash`, `ddr` and `scratch` are listed as `not run` (`pcie-link`, `jtag` and `rp1-pio` still run) |
| `p2-uart` | P2: K2 (FPGA transmit) to the Pi's RXD (GPIO15), J2 (FPGA receive) from the Pi's TXD (GPIO14) | the serial pair, in the right direction | no |
| `p2-serial` | the same two wires, driven and read as plain pins in both directions | each of J2 and K2 on its own, so a crossed pair or one open wire is told apart | no |
| `p2-gpio` | P2: J5 to GPIO3, H5 to GPIO4, in both directions | the two spare wires | no; and never on a Compute Blade, whose cable does not carry them |
| `rp1-pio` | no wire: `/dev/pio0` on a Pi 5 or CM5 | nothing about the wiring (not run on other hosts) | yes |
| `flash`, `ddr`, `scratch` | no wire of the cable (`scratch` also uses the serial pair) | nothing about the wiring | no |

So on a card that has not been converted yet, `pcie-link` and `jtag` are the wiring tests; the P2 wires can
only be tested once the card runs the fpgas.online design
([converting a card](hardware/acorn-pcie-programming.md)).

#### From what it says to the wire

| The failing line | Look at |
|---|---|
| `pcie-link fail: link is x2, expected x1` (or a speed) | the M.2 seat; or the setup's expected figures are not this host's |
| `jtag fail: no device on the P1 JTAG chain` | the P1 cable is not plugged in, or TCK, TMS or TDO is open or on the wrong pin |
| `jtag fail: P1 JTAG chain has …, expected one …` | another device answers, or the card is not the variant the host expects |
| `jtag fail: device DNA over P1 JTAG reads 0x0: the DNA port is not being read` (or `reads 0x1ffffffffffffff`), `openFPGALoader --read-dna read no device DNA over P1 JTAG`, or `device DNA over JTAG … is not the one over BAR0 …` | TDI: the IDCODE read worked without it |
| `jtag fail: … GPIO14 (TMS) is held by … (uart0): the kernel does not hand out a pin that is held …` | not a wire: on a Compute Blade the serial port has the TMS pin ([below](#on-a-compute-blade)) |
| `p2-uart fail: no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)` | the serial pair: open, or crossed; `p2-serial` says which |
| `p2-serial fail: J2 -> GPIO14: the FPGA drove 1, the Pi read 0; K2 -> GPIO15: the FPGA drove 0, the Pi read 1; …` with the `01` and `10` lines swapped and `00` and `11` right | J2 and K2 are **crossed**: swap the two wires at the Pi end (on a Compute Blade the J2 wire carries the 470 Ω resistor: the resistor stays with J2) |
| `p2-serial` or `p2-gpio` naming one ball only | that one wire is **open**, or on the wrong pin. Before the FPGA drives, the test sets the Pi's pull against the level to come, so an open wire reads the opposite of what was driven; GPIO3 (the Pi 5's J5) has a pull-up of its own on the Pi, so an open J5 wire reads 1 whatever is driven |
| `p2-gpio fail: J5 -> GPIO3: …; H5 -> GPIO4: …` with the `01` and `10` lines swapped and `00` and `11` right | J5 and H5 are crossed |

`p2-serial` and `p2-gpio` print what was driven and what was read, eight lines for two wires. The two digits
are the two balls: the right-hand digit is J2 (or J5), the left-hand one K2 (or H5).

**A crossed pair**: read on acorn-olive at Welland, 4 October 2026, whose P2 pairs were both crossed. `FPGA drives
01` raises J2, which should arrive on GPIO14; it arrives on GPIO15:

```text
    p2-serial  fail: J2 -> GPIO14: the FPGA drove 1, the Pi read 0; K2 -> GPIO15: the FPGA drove 0, the Pi read 1; J2 -> GPIO14: the FPGA drove 0, the Pi read 1; K2 -> GPIO15: the FPGA drove 1, the Pi read 0; GPIO14 -> J2: the Pi drove 1, the FPGA read 0; GPIO15 -> K2: the Pi drove 0, the FPGA read 1; GPIO14 -> J2: the Pi drove 0, the FPGA read 1; GPIO15 -> K2: the Pi drove 1, the FPGA read 0; the UARTBone does not answer on /dev/ttyAMA0 after the switch (no fpgas.online SoC answered at 1200 baud after a break)
        FPGA drives 00: Pi reads GPIO14=0 GPIO15=0
        FPGA drives 01: Pi reads GPIO14=0 GPIO15=1
        FPGA drives 10: Pi reads GPIO14=1 GPIO15=0
        FPGA drives 11: Pi reads GPIO14=1 GPIO15=1
        Pi drives 00: FPGA reads 00
        Pi drives 01: FPGA reads 10
        Pi drives 10: FPGA reads 01
        Pi drives 11: FPGA reads 11
```

**One open wire**: read on acorn-sycamore at Welland the same day, whose J5 wire did not reach GPIO3. GPIO3
reads 1 whatever the FPGA drives (the Pi's own pull-up on GPIO3 wins over the test's pull-down; on GPIO4 an
open wire would read the opposite of what was driven), and on this card the FPGA read J5 as 1 whatever the Pi
drove; H5 and GPIO4 follow each other:

```text
    p2-gpio    fail: J5 -> GPIO3: the FPGA drove 0, the Pi read 1; J5 -> GPIO3: the FPGA drove 0, the Pi read 1; GPIO3 -> J5: the Pi drove 0, the FPGA read 1; GPIO3 -> J5: the Pi drove 0, the FPGA read 1
        FPGA drives 00: Pi reads GPIO3=1 GPIO4=0
        FPGA drives 01: Pi reads GPIO3=1 GPIO4=0
        FPGA drives 10: Pi reads GPIO3=1 GPIO4=1
        FPGA drives 11: Pi reads GPIO3=1 GPIO4=1
        Pi drives 00: FPGA reads 01
        Pi drives 01: FPGA reads 01
        Pi drives 10: FPGA reads 11
        Pi drives 11: FPGA reads 11
```

A correctly wired pair reads back what was driven: `FPGA drives 01: Pi reads GPIO14=1 GPIO15=0`, `Pi drives 01:
FPGA reads 01`, and so on for every pattern.

#### On a Compute Blade

What has been run on a Compute Blade, and what has not, as of 5 October 2026:

| | State |
|---|---|
| Installing the packages and running the check (Raspberry Pi OS trixie, CM5) | run at ps1: the first failing example under [Reading the result](#reading-the-result) is that host's result, taken with 0.0.post1100, before the check named the pin's holder |
| `pcie-link` | run at ps1: passes (5.0 GT/s, x1) |
| `jtag` with the serial port on, kernel 6.18 | run at ps1: **cannot work**. TMS is GPIO14, which is also the serial port's TX; that kernel does not lend a pin a driver has, and the serial driver cannot be detached while the system runs. From 0.0.post1111 the test fails saying so, without running the tool ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)) |
| `jtag` with the serial port off | **not yet run by us on this hardware** |
| `jtag` under kernel 6.12, serial port on | recorded as working on one ps1 blade (`--pins 2:3:4:14`), before these packages existed; not run with them |
| The `p2-uart` and `p2-serial` tests | **not yet run by us on this hardware**: they need a converted card |
| Converting a card on a Compute Blade | **not yet run by us on this hardware**; the [written steps](hardware/acorn-pcie-programming.md) are for the Pi 5 setup |
| A Compute Blade that passes the whole check | **not yet seen** |
| The `p2-serial` test on a blade whose J2 wire has no 470 Ω resistor (pi20 as wired on 5 October 2026: the pair on Extension Port pins 9 and 10) | **not yet run by us on this hardware**. From the code: while it runs to its end or raises an error, the test never has both ends of a wire driving at once (the Pi's pins are made inputs before the FPGA drives, and the FPGA's outputs are switched off before the Pi drives), so it does not rely on the resistor. What the resistor guards against is a design that drives J2 while JTAG or the serial port drives GPIO14; the fpgas.online design leaves J2 an input except while the host has switched J2/K2 to GPIO mode and enabled J2's output, which is what this test does, with the Pi's GPIO14 an input at that moment |

JTAG and the serial pair share GPIO14 on a Compute Blade (J2 reaches it through 470 Ω, so JTAG wins
electrically). Under kernel 6.18 they cannot both be had from one boot: with the header's serial port on, the
kernel keeps GPIO14 for it. The configuration we expect to work for JTAG, and with it for converting a card,
is the header's serial port off at boot. **Not yet run by us on this hardware**, and Raspberry Pi's
documentation does not say that it frees GPIO14 on a Compute Module 5:

* in `config.txt`, the line `enable_uart=0`, written out (Raspberry Pi's documentation gives the default as 1
  when the primary serial port is a PL011; we have not seen it left unset on a Compute Blade); and if the
  port is switched on by a `dtoverlay=uart0…` or `dtparam=uart0` line, that line has to go instead;
* in `cmdline.txt`, the word `console=serial0,115200` deleted from the one line, if it is there.

On a netbooted host those files may not be on the host: where the firmware reads `config.txt` and
`cmdline.txt` from is not something we have read, and if it fetches them from a boot server, they are changed
there, by whoever keeps that server, for every host booting from that tree. At ps1 the blades' root is the
gateway's `/srv/nfs/rpi/trixie/root` (read from the kernel command line of pi16 and pi20, 5 October 2026);
where the firmware's copies come from was not read by us.

Then check that the pin is free (the two commands below) before trying JTAG. With the serial port off, `/dev/ttyAMA0` is not there, so the
`p2-uart`, `p2-serial` and `scratch` tests cannot pass in that boot; what a Compute Blade's check should
count as its result in each of the two configurations is not settled.

To see who has the JTAG pins on a host, without running anything on the card:

```bash
pinctrl get 2,3,4,14,15     # the function each pin is switched to
gpiodetect                  # the header's chip: `pinctrl-rp1` on a CM5, `pinctrl-bcm2711` on a CM4
gpioinfo -c gpiochip0 | grep -E 'line +(2|3|4|14):'   # with that chip's name (gpiod 2; gpiod 1: `gpioinfo gpiochip0`)
# a line shown with a consumer (`consumer="kernel"`) or `[used]` is one the kernel will not hand out
```

### Common failures

| It says | Meaning, and what to do |
|---|---|
| `missing`: `no <board> found: this host is set up for one…` | the board is not on USB/PCI (or JTAG). Check power and cables. A Fomu that has run a design needs a power cycle |
| `missing`: `…; a Fomu EVT was found on this host by an earlier check and is not there now: …` | the Fomu may still be plugged in and working: the last check that found it loaded its test design, which has no USB, and a reboot does not bring it back. If it is plugged in, power-cycle the Pi (its power or its PoE port), not a reboot. The check cannot tell this from a Fomu that was unplugged |
| `missing`: `none of the installed boards … was found` | nothing attached. Expected on a Pi with no FPGA, and still a fail |
| `error`: `the board did not say which Tiny Tapeout board it is, so no test was run and nothing was loaded` | the demo board could not be asked: the rest of the reason says why (rpi-hwid not installed, its `main.py` changed, its SDK did not start, rpi-hwid could not read it). [Which Tiny Tapeout board it is](#which-tiny-tapeout-board-it-is) |
| `fail`: `wiring not run: the Pmod wiring test is not yet part of the boot check, …` | a demo board with a Tiny Tapeout chip. Nothing is known to be wrong with it: the check cannot test its cabling to the Pi yet, and does not pass a board untested. Its `sdk` test and identity are in the report. [The `sdk` test](#the-sdk-test) |
| `fail`: `sdk fail: a tt06 chip needs SDK 2.0.x on an RP2040, and the board runs SDK …` / `no SDK release is recorded as supporting …` | the Tiny Tapeout SDK on the demo board is not a release known to work with the chip it carries. The firmware is installed by whoever looks after the board; the check writes nothing to it. [The `sdk` test](#the-sdk-test) |
| `fail`: `a Raspberry Pi RP2 is on USB but is not running the Tiny Tapeout firmware` | the demo board's microcontroller is in its USB boot loader: power-cycle the board; if it comes back the same, its firmware is gone |
| `error`: `… is not installed` | a tool is missing: `mpremote` (bookworm: bookworm-backports), openocd, openFPGALoader |
| `error`: `no FPGA board is configured` / `conflicting fpga-board settings` | install one board's package, or fix `/etc/fpgas-verify/*.ini` |
| `fail`: `power-cycle fail: the FPGA has not restarted since an earlier boot's check` | the Acorn kept its configuration across the Pi's restart (not seen after a soft reboot on the one Pi 5 measured): power-cycle the Pi (PoE). [The power-cycle check](#the-acorns-power-cycle-check-opt-in) |
| `error`: `power-cycle-check is '…'; it is on or off` / `conflicting power-cycle-check settings` | fix `/etc/fpgas-verify/*.ini` |
| `error`: `… does not match its manifest` / `manifest.json is missing` | `sudo apt install --reinstall fpgas-online-<board>-bitstreams` |
| `fail`: `loading it failed (exit N)` | the programmer could not load the design: JTAG wiring, cable, or programmer support |
| `fail`: `python3 did not finish within 300 s` | the design never printed what the test waits for: wrong UART, or the design does not run |
| `fail`: `the test exited 1` | the test failed; its last lines are in the summary. `fpgas-<board>-debug test <test>` shows all of it |
| `fail`: `N/18 pins match expected wiring` | the Pmod HAT cabling differs from the board's expected map |
| `fail`: `… is an XC7A100T, not the a7-35's XC7A35T …` / `P1 JTAG chain has … expected one …` | the JTAG IDCODE is not the variant's part: the wrong board, or the wrong `--variant` |
| `fail`: `the JTAG chain has N devices (…), not one` | more than the board's FPGA answers on its JTAG chain (an Arty or a NeTV2): another device wired into it, or a fault on the cable |
| `fail`: `unconverted: …` | an Acorn on SQRL's factory image (or the XDMA sample): convert it ([acorn-pcie-programming.md](hardware/acorn-pcie-programming.md)) |
| `fail`: `… is not a design we built` | a Xilinx PCIe design the Acorn check does not know; its flash is not read |
| `fail`: `… has no test design for this board yet` | a Xilinx PCIe board that is not an Acorn (a PCIe Screamer, a PicoEVB) |
| `fail`: `running the golden image` | the Acorn's operational slot did not boot; it fell back to golden |
| `fail`: `link is x2, expected x1` | the Acorn's PCIe link is not the setup's (`expected.toml`) |
| `fail`: `no device on the P1 JTAG chain` / `no UARTBone reply on /dev/ttyAMA0` | an Acorn's JTAG or P2 UART cable is off or miswired |
| `fail`: `P1 JTAG could not be probed: GPIO14 (TMS) is held by 1f00030000.serial (uart0): the kernel does not hand out a pin that is held…` | an Acorn's JTAG pin is in use by another driver, so the scan was not tried. Seen on a Compute Blade with a CM5 (kernel 6.18): TMS and the serial port's TX are both GPIO14, and with the serial port on the kernel does not lend the pin. JTAG cannot be tested there while the serial port is on; booting with it off should free the pin, which is not yet confirmed on hardware ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)) |
| `fail`: `… gpiod_line_request_set_values_subset: Assertion 'request' failed` | openFPGALoader could not have one of the JTAG pins, because a driver holds it. Seen on a Compute Blade with a CM5 (kernel 6.18), where the serial port holds GPIO14, which is also JTAG TMS: the JTAG test cannot run there yet ([#127](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)) |
| `fail`: `openFPGALoader printed no raw IDCODE scan (needs --verbose-level 2 output)` | the tool's version, not the board: openFPGALoader exited 0 but printed no `- 0 -> 0x...` lines at `--verbose-level 2`, so it is older than v0.9.0. Its last lines are in the report's `output` |
| `fail`: `… failed (exit N) before scanning the JTAG chain: …` | the scan tool exited with an error and printed no scan: the cable or gpiochip would not open, say. The reason ends with its last line of output; more is in the report's `output` |
| `fail`: `… exited N reading the IDCODE` / `openFPGALoader --detect exited N …` | the IDCODE scan reported an error, even if it printed an IDCODE; its last lines are in the report's `output` |
| `fail`: `device DNA over P1 JTAG reads 0x…: the DNA port is not being read` | the DNA read over JTAG is all zeros or all ones, which is no chip's DNA. The IDCODE read worked without TDI, so check the P1 TDI wire first; then run `openFPGALoader --read-dna` by hand |
| `fail`: `device DNA over JTAG reads 0x…: the DNA port is not being read` | an Arty's or NeTV2's DNA read is all zeros or all ones. Its IDCODE scan works without TDI, so check TDI first (the NeTV2's GPIO27); then run `openFPGALoader --read-dna` by hand |
| `fail`: `openFPGALoader --read-dna read no device DNA (exit N): …` | an Arty's or NeTV2's DNA read failed; the reason ends with its last line. An openFPGALoader older than 0.13.0 (Debian bookworm's) has no `--read-dna`: install fpgas.online's ([Installing](#installing)) |
| `fail`: `device DNA over JTAG … is not the one over BAR0` | the P1 TDI wire does not carry, or the DNA readout is wrong. Only a good BAR0 DNA is compared: one of all zeros or all ones is pcie-bar0's own fault (`device DNA over BAR0 reads 0x0: the DNA port is not being read`) |
| `fail`: `J5 -> GPIO3: the FPGA drove 0, the Pi read 1` (or the other way) | a P2 spare wire is cut or miswired |
| `fail`: `K2 -> GPIO15: …` / `GPIO14 -> J2: …` | a P2 serial wire is cut or miswired |
| `fail`: `DRAM write … MB/s, below the … MB/s expected` / `… words wrong in the … half` | the DRAM is slow or broken; `selftest.py` shows more |
| `error`: `this host (…) is not an Acorn setup in wiring.toml` | an Acorn on a host neither setup has: add the host to `wiring.toml` if it is a real setup |
| `changed` | the board or its flash differs from the recorded state. Meant it? `sudo fpgas-verify --update` |

### The report and the recorded state

* The report, `/run/fpgas-online/verify.json` (this boot's only, `schema_version` 2):

  | Field | Holds |
  |---|---|
  | `result`, `reason` | the result, and why, when no board was checked |
  | `checked_at` | when (UTC, ISO 8601) |
  | `mode`, `configured_by`, `chosen_by` | `auto` or the board, the file (or "command line") that said so, and how the boards were found |
  | `boards[]` | per board: `board`, `variant`, `found`, `result`, `reason` (every fault), `bitstreams`, `tests[]` (`test`, `result`, `reason`, `output`, and what the test read or measured), `identity` ([who the board is](identity.md)), `state`. The Arty's and NeTV2's also have `jtag`: `result`, `reason`, the [IDCODE's fields](#the-jtag-idcode), and `dna` or `dna_error` ([the device DNA](#the-device-dna)). The Acorn's also has `setup`, `running`, `flash`, `not_run`, and `driver` when one was unbound. `not_run` (test: why) is also on a Tiny Tapeout board with a chip, for the cabling test it does not have yet; there it fails the board |
  | `state` | `file`, and `recorded` (`first run` or `--update`) or `changes` |

  ```bash
  python3 -c 'import json; r = json.load(open("/run/fpgas-online/verify.json")); print(r["result"]); [print(b["board"], t["test"], t["result"]) for b in r["boards"] for t in b.get("tests", [])]'
  ```
* The first run records each board's identity and flash fingerprint in `/var/lib/fpgas-online/verify-state.json`.
  Later runs compare against it; a difference is `changed` until `sudo fpgas-verify --update`.
* Loading a test design and upgrading the packages are not changes. A flash that could not be read is not compared.
* An IDCODE recorded without its version (a record with `schema_version` below 3) takes the whole one
  quietly. On a newer record, another version is a change: it is another chip.
* One swap is missed because of that, once. A NeTV2 on a Pi 3/4 recorded its whole IDCODE even before
  schema 3 (OpenOCD prints it), but the record cannot say whether its value was whole or masked. A version 0
  value looks the same either way. So if such a board's version 0 chip was swapped for a version 1 chip of
  the same part, the first run on schema 3 takes the new IDCODE quietly instead of reporting `changed`.
  Later runs compare the whole IDCODE as usual.
* A device DNA recorded without its leading zeros (a record with `schema_version` below 4) takes the 16-digit
  spelling quietly. Another DNA is a change.
* On a record with `schema_version` below 4, a flash part name that changed while its JEDEC ID and unique ID
  did not is a corrected name, taken quietly: the part is now named from RDID byte 6, so an S25FS256S is no
  longer called an S25FL256S. A different JEDEC ID or unique ID is still a change, and so is a rewritten flash.
* A device DNA missing from a record with `schema_version` below 5 is added quietly, once: until then only the
  Acorn's was read. This goes for every board, so an Acorn whose record has no DNA (neither BAR0 nor JTAG
  read one that run) also gets its DNA added quietly. On a newer record a DNA not recorded before is a
  change, as is another DNA.
* A `--test` run neither records nor compares the state.

---

## 2. How verify is used in fpgas.online

| What | How |
|---|---|
| Install | every netbooted Pi at a site shares one read-only NFS root, built with `fpgas-online-all-boards` (infra `roles/onpi/tasks/fpga_verify.yml`) |
| Publishing | the root carries `/etc/fpgas-verify/fleet.ini` with `[verify]` and `publish = on` (infra `roles/onpi`); without it the check sends nothing and the site never lists the board |
| When | `fpgas-verify.service` runs it once per boot, and only then: to check a Pi again, reboot it. It starts after `fpgas-fleet-agent.service` and before `fpgas-tt.service` (ordering only); time limit 30 minutes |
| State | `/var/lib` is on the root's tmpfs overlay, so every boot is a first run and `changed` never fires |
| No board | Orange Pis, or a Pi whose board is off, report `missing`, a fail; the Pi still boots and takes ssh |
| Result | anything but `pass` leaves the unit failed; the summary is in `journalctl -b -u fpgas-verify` |
| Site | the fleet app ([site](https://github.com/fpgas-online/fpgas.online-site) `fleet/src/fleet/services.py`) keeps each Pi's state for **this boot**: `verifying` from `fpga-verifying` until `fpga-verified`, then its result. `/fleet/` lists them |
| Gate | with `FPGAS_REQUIRE_VERIFIED = True` (infra `site_require_fpga_verified`, on for Welland), `/fpgas/` offers only Pis whose state is `pass` |

### Events

The check tells the site what it is doing as it goes. `fleet-event` (from
[setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi)) sends each over MQTT to
`fpgas/<site>/pi/<serial>/event`. The names and details are `EVENTS` in
[`runner.py`](../verify/src/fpgas_online_verify/runner.py):

| Event | When | Details |
|---|---|---|
| `fpga-verifying` | the check starts | `started_at` |
| `fpga-board-found` | for each board found | `board`, `variant` (`-` for a Tiny Tapeout board, which says what it is later), `where` (PCI slot, USB path or JTAG IDCODE) |
| `fpga-no-board` | no board was found | `reason` |
| `fpga-board-identified` | exactly once for each board found: an Acorn once PCIe and JTAG have said who it is, any other board before its tests; a board whose check stops first, or that is not checked (`--test` naming none of its tests), from what finding it showed | `schema` (`fpga-identity/1`) and the board's [identity](identity.md) |
| `fpga-test-started` | each test starts | `board`, `test` |
| `fpga-test-finished` | each test ends | `board`, `test`, `result`, `reason` |
| `fpga-verified` | the check is done | the report, flattened: `result`, `mode`, `reason`; per board `board0` (`netv2 a7-35 fail`), `board0_reason`, `board0_tests` (`uart=pass ddr=fail spiflash=pass`), `board0_not_run` (the names in `not_run`, when there are any), `board0_bitstreams`, `board0_state_*`, `board0_identity_*` |

* `board` is the board's name, or `name@where` when there are two of a kind.
* `fpga-verifying` and the progress events each wait at most 15 s, so a broker that is down does not hold up
  the check; `fpga-verified` waits at most 60 s.
* If an event before `fpga-verified` cannot be sent, no more progress events are tried that run, but
  `fpga-verified` still is.
* A failure to send is reported on stderr and does not change the result; the report stays in
  `/run/fpgas-online/verify.json`.
* Nothing is sent without `publish = on` (above). With it, `--test` runs and `--no-publish` still send nothing.

The progress events of an Acorn passing every test, in order, with their details (the check run against the
tests' fake Acorn, [`tests/acorn_fakes.py`](../tests/acorn_fakes.py); the last 12 are cut):

```text
fpga-board-found {"board": "acorn", "variant": "cle-215+", "where": "0001:01:00.0"}
fpga-test-started {"board": "acorn", "test": "pcie-link"}
fpga-test-finished {"board": "acorn", "test": "pcie-link", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "pcie-bar0"}
fpga-test-finished {"board": "acorn", "test": "pcie-bar0", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "rp1-pio"}
fpga-test-finished {"board": "acorn", "test": "rp1-pio", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "jtag"}
fpga-test-finished {"board": "acorn", "test": "jtag", "result": "pass", "reason": ""}
fpga-board-identified {"board": "acorn", "kind": "acorn", "variant": "cle-215+", "bdf": "0001:01:00.0", "soc_model": "cle-215+", "identifier": "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-21 14:23:32", "build": "operational", "dna": "0x0054b48664b04854", "idcode": "0x13636093", "idcode_version": "1", "idcode_part_number": "0x3636", "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A200T", "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180", "flash": "S25FL256S", "flash_size_bytes": "33554432", "flash_status": "0x00", "flash_config": "0x02", "flash_quad": "true", "flash_uid": "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf", "flash_uid_bits": "128", "flash_uid_state": "read", "flash_uid_opcode": "0x4b", "flash_sfdp": "none", "flash_source": "pcie", "schema": "fpga-identity/1"}
```

They come between `fpga-verifying` and `fpga-verified`.

### How a deploy picks up new packages

1. A commit lands on `main`. When CI is green, [`collect-bitstreams.yml`](../.github/workflows/collect-bitstreams.yml)
   uploads the packages to that build's own release, `build-<version>` (for example `build-0.0.post795`).
2. [fpgas-online/apt](https://github.com/fpgas-online/apt) pulls them into <https://apt.fpgas.online> within 15 minutes.
3. Infra CI (`nfsroot-build.yml`) builds the NFS root image with the latest packages, as
   `ghcr.io/fpgas-online/nfsroot:ci-<run>`; on infra `main` it moves `bookworm-armhf` once a virtual Pi has
   netbooted it.
4. An operator runs infra `site.yml --limit fpgas.online` (optionally `-e img_nfsroot_image=…:ci-<run>`), which
   unpacks the image on tweed.
5. Each Pi's `nfsroot-watchdog` reboots it in its own slot, 20 s apart (a two-switch site takes about 33 minutes).
6. Each Pi runs the new `fpgas-verify` at boot and publishes the result; the gate follows.

### Collecting every Pi's result

[`scripts/collect_verify_status.py`](../scripts/collect_verify_status.py) reads every Pi's report, unit state,
installed version and (with no report) journal over SSH. It only reads, so it is safe while boards are in use.

```bash
uv run --no-project python scripts/collect_verify_status.py \
    --ssh-config ../fpgas.online-infra/ansible/ssh.cfg            # every port on both Welland switches
uv run --no-project python scripts/collect_verify_status.py --host 10.21.2.47 --json tmp/verify.json
```

* It goes through tweed (`ansible@10.99.21.2`) as `root` to `10.21.<switch>.<port>`: switch 1 ports 1-40 and
  switch 2 ports 1-48, except sw2 p30 (not on the fpgas root). See `--help` for `--jump`, `--ports`, `--host`, ….
* Exit: 2 if the jump host is unreachable; 1 if no Pi, or some Pi, could not be read; else 0.
* The Pis share one host key, kept as `fpgas-netboot-pi` in `~/.config/fpgas-online/netboot_known_hosts`
  (learnt on first use). After a deliberate rekey:
  `ssh-keygen -R fpgas-netboot-pi -f ~/.config/fpgas-online/netboot_known_hosts`.
* The site's `/fleet/` page shows the same overall result per Pi, but not the tests.

### Current results

Collected 2026-10-02T03:50:20Z from the 24 Welland Pis that answered, all running `fpgas-online-verify`
`0.0.post771`, by:

```bash
uv run --no-project python scripts/collect_verify_status.py --ssh-config ../fpgas.online-infra/ansible/ssh.cfg
```

pi-sw2-p47's row is from a later check, at 2026-10-02T03:56:17Z, once its flash held the pinned release
(`vivado-bitstreams-acorn-pcie-20261001-ge568a408e7bd`). Rerun the collector to refresh this section.

| Board | Pis | Result | Tests (passed / run) |
|---|---|---|---|
| Acorn | 2 | pass 2 | pcie-link 2/2, pcie-bar0 2/2, jtag 2/2, flash 2/2, ddr 2/2, p2-uart 2/2, p2-serial 2/2, scratch 2/2, p2-gpio 2/2 |
| Arty A7 | 4 | fail 4 | uart 4/4, ddr 4/4, spiflash 4/4, ethernet 3/4, pin-id 0/4 |
| Fomu EVT | 1 | pass 1 | uart 1/1 |
| NeTV2 | 5 | fail 5 | uart 5/5, ddr 0/5, spiflash 5/5 |
| TT FPGA | 3 | fail 3 | pin-id 0/3, uart 3/3, spiflash 0/3 |
| Unrecognised PCIe FPGA | 2 | fail 2 | - |
| (no board) | 7 | missing 7 | - |

| Host | Pi | Board | Variant | Result | Tests | Reason | Checked (UTC) | fpgas-online-verify |
|---|---|---|---|---|---|---|---|---|
| pi-sw1-p10 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:14:54Z | 0.0.post771 |
| pi-sw1-p12 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:15:49Z | 0.0.post771 |
| pi-sw1-p14 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:16:07Z | 0.0.post771 |
| pi-sw1-p16 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:16:22Z | 0.0.post771 |
| pi-sw1-p17 | Pi 3B+ | Fomu EVT | evt | pass | uart=pass |  | 2026-10-02T03:16:39Z | 0.0.post771 |
| pi-sw1-p18 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:17:44Z | 0.0.post771 |
| pi-sw1-p38 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | PCIe Screamer (PCILeech image): fpgas.online has no test design for this board yet | 2026-10-02T03:23:02Z | 0.0.post771 |
| pi-sw2-p9 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:29:45Z | 0.0.post771 |
| pi-sw2-p10 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=**fail** pin-id=**fail** | ethernet fail: the test exited 1; pin-id fail: the test exited 1 | 2026-10-02T03:30:57Z | 0.0.post771 |
| pi-sw2-p12 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:31:05Z | 0.0.post771 |
| pi-sw2-p15 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:32:22Z | 0.0.post771 |
| pi-sw2-p18 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:33:35Z | 0.0.post771 |
| pi-sw2-p19 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:14Z | 0.0.post771 |
| pi-sw2-p20 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:27Z | 0.0.post771 |
| pi-sw2-p21 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:12Z | 0.0.post771 |
| pi-sw2-p22 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:16Z | 0.0.post771 |
| pi-sw2-p23 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:35:45Z | 0.0.post771 |
| pi-sw2-p24 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:35:05Z | 0.0.post771 |
| pi-sw2-p33 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:29Z | 0.0.post771 |
| pi-sw2-p35 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:51Z | 0.0.post771 |
| pi-sw2-p36 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:58Z | 0.0.post771 |
| pi-sw2-p37 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | Xilinx XDMA design (likely PicoEVB): fpgas.online has no test design for this board yet | 2026-10-02T03:38:50Z | 0.0.post771 |
| pi-sw2-p47 | Pi 5B | Acorn | cle-215+ | pass | pcie-link=pass pcie-bar0=pass jtag=pass flash=pass ddr=pass p2-uart=pass p2-serial=pass scratch=pass p2-gpio=pass | (a later check) | 2026-10-02T03:56:17Z | 0.0.post771 |
| pi-sw2-p48 | Pi 5B | Acorn | cle-215+ | pass | pcie-link=pass pcie-bar0=pass jtag=pass flash=pass ddr=pass p2-uart=pass p2-serial=pass scratch=pass p2-gpio=pass |  | 2026-10-02T03:42:34Z | 0.0.post771 |

No Pi answered on 63 ports: sw1 p1-9,p11,p13,p15,p19-37,p39-40; sw2 p1-8,p11,p13-14,p16-17,p25-29,p31-32,p34,p38-46.

What the results show:

| Board | Result |
|---|---|
| Acorn | both pass all 9 tests. `ddr` on each: 1 GiB, 2 passes, 0 errors, 1327.4 MB/s write, 1350.1 MB/s read |
| Arty A7 | `pin-id` fails on all 4; `ethernet` fails on pi-sw2-p10; `uart`, `ddr` and `spiflash` pass on all 4 |
| NeTV2 | `ddr` fails on all 5; `uart` and `spiflash` pass |
| TT FPGA | `pin-id` and `spiflash` fail on all 3; `uart` passes |
| Fomu EVT | pi-sw1-p17 passes |
| Unrecognised PCIe FPGA | pi-sw1-p38 (a PCIe Screamer) and pi-sw2-p37 (an XDMA design, likely a PicoEVB): fpgas.online has no test design for them |
| (no board) | pi-sw2-p18 … p24: Orange Pi PCs with no FPGA, so `missing`. pi-sw2-p30, their FEL host, is not on the fpgas root and is not read |
