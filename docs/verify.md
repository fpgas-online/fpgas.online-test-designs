# fpgas-verify: checking an FPGA board from its Raspberry Pi

`fpgas-verify` finds the FPGA board on a Raspberry Pi, loads the fpgas.online test designs into it one at a
time, runs each design's host test, and says `pass` or what is wrong. The code is in [`verify/`](../verify/);
the design notes are in [plans/2026-09-26-fpgas-online-verify-design.md](plans/2026-09-26-fpgas-online-verify-design.md).

1. [Using verify as a standalone tool](#1-using-verify-as-a-standalone-tool)
2. [How verify is used in fpgas.online](#2-how-verify-is-used-in-fpgasonline), with the
   [current results](#current-results)

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
| `fpgas-online-acorn` | everything to check a Sqrl Acorn CLE-215+ / CLE-101, and turns the boot check on for it |
| `fpgas-online-arty` | everything to check a Digilent Arty A7-35T, and turns the boot check on for it |
| `fpgas-online-netv2` | everything to check a Kosagi NeTV2 (XC7A35T or XC7A100T), and turns the boot check on for it |
| `fpgas-online-fomu` | everything to check a Fomu EVT, and turns the boot check on for it |
| `fpgas-online-tt-fpga` | everything to check a TT FPGA Demo Board, and turns the boot check on for it |
| `fpgas-online-all-boards` | everything to check any of the boards, and turns the boot check on for whichever is found |
| `fpgas-online-multi-board` | turns the boot check on for whichever board is found, of those whose `fpgas-online-<board>-tools` you also install |

* `fpgas-online-<board>-debug` adds `fpgas-<board>-debug` and the tools for the tests the boot check skips.
* Installing does not run the check. It runs at the next boot, or when you run it.
* `sudo apt upgrade` moves every package together: each depends on the others' exact version.
* Each board's page lists what its packages pull in: [acorn](hardware/acorn.md#installing-the-acorn-packages),
  [arty-a7](hardware/arty-a7.md#installing-the-arty-packages), [netv2](hardware/netv2.md#installing-the-netv2-packages),
  [fomu-evt](hardware/fomu-evt.md#installing-the-fomu-packages), [tt-fpga](hardware/tt-fpga.md#installing-the-tt-fpga-packages).

### Running it

```bash
sudo fpgas-verify --no-publish             # check this host's board, as the boot does
sudo fpgas-arty-verify --no-publish        # check the Arty, whatever this host is set up for
sudo fpgas-arty-verify --test ddr          # run one test; the JSON report goes to stdout
sudo fpgas-verify --update                 # after flashing or swapping a board on purpose
fpgas-verify --list                        # the installed boards, and which this host checks

sudo fpgas-arty-debug test ddr             # load the DDR design and run its test, all output live
sudo fpgas-acorn-debug identify            # the Acorn's running build and flash IDs
```

* Run them with `sudo`; `--help`, `--list` and `fpgas-<board>-debug list` do not need it.
* Without `--no-publish`, a host that is not a fleet Pi also prints
  `fpgas-verify: could not publish fpga-verifying ([Errno 2] No such file or directory: 'fleet-event')`.
  The result is unaffected.
* Only one command uses a board at a time. A second one prints `waiting for another user of the <board> to finish...`
  and waits.
* Options for the boot run go in `FPGAS_VERIFY_ARGS` in `/etc/default/fpgas-verify`.
* From a checkout, without installing: `PYTHONPATH=verify/src python3 -m fpgas_online_verify --help`.

### Reading the result

The summary goes to stderr; at boot, to the journal (`journalctl -b -u fpgas-verify`). Only `pass` exits 0.
The JSON report is in `/run/fpgas-online/verify.json`.

**pass**: an Acorn (pi-sw2-p47, at boot):

```text
$ journalctl -b -u fpgas-verify -o cat
fpgas-verify: pass (mode auto, auto: USB/PCI IDs)
  acorn cle-215+: pass
    jtag       pass
    p2-uart    pass
    flash 0x000000 match
    flash 0x400000 match
  state recorded (first run) in /var/lib/fpgas-online/verify-state.json
```

**fail**: a NeTV2 whose DDR test fails (pi-sw1-p12, at boot). A failed test's last 8 lines are shown:

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

The results, best to worst, are listed at the end of `fpgas-verify --help` [below](#--help).

### `--help`

```text
$ fpgas-verify --help
usage: fpgas-verify [options]

Check this host's FPGA board with the fpgas.online test designs.
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

results, best to worst (exit 0 only for pass):
  pass          every test passed; the board and flash are as recorded
  driver-bound  Acorn: a kernel driver holds the board, so it was not read
  degraded      Acorn: running its golden (fallback) image
  changed       a different board or flash from the recorded one
  fail          a test, a load or a flash comparison failed
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

tests in the boot check: uart ddr spiflash ethernet pin-id
tests only fpgas-arty-debug runs: pmod

results, best to worst (exit 0 only for pass):
  pass          every test passed; the board and flash are as recorded
  changed       a different board or flash from the recorded one
  fail          a test, a load or a flash comparison failed
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

tests in the boot check: uart ddr spiflash ethernet pin-id
tests only fpgas-arty-debug runs: pmod

examples:
  sudo fpgas-arty-debug detect
  fpgas-arty-debug list
  sudo fpgas-arty-debug test uart
  sudo fpgas-arty-debug test pin-id -- --hat-port JA
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

For the Arty, NeTV2, Fomu and TT FPGA, each test checks its bitstream's sha256, loads it, runs its host
script ([`testbench.py`](../verify/src/fpgas_online_verify/testbench.py)) and passes when the script exits 0.

| Test | Host script | Passes when |
|---|---|---|
| `uart` | [`test_uart.py`](../designs/uart/host/test_uart.py) | the LiteX BIOS banner arrives (Arty only) and printable ASCII echoes back |
| `ddr` | [`test_ddr.py`](../designs/ddr-memory/host/test_ddr.py) | the BIOS reports DRAM calibration and `Memtest OK` |
| `spiflash` | [`test_spiflash.py`](../designs/spi-flash-id/host/test_spiflash.py) | the design reads the flash's JEDEC ID and prints `SPI_FLASH_TEST: PASS` |
| `ethernet` | [`test_ethernet.py`](../designs/ethernet-test/host/test_ethernet.py) | the design answers ARP and ping through the Pi's USB Ethernet adapter (192.168.1.100/24 on that adapter only) |
| `pin-id` | [`identify_pmod_pins.py`](../designs/pmod-pin-id/host/identify_pmod_pins.py) | every Pmod HAT GPIO receives the FPGA ball name the expected cabling puts there |
| `pmod` | [`test_pmod_loopback.py`](../designs/pmod-loopback/host/test_pmod_loopback.py) | the loopback wiring reads back; `-debug` only |

| Board | Found by | Loaded with | UART | Recorded state (a change is `changed`) |
|---|---|---|---|---|
| Arty A7 | USB `0403:6010` | `openFPGALoader -b arty` | `/dev/ttyUSB1` | FTDI serial, flash JEDEC ID, sha256 of the flash's first 2.1 MiB |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22 | openocd (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `/dev/ttyAMA0` | IDCODE, flash JEDEC ID, sha256 of the flash's boot image |
| Fomu EVT | USB `1209:5bf0` (DFU bootloader) | openFPGALoader over DFU | `/dev/serial0` | USB serial |
| TT FPGA | USB `2e8a:*` | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | USB serial |
| Acorn | PCI `10ee:*` / `1e24:*` | nothing: runs from its flash | `/dev/ttyAMA0` | PCI slot and IDs, flash IDs, sha256 of both flash slots |

* Each board's tests are listed in its `fpgas-<board>-verify --help`.
* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  others the last test design. Each returns to its flash image at its next power cycle.
* The Fomu runs only `uart` at boot: a DFU load replaces the bootloader until the next power cycle.
* With `fpga-board = auto`, the NeTV2's JTAG scan runs only if nothing was found on USB or PCI.

The **Acorn** check ([`boards/acorn/check.py`](../verify/src/fpgas_online_verify/boards/acorn/check.py),
[`links.py`](../verify/src/fpgas_online_verify/boards/acorn/links.py)) loads nothing and never writes the flash:

| Step | Fails when |
|---|---|
| PCI IDs | not `10ee:7021` with subsystem `1e24:021f` (CLE-215+) or `1e24:0101` (CLE-101). SQRL's factory image and the XDMA sample are `unconverted: …` |
| The SoC's identifier, over BAR0 | not the installed release's operational or golden build. Golden is `degraded` |
| The flash, over BAR0, read only | either 4 MiB slot (golden `0x000000`, operational `0x400000`) differs from the release's image |
| `jtag` | `openFPGALoader --detect` on the P1 cable (GPIO 10/9/11/8) does not find the variant's IDCODE |
| `p2-uart` | the UARTBone identifier on P2 (`/dev/ttyAMA0`) differs from BAR0's |

A kernel driver (`litepcie.ko`) bound to the board makes it `driver-bound`: nothing is read.

### Common failures

| It says | Meaning, and what to do |
|---|---|
| `missing`: `no <board> found: this host is set up for one…` | the board is not on USB/PCI (or JTAG). Check power and cables. A Fomu that has run a design needs a power cycle |
| `missing`: `none of the installed boards … was found` | nothing attached. Expected on a Pi with no FPGA |
| `error`: `… is not installed` | a tool is missing: `mpremote` (bookworm: bookworm-backports), openocd, openFPGALoader |
| `error`: `no FPGA board is configured` / `conflicting fpga-board settings` | install one board's package, or fix `/etc/fpgas-verify/*.ini` |
| `error`: `… does not match its manifest` / `manifest.json is missing` | `sudo apt install --reinstall fpgas-online-<board>-bitstreams` |
| `fail`: `loading it failed (exit N)` | the programmer could not load the design: JTAG wiring, cable, or programmer support |
| `fail`: `python3 did not finish within 300 s` | the design never printed what the test waits for: wrong UART, or the design does not run |
| `fail`: `the test exited 1` | the test failed; its last lines are in the summary. `fpgas-<board>-debug test <test>` shows all of it |
| `fail`: `N/18 pins match expected wiring` | the Pmod HAT cabling differs from the board's expected map |
| `fail`: `unconverted: …` | an Acorn on SQRL's factory image: convert it ([acorn-pcie-programming.md](hardware/acorn-pcie-programming.md)) |
| `fail`: `… is not a design we built` | a Xilinx PCIe design the Acorn check does not know |
| `fail`: `no device on the P1 JTAG chain` / `no UARTBone reply on /dev/ttyAMA0` | an Acorn's JTAG or P2 UART cable is off or miswired |
| `changed` | the board or its flash differs from the recorded state. Meant it? `sudo fpgas-verify --update` |

### The report and the recorded state

* The report, `/run/fpgas-online/verify.json` (this boot's only), holds everything in the summary and more:
  each test's last 20 output lines, the Acorn's flash details, and what found each board.
  ```bash
  python3 -c 'import json; r = json.load(open("/run/fpgas-online/verify.json")); print(r["result"]); [print(b["board"], t["test"], t["result"]) for b in r["boards"] for t in b.get("tests", [])]'
  ```
* The first run records each board's identity and flash fingerprint in `/var/lib/fpgas-online/verify-state.json`.
  Later runs compare against it; a difference is `changed` until `sudo fpgas-verify --update`.
* Loading a test design and upgrading the packages are not changes. A flash that could not be read is not compared.
* A `--test` run neither records nor compares the state.
* Which board a host checks is `[verify] fpga-board = <board>` or `auto`, in `*.ini` files: the board's package
  puts one in `/usr/share/fpgas-online/verify/mode.d/`; one in `/etc/fpgas-verify/` overrides it.

---

## 2. How verify is used in fpgas.online

| What | How |
|---|---|
| Install | every netbooted Pi at a site shares one read-only NFS root, built with `fpgas-online-all-boards` (infra `roles/onpi/tasks/fpga_verify.yml`) |
| When | `fpgas-verify.service` runs it once per boot, after `fpgas-fleet-agent.service` and before `fpgas-tt.service` (ordering only); time limit 30 minutes |
| State | `/var/lib` is on the root's tmpfs overlay, so every boot is a first run and `changed` never fires |
| No board | Orange Pis, or a Pi whose board is off, report `missing`; the unit fails, and the Pi still boots and takes ssh |
| Publishing | `fleet-event` (from [setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi)) sends `fpga-verifying` at the start (15 s timeout) and `fpga-verified` with the result over MQTT to `fpgas/<site>/pi/<serial>/event` |
| `fpga-verified` fields | `result`, `mode`, `reason`; per board `board0` (`netv2 a7-35 fail`), `board0_reason`, `board0_tests` (`uart=pass ddr=fail spiflash=pass`), `board0_bitstreams`, `board0_state_*` |
| Site | the fleet app ([site](https://github.com/fpgas-online/fpgas.online-site) `fleet/src/fleet/services.py`) keeps each Pi's state for **this boot**: `verifying` until `fpga-verified`, then its result. `/fleet/` lists them |
| Gate | with `FPGAS_REQUIRE_VERIFIED = True` (infra `site_require_fpga_verified`, on for Welland), `/fpgas/` offers only Pis whose state is `pass` |

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
