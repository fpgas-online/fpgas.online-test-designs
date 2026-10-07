# fpgas-verify: more results

You have run `fpgas-verify`, read [reading the result](reading-the-result.md), and want to compare your
summary with more failing and missing results.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

**fail, with two faults**: the check run against the tests' fake Acorn
([`tests/acorn_fakes.py`](../../tests/acorn_fakes.py)), with its PCIe link at x2 and a JTAG TDI wire that does not carry:

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
    https://docs.fpgas.online/en/latest/verify/common-failures.html#common-failures
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
    https://docs.fpgas.online/en/latest/verify/common-failures.html#common-failures
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
    https://docs.fpgas.online/en/latest/verify/common-failures.html#common-failures
The whole report, for a program to read (JSON): /run/fpgas-online/verify.json
******************************************************************************

exit 1
```
