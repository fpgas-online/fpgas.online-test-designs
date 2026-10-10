# fpgas-verify: reading the result

You have run `fpgas-verify` and want to know what its result and summary mean. More examples of failing
results are in [more results](more-results.md).
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Reading the result

There is one result: **pass** or **fail**. A fail is named for its worst cause:

| Result | Pass or fail | Means |
|---|---|---|
| `pass` | pass | every test passed, and the board and its flash are the ones recorded |
| `changed` | fail | a different board, or a different flash, from the [recorded state](report-and-state.md#the-report-and-the-recorded-state) |
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
  failures](common-failures.md#common-failures)).
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
SQRL's factory image (pi16 at ps1, 2026-10-05; the summary its boot report gives). Two things are wrong, and
neither is the installation: the card has not been converted, and on this setup the JTAG test cannot have its
TMS pin ([fpgas.online-test-designs issue 127: on a Compute Blade the JTAG test cannot have GPIO14 while the serial port holds it](https://github.com/fpgas-online/fpgas.online-test-designs/issues/127)).

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
    so only its PCIe link and its JTAG could be tested. On a Compute Blade, do
    not load a design into the card or convert it: that is not in the guide
    yet. The only attempt (pi20 at ps1, 7 October 2026) lost the card's PCIe
    endpoint (a bus rescan did not bring it back, and a root-complex re-probe
    failed), and the reboot after it was followed by about two hours of
    restarts, cause not known:
    https://docs.fpgas.online/en/latest/boards/acorn/building/compute-blade/verifying-3.html
  * openFPGALoader could not have one of the JTAG pins, because a driver holds
    it (on a Compute Blade the serial port holds GPIO14, which is also the
    JTAG TMS wire). The check cannot test JTAG on such a host yet
    (fpgas.online-test-designs issue 127, on a Compute Blade the JTAG test
    cannot have GPIO14 while the serial port holds it):
    https://github.com/fpgas-online/fpgas.online-test-designs/issues/127
  * To look at the acorn board yourself: sudo fpgas-acorn-debug --help (sudo
    apt install fpgas-online-acorn-debug)
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/common-failures.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************
```

**fail, the docs' install steps run on a Compute Blade**: the same blade (pi16 at ps1, a CM5 and an Acorn
CLE-101 on SQRL's factory image) on 2026-10-07, version 0.0.post1216, installed by the steps of
[How to run the Acorn check on a Compute Blade](https://docs.fpgas.online/en/latest/boards/acorn/checks/compute-blade.html) as printed. The lines `sudo: unable to resolve host pi16: Name or service not known`, which
sudo printed first, are left out. From 0.0.post1111 the `jtag` line names what holds the pin. Its advice to
"change one blade's own copy" of the gateway's boot files is that version's; from 0.0.post1284 the check says that changing the
shared files or giving one blade its own copy is the gateway owner's choice. So is its advice to convert the card:
from 0.0.post1284 it says not to load or convert a card on a Compute Blade, as the first transcript above shows.

```text
$ sudo fpgas-acorn-verify --no-publish

******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode acorn, configured: acorn)
  not published: --no-publish
  acorn cle-101: fail
    unconverted: runs SQRL's factory image, not the fpgas.online design
    pcie-link  pass
    rp1-pio    pass
    jtag       fail: P1 JTAG could not be probed: GPIO14 (TMS) is held by 1f00030000.serial (uart0): the kernel does not hand out a pin that is held, so the JTAG chain cannot be scanned
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
    failed: jtag: P1 JTAG could not be probed: GPIO14 (TMS) is held by 1f00030000.serial (uart0): the kernel does not hand out a pin that is held, so the JTAG chain cannot be scanned
    not run: pcie-bar0, flash, ddr, p2-serial, scratch: unconverted: runs SQRL's factory image, not the fpgas.online design
    not run: p2-uart: the board does not run a known build
    not run: p2-gpio: J5 and H5 are not wired on the Compute Blade setup
What to do:
  * The Acorn still runs the image it was sold with, not the fpgas.online one,
    so only its PCIe link and its JTAG could be tested. It has to be converted
    once (the fpgas.online image loaded over JTAG, then written to its flash
    with fpgas-acorn-flash):
    https://github.com/fpgas-online/fpgas.online-test-designs/blob/main/docs/hardware/acorn-pcie-programming.md
  * The serial port has a pin JTAG needs, so the JTAG test could not run. On a
    Compute Blade the JTAG TMS wire and the serial port's TX are the same pin
    (GPIO14): while the serial port is on, JTAG cannot be tested there. Boot
    with the header's serial port off: in config.txt enable_uart=0 and no
    uart_2ndstage=1, in cmdline.txt no console=serial0 (on a netbooted blade
    these files are on the gateway: change one blade's own copy, as several
    hosts may share them). With all three, on one Compute Blade with a CM5,
    the pin was free and the JTAG test passed:
    https://github.com/fpgas-online/fpgas.online-test-designs/issues/127
  * To look at the acorn board yourself: sudo fpgas-acorn-debug --help (sudo
    apt install fpgas-online-acorn-debug)
  * What each message means:
    https://docs.fpgas.online/en/latest/verify/common-failures.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************
```
