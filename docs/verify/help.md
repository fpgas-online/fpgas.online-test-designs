# fpgas-verify: the --help output

You want to see the options and commands of `fpgas-verify`, `fpgas-arty-verify`, `fpgas-arty-debug`,
`fpgas-acorn-verify`, `fpgas-acorn-debug` and `fpgas-acorn-flash` without installing them.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## `--help`

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
