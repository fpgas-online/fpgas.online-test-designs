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

# Optional: fpgas.online's openFPGALoader. A NeTV2 on a Pi 5 needs it; add it before installing.
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
sudo fpgas-verify --no-publish             # check this host's board, as the boot does
sudo fpgas-arty-verify --no-publish        # check the Arty, whatever this host is set up for
sudo fpgas-arty-verify --test ddr          # run one test; the JSON report goes to stdout
sudo fpgas-acorn-verify --test pcie-link --test flash   # only some tests (these two only read)
sudo fpgas-verify --update                 # after flashing or swapping a board on purpose
fpgas-verify --list                        # the installed boards, and which this host checks

sudo fpgas-arty-debug test ddr             # load the DDR design and run its test, all output live
sudo fpgas-acorn-debug identify            # the Acorn's running build and flash IDs
```

* Run them with `sudo`; `--help`, `--list` and `fpgas-<board>-debug list` do not need it.
* Without `--no-publish`, a host that is not a fleet Pi also prints
  `fpgas-verify: could not publish fpga-verifying ([Errno 2] No such file or directory: 'fleet-event')`.
  The result is unaffected.
* `--test` runs part of the check. It is never published, never recorded, and its report goes to stdout
  unless `--report` says otherwise.
* Only one command uses a board at a time. A second one prints
  `waiting for another user of the <board> to finish...` and waits.
* Which board a host checks is `[verify] fpga-board = <board>` or `auto`, in `*.ini` files: the board's
  package puts one in `/usr/share/fpgas-online/verify/mode.d/`; one in `/etc/fpgas-verify/` overrides it.
* Options for the boot run go in `FPGAS_VERIFY_ARGS` in `/etc/default/fpgas-verify`.
* From a checkout, without installing: `PYTHONPATH=verify/src python3 -m fpgas_online_verify --help`.

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
* The check goes on after a fault wherever it can, so the board's reason lists every fault it found.
* The summary goes to stderr; at boot, to the journal (`journalctl -b -u fpgas-verify`). A failed test's last
  8 output lines are shown.
* The JSON report is in `/run/fpgas-online/verify.json`.

**pass**: an Acorn on the Pi 5 setup. This is the check run against the tests' fake Acorn
([`tests/acorn_fakes.py`](../tests/acorn_fakes.py)):

```text
$ sudo fpgas-verify --no-publish
fpgas-verify: pass (mode auto, auto: USB/PCI IDs)
  acorn cle-215+: pass
    pcie-link  pass
    pcie-bar0  pass
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

**fail, with two faults**: the same fake Acorn, with its PCIe link at x2 and a JTAG TDI wire that does not carry:

```text
$ sudo fpgas-verify --no-publish
******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode auto, auto: USB/PCI IDs)
  acorn cle-215+: fail: pcie-link fail: link is x2, expected x1; jtag fail: device DNA over JTAG 0x1 is not the one over BAR0 0x54b48664b04854: TDI (or the DNA readout) is wrong
    pcie-link  fail: link is x2, expected x1
    pcie-bar0  pass
    jtag       fail: device DNA over JTAG 0x1 is not the one over BAR0 0x54b48664b04854: TDI (or the DNA readout) is wrong
        index 0:
            idcode 0x3636093
            manufacturer xilinx
            family artix a7 200t
            model  xc7a200
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
  more: fpgas-<board>-debug (fpgas-online-<board>-debug)
******************************************************************************
```

**fail**: a NeTV2 whose DDR test fails (pi-sw1-p12, at boot):

```text
$ journalctl -b -u fpgas-verify -o cat
******************************************************************************
*** FPGA VERIFY: FAIL ******************************************************
fpgas-verify: fail (mode auto, auto: probed (netv2))
  netv2 a7-35: fail: ddr fail: the test exited 1
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
  more: fpgas-<board>-debug (fpgas-online-<board>-debug)
******************************************************************************
```

**missing**: a host set up for an Arty, with none attached:

```text
$ sudo fpgas-verify --no-publish; echo "exit $?"

******************************************************************************
*** FPGA VERIFY: MISSING ***************************************************
fpgas-verify: missing (mode arty, -)
  no Digilent Arty A7 found: this host is set up for one, and nothing else is looked for
  more: fpgas-<board>-debug (fpgas-online-<board>-debug)
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
  --list             list the installed boards and the configured one
  --board BOARD      check BOARD, ignoring the configuration
  --no-probe         never scan JTAG to find a board (auto only)
  --test TEST        run only TEST (repeatable); not published or recorded
  --update           accept a changed board or flash: record it
  --variant VARIANT  use VARIANT's bitstreams, not the detected one
  --port PORT        the board's UART (default: the board's usual one)
  --images DIR       the bitstreams (default: installed)
  --state FILE       the recorded state
  --report FILE      the JSON report; '-' for stdout (the default with --test)
  --no-publish       do not send the result to the fleet

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
  --variant VARIANT  use VARIANT's bitstreams, not the detected one
  --port PORT        the board's UART (default: the board's usual one)
  --images DIR       the bitstreams (default: installed)
  --state FILE       the recorded state
  --report FILE      the JSON report; '-' for stdout (the default with --test)
  --no-publish       do not send the result to the fleet

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
  --images DIR   the bitstreams (default: installed)
  --state FILE   the recorded state
  --report FILE  the JSON report; '-' for stdout (the default with --test)
  --no-publish   do not send the result to the fleet

tests in the boot check:
  pcie-link pcie-bar0 jtag flash ddr p2-uart p2-serial scratch p2-gpio

the result is pass (exit 0) or a fail named for its worst cause (exit 1):
  pass          every test passed, and the board and flash are as recorded
  changed       a different board or flash from the recorded one
  fail          a test failed, or the board runs a design that is not ours
  missing       no board found
  error         the check could not run (a missing tool or file)

files:
  /run/fpgas-online/verify.json            the report (--report)
  /var/lib/fpgas-online/verify-state.json  the recorded state (--state)
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
  identify      show the running build and the flash's ID

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
  id                print the flash's part, size and IDs as JSON
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
| Arty A7 | USB `0403:6010` | `openFPGALoader -b arty` | `/dev/ttyUSB1` | `uart`, `ddr`, `spiflash`, `ethernet`, `pin-id` | `pmod` | FTDI serial, flash JEDEC ID, sha256 of the flash's first 2.1 MiB |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22 | openocd (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `/dev/ttyAMA0` | `uart`, `ddr`, `spiflash` | `ethernet`, `pmod`, `pin-id` | IDCODE, flash JEDEC ID, sha256 of the flash's boot image |
| Fomu EVT | USB `1209:5bf0` (DFU bootloader) | openFPGALoader over DFU | `/dev/serial0` | `uart` | `spiflash`, `pmod`, `pin-id` | USB serial |
| TT FPGA | USB `2e8a:*` | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | `pin-id`, `uart`, `spiflash` | `pmod` | USB serial |

* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  others the last test design. Each returns to its flash image at its next power cycle.
* The Fomu runs only `uart` at boot: a DFU load replaces the bootloader until the next power cycle.
* The TT FPGA's `fpgas-tt.service` is stopped for the tests and started again after.
* The NeTV2 has no USB, so finding it means driving the GPIO header. With `fpga-board = auto` the JTAG scan
  runs only if nothing was found on USB or PCI (or only a Xilinx PCIe design the Acorn check cannot name);
  `--no-probe` turns it off.

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
| `1e24:021f` or `1e24:0101` as vendor:device | an Acorn on SQRL's factory image | `fail`, `unconverted: …`; only `pcie-link` and `jtag` run |
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
| `pcie-bar0` | BAR0 | the operational build runs (the golden build means the operational slot did not boot), the flash identifies itself, the device DNA is neither all zeros nor all ones, and the XADC temperature and VCCINT, VCCAUX and VCCBRAM are in range |
| `jtag` | P1 | `openFPGALoader --detect` finds one device with the variant's IDCODE, and `openFPGALoader --read-dna` reads the DNA BAR0 gave. The IDCODE read does not use TDI; the DNA read does |
| `flash` | BAR0 | both 4 MiB slots (golden at `0x000000`, operational at `0x400000`), read whole with read opcodes only, hold the release's images |
| `ddr` | BAR0 | after the BIOS console is read out, the DRAM BIST makes two passes over the whole DRAM: no errors, and write and read bandwidth at least the variant's minimum |
| `p2-uart` | P2 | the UARTBone identifier at 1200 baud is BAR0's; at 921600 baud the identifier, DNA and XADC readings are right and the DNA is BAR0's. The link is left at 1200 baud |
| `p2-serial` | BAR0 and the Pi's GPIO | J2/K2, borrowed from the UART by the `p2_serial` switch, carry 0 and 1 both ways; the switch goes back to serial by itself; the UARTBone then answers with BAR0's identifier |
| `scratch` | BAR0 and P2 | the `ctrl` scratch register holds two patterns written over each bridge; its value is put back |
| `p2-gpio` | BAR0 and the Pi's GPIO | Pi 5 setup only: J5/H5 carry 0 and 1 both ways, FPGA to Pi and Pi to FPGA |

* `ddr` in detail ([`bist.py`](../verify/src/fpgas_online_verify/boards/acorn/bist.py), the same code
  [`selftest.py`](../designs/acorn-pcie/host/selftest.py) runs):
  1. The BIOS console is read until it has been quiet for 2 s. The BIOS stops while its console is full and
     unread ([#47](https://github.com/fpgas-online/fpgas.online-test-designs/pull/47)), so reading it lets it
     finish setting up the DRAM. Its memtest line, when still there, is reported as `bios_memtest`.
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

#### Not done yet

What [verify-goals.md](verify-goals.md) asks for that the check does not do yet:

* The Arty, NeTV2, Fomu and TT FPGA are checked with the single-function test designs, loaded one at a time,
  not with the full test design.
* `pin-id` checks each Pmod pin in one direction only, FPGA to Pi.
* The Acorn's PCIe transfer rate is not measured.

### Common failures

| It says | Meaning, and what to do |
|---|---|
| `missing`: `no <board> found: this host is set up for one…` | the board is not on USB/PCI (or JTAG). Check power and cables. A Fomu that has run a design needs a power cycle |
| `missing`: `none of the installed boards … was found` | nothing attached. Expected on a Pi with no FPGA, and still a fail |
| `error`: `… is not installed` | a tool is missing: `mpremote` (bookworm: bookworm-backports), openocd, openFPGALoader |
| `error`: `no FPGA board is configured` / `conflicting fpga-board settings` | install one board's package, or fix `/etc/fpgas-verify/*.ini` |
| `error`: `… does not match its manifest` / `manifest.json is missing` | `sudo apt install --reinstall fpgas-online-<board>-bitstreams` |
| `fail`: `loading it failed (exit N)` | the programmer could not load the design: JTAG wiring, cable, or programmer support |
| `fail`: `python3 did not finish within 300 s` | the design never printed what the test waits for: wrong UART, or the design does not run |
| `fail`: `the test exited 1` | the test failed; its last lines are in the summary. `fpgas-<board>-debug test <test>` shows all of it |
| `fail`: `N/18 pins match expected wiring` | the Pmod HAT cabling differs from the board's expected map |
| `fail`: `unconverted: …` | an Acorn on SQRL's factory image (or the XDMA sample): convert it ([acorn-pcie-programming.md](hardware/acorn-pcie-programming.md)) |
| `fail`: `… is not a design we built` | a Xilinx PCIe design the Acorn check does not know; its flash is not read |
| `fail`: `… has no test design for this board yet` | a Xilinx PCIe board that is not an Acorn (a PCIe Screamer, a PicoEVB) |
| `fail`: `running the golden image` | the Acorn's operational slot did not boot; it fell back to golden |
| `fail`: `link is x2, expected x1` | the Acorn's PCIe link is not the setup's (`expected.toml`) |
| `fail`: `no device on the P1 JTAG chain` / `no UARTBone reply on /dev/ttyAMA0` | an Acorn's JTAG or P2 UART cable is off or miswired |
| `fail`: `device DNA over JTAG … is not the one over BAR0` | the P1 TDI wire does not carry, or the DNA readout is wrong |
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
  | `boards[]` | per board: `board`, `variant`, `found`, `result`, `reason` (every fault), `bitstreams`, `tests[]` (`test`, `result`, `reason`, `output`, and what the test read or measured), `state`. The Acorn's also has `setup`, `identity`, `running`, `flash`, `not_run`, and `driver` when one was unbound |
  | `state` | `file`, and `recorded` (`first run` or `--update`) or `changes` |

  ```bash
  python3 -c 'import json; r = json.load(open("/run/fpgas-online/verify.json")); print(r["result"]); [print(b["board"], t["test"], t["result"]) for b in r["boards"] for t in b.get("tests", [])]'
  ```
* The first run records each board's identity and flash fingerprint in `/var/lib/fpgas-online/verify-state.json`.
  Later runs compare against it; a difference is `changed` until `sudo fpgas-verify --update`.
* Loading a test design and upgrading the packages are not changes. A flash that could not be read is not compared.
* A `--test` run neither records nor compares the state.

---

## 2. How verify is used in fpgas.online

| What | How |
|---|---|
| Install | every netbooted Pi at a site shares one read-only NFS root, built with `fpgas-online-all-boards` (infra `roles/onpi/tasks/fpga_verify.yml`) |
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
| `fpga-board-found` | for each board found | `board`, `variant`, `where` (PCI slot, USB path or JTAG IDCODE) |
| `fpga-no-board` | no board was found | `reason` |
| `fpga-board-identified` | an Acorn, once PCIe and JTAG have said who it is | `board`, `bdf`, `pci_ids`, `subsystem`, `variant`, `identifier`, `build`, `dna`, `idcode`, `flash_part`, `flash_jedec`, `flash_unique_id` |
| `fpga-test-started` | each test starts | `board`, `test` |
| `fpga-test-finished` | each test ends | `board`, `test`, `result`, `reason` |
| `fpga-verified` | the check is done | the report, flattened: `result`, `mode`, `reason`; per board `board0` (`netv2 a7-35 fail`), `board0_reason`, `board0_tests` (`uart=pass ddr=fail spiflash=pass`), `board0_bitstreams`, `board0_state_*`, `board0_identity_*` |

* `board` is the board's name, or `name@where` when there are two of a kind.
* `fpga-verifying` and the progress events each wait at most 15 s, so a broker that is down does not hold up
  the check; `fpga-verified` waits at most 60 s.
* If an event before `fpga-verified` cannot be sent, no more progress events are tried that run, but
  `fpga-verified` still is.
* A failure to send is reported on stderr and does not change the result; the report stays in
  `/run/fpgas-online/verify.json`.
* `--test` runs and `--no-publish` send nothing.

The progress events of the Acorn [passing above](#reading-the-result), in order, with their details (the same
run against the tests' fake Acorn; the last 12 are cut):

```text
fpga-board-found {"board": "acorn", "variant": "cle-215+", "where": "0001:01:00.0"}
fpga-test-started {"board": "acorn", "test": "pcie-link"}
fpga-test-finished {"board": "acorn", "test": "pcie-link", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "pcie-bar0"}
fpga-test-finished {"board": "acorn", "test": "pcie-bar0", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "jtag"}
fpga-test-finished {"board": "acorn", "test": "jtag", "result": "pass", "reason": ""}
fpga-board-identified {"board": "acorn", "bdf": "0001:01:00.0", "pci_ids": "10ee:7021", "subsystem": "1e24:021f", "variant": "cle-215+", "identifier": "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-21 14:23:32", "build": "operational", "dna": "0x54b48664b04854", "idcode": "0x3636093", "flash_part": "S25FL256S", "flash_jedec": "0x010219", "flash_unique_id": "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf"}
```

They come between `fpga-verifying` and `fpga-verified`.

### How a deploy picks up new packages

1. A commit lands on `main`. When CI is green, [`collect-bitstreams.yml`](../.github/workflows/collect-bitstreams.yml)
   uploads the packages to this repository's `v0.0` release.
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
