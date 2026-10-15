# fpgas-verify: what an Arty, NeTV2, Fomu or TT FPGA check tests

You have an Arty, NeTV2, Fomu or TT FPGA board and want to know what each test of its check does and when
it passes.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## What the check tests on each board

This page covers the Arty, NeTV2, Fomu and TT FPGA. The Acorn's tests are on
[What an Acorn check tests](acorn.md#acorn).

### Arty, NeTV2, Fomu and TT FPGA

Each test checks its bitstream's sha256 against the `-bitstreams` package's manifest (a damaged file is an
`error`, never loaded), loads it, runs its host script, and passes when the script exits 0
([`testbench.py`](../../verify/src/fpgas_online_verify/testbench.py)).

| Test | Host script | Passes when |
|---|---|---|
| `jtag` | (no host script) | Arty and NeTV2: the JTAG IDCODE is the variant's part and the device DNA reads and is neither all zeros nor all ones. It runs on every check of these two, also when single tests are asked for with `--test`. (The Acorn's `jtag` is on [What an Acorn check tests](acorn.md#acorn).) |
| `uart` | [`test_uart.py`](../../designs/uart/host/test_uart.py) | the LiteX BIOS banner arrives (Arty only) and printable ASCII echoes back |
| `ddr` | [`test_ddr.py`](../../designs/ddr-memory/host/test_ddr.py) | the BIOS reports DRAM calibration and `Memtest OK` |
| `flash` | [`test_spiflash.py`](../../designs/spi-flash-id/host/test_spiflash.py) | the design reads the flash's JEDEC ID and prints `SPI_FLASH_TEST: PASS` |
| `ethernet` | [`test_ethernet.py`](../../designs/ethernet-test/host/test_ethernet.py) | the design answers ARP and ping through the Pi's USB Ethernet adapter (192.168.1.100/24 on that adapter only) |
| `wiring` | [`identify_pmod_pins.py`](../../designs/pmod-pin-id/host/identify_pmod_pins.py) | each Pmod HAT GPIO the test covers receives the FPGA ball name the expected cabling puts there. TT FPGA: all 24 signal wires of the three ribbons, each on its own (the six that share three Pi pins send in turns). Arty: 18 of 24 (not the six on the shared pins). The test's last lines say which. Each scanned pin gets its function back only if that function listens. A pin whose function drives (UART TX, SPI, I2C) stays an input, with a line that gives the command to set it back once the FPGA is reset |
| `pmod` | [`test_pmod_loopback.py`](../../designs/pmod-loopback/host/test_pmod_loopback.py) | the loopback wiring reads back; `-debug` only |

| Board | Found by | Loaded with | UART | Boot-check tests, in order | Only in `-debug` | Recorded state |
|---|---|---|---|---|---|---|
| Arty A7 | USB `0403:6010` | `openFPGALoader -b arty` | `/dev/ttyUSB1` | `jtag`, `uart`, `ddr`, `flash`, `ethernet`, `wiring` | `pmod` | FTDI serial, IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's first 2.1 MiB |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22 | openocd (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `/dev/ttyAMA0` | `jtag`, `uart`, `ddr`, `flash` (`ethernet` is planned but not run yet, which fails the board: [#341](https://github.com/fpgas-online/fpgas.online-test-designs/issues/341)), and `wiring` derived from `jtag` and `uart` | `ethernet`, `pmod`, `pmod-pin-id` (the Pmod pin-ID scan; there is no Pmod HAT cabling on the NeTV2) | IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's boot image |
| Fomu EVT | CDONE high on the Pi's header (GPIO17), or USB `1209:5bf0` (foboot) | openFPGALoader over DFU | `/dev/serial0` | `header`, `foboot` (both load nothing), `uart`, `flash` (after a reset back into foboot through the header), and `wiring` derived from `header` and `uart` | `pmod` and `pmod-pin-id`, which cannot pass on the EVT ([#202](https://github.com/fpgas-online/fpgas.online-test-designs/issues/202)) | the flash's JEDEC ID and unique ID, read over the header |
| TT FPGA | USB `2e8a:0005`, `2e8a:000f` (and `2e8a:0003`, the RP2's boot loader, which fails) | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | `sdk` (loads nothing), `dip-switches`, `wiring`, `uart`, `spram`; a board with a Tiny Tapeout chip: `sdk`, then `wiring` (nothing is loaded) | `pmod` | USB serial |

* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  Fomu its test design, and the TT FPGA a design that moves its display
  ([what the TT FPGA is left running](tt-fpga.md#what-the-tt-fpga-is-left-running)). Each returns to its flash image at
  its next power cycle (the TT FPGA has none: it is empty until something is loaded).
* The Arty and NeTV2 have their whole JTAG IDCODE read and decoded before the tests, and the result is reported as their first test, `jtag`
  ([the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)): a part that is not the variant's fails the board. Then their device
  DNA is read over the same JTAG ([the device DNA](idcode-and-dna.md#the-device-dna)): one that cannot be read, or is all zeros
  or all ones, fails the board.
* The Fomu EVT sits on the Pi's header ([Fomu EVT wiring to a Raspberry Pi](https://docs.fpgas.online/en/latest/boards/fomu-evt/setup/wiring.html#connections-to-the-pi)). Finding it
  reads its CDONE (GPIO17) and drives nothing: high means its iCE40 runs a design, whatever is on its USB. The
  check then identifies it before any test
  ([#200](https://github.com/fpgas-online/fpgas.online-test-designs/issues/200)): `fomu_header_id.py` holds the iCE40 in
  reset (CRESET, GPIO27), reads its flash's JEDEC ID and unique ID over the shared SPI pins with read commands
  only, sets every line back to an input, and lets the iCE40 boot from its flash, into foboot, as at power-up.
  That stops whatever design was running, so only the check does it, never `--identify`. `header` judges the
  reading: CDONE must be high before the reset (or nothing is driven), fall in reset and rise after it, and the flash must be the EVT's W25Q128JV (`ef7018`)
  with a unique ID that is not all `00` or all `ff`. `foboot` passes when foboot enumerates on USB again within 10 s of the
  reset: the DFU loads need it.
* A DFU load replaces the Fomu's bootloader with a design that has no USB, until the next reset. So after `uart` the
  check resets the iCE40 back into foboot through the header, as `header` did, and loads `flash`'s design only once
  foboot is back on USB ([#342](https://github.com/fpgas-online/fpgas.online-test-designs/issues/342)); that is why
  `flash` needs `header` to have passed. A reset that does not bring foboot back is `flash`'s result, with the
  reason. The check ends with the same reset (`foboot-after`).
* The TT FPGA's `fpgas-tt.service` is stopped for the tests and started again once the report is written, so
  it never starts against the report of the run before. If it cannot be started again the result is `error`
  and the report says so, in `services_failed` at the top of the report: the board's own entry keeps the
  result of its tests, and the state recorded for it stands, since the board itself was read. The service is
  started even when the check is interrupted or the report cannot be written. While it is stopped, and before the first test, rpi-hwid reads who the board is ([TT FPGA identity](tt-fpga.md#tt-fpga-identity)).
* The NeTV2 has no USB, so finding it means driving the GPIO header. With `fpga-board = auto` the JTAG scan
  runs only if nothing was found on USB or PCI (or only a Xilinx PCIe design the Acorn check cannot name);
  `--no-probe` turns it off.

### What each board type's check plans

The check lists every test it should run for your board before it runs the first one, so the report
says what was not run, and why, even when the check stopped early. A check your board cannot have is listed
with the reason. A test that is planned but has no boot-check test yet is in `not_run` with its issue, and it
fails the board: the board is not offered until its test exists. The report fields are in [the fleet events](fleet.md#the-planned-tests-fields).

| Board type | Planned tests, in order | Not applicable | Not written yet (fails the board) |
|---|---|---|---|
| Arty A7 | `jtag`, `uart`, `ddr`, `flash`, `ethernet`, `wiring` | none: every common check applies | none |
| NeTV2 | `jtag`, `uart`, `ddr`, `flash`, `ethernet`, `wiring` (from `jtag` and `uart`: its wires to the Pi are the header's JTAG and UART lines) | none | `ethernet`: [#341](https://github.com/fpgas-online/fpgas.online-test-designs/issues/341) |
| Fomu EVT | `header`, `foboot`, `uart`, `flash`, `wiring` (from `header` and `uart`: it sits on the Pi's header, whose reset, CDONE and SPI flash lines `header` checks and whose UART lines `uart` checks), `foboot-after` | `jtag`: the iCE40UP5K has no JTAG port: the Fomu is loaded over USB DFU, by foboot. `ddr`: the Fomu EVT has no DRAM. `ethernet`: the Fomu EVT has no Ethernet | none |
| TT FPGA | `sdk`, `dip-switches`, `wiring`, `uart`, `spram` | `jtag`: the iCE40UP5K has no JTAG port: it is loaded through the demo board's RP2350. `flash`: the FPGA breakout has no configuration flash: the RP2350 streams each design from the Pi. `ddr`: the demo board has no DRAM. `ethernet`: the demo board has no Ethernet | none |
| TT board with a Tiny Tapeout chip | `sdk`, `wiring` | `jtag`: a Tiny Tapeout chip is an ASIC, not an FPGA: nothing on it is configured over JTAG. `uart`: a Tiny Tapeout chip's projects are fixed in silicon: no UART design can be loaded; the wiring test checks its lines to the Pi. `flash`: a Tiny Tapeout chip is an ASIC: it has no configuration flash to test. `ddr`: the demo board has no DRAM. `ethernet`: the demo board has no Ethernet | none |
| TT board that did not say which it is | `sdk`, `wiring` (not run: the check stopped when the board did not say) | `jtag`: neither a TT FPGA breakout (an iCE40UP5K, loaded through the RP2350) nor a Tiny Tapeout chip has a JTAG port. `uart`: only an FPGA board has a UART test, and the board did not say whether it carries an FPGA. `flash`: neither a TT FPGA breakout nor a Tiny Tapeout chip has a configuration flash. `ddr`: the demo board has no DRAM. `ethernet`: the demo board has no Ethernet | none |
| Acorn | `pcie-link`, `pcie-bar0`, `rp1-pio`, `jtag`, `flash`, `ddr`, `p2-uart`, `p2-serial`, `scratch`, `p2-gpio`, `wiring` (from `jtag`, `p2-uart`, `p2-serial` and `p2-gpio`: its two cables, P1 and P2) (`power-cycle` too when switched on); none for a card the Acorn module names as another board (a PCIe Screamer, a PicoEVB) | `uart`: its UART is on the P2 cable: p2-uart tests it. `ethernet`: an Acorn is an M.2 PCIe card with no Ethernet | none |

Every board with wires to the Pi has a `wiring` result. The Arty, TT FPGA and TT chip boards have a test that checks
the cabling pin by pin. On the NeTV2, Fomu and Acorn every wire is already checked by a test of its own, so their
`wiring` is derived from those tests: it passes when all of them passed, takes the result of the first that did not
(its reason then reads `p2-uart fail`), and is not run when one of them did not run.

The Fomu's `flash` test exists in `fpgas-fomu-debug`. It is not in the boot check because a DFU load replaces
foboot until the next reset.

The report puts each planned test in one of four groups:

| Group | Tests |
|---|---|
| `basic` | `jtag`, `header`, `wiring` |
| `memory` | `flash`, `ddr`, `spram` |
| `peripherals` | `uart`, `p2-uart`, `p2-serial`, `p2-gpio`, `ethernet` |
| `board-specific` | `pcie-link`, `pcie-bar0`, `power-cycle`, `rp1-pio`, `scratch`, `foboot`, `foboot-after`, `sdk`, `dip-switches`, `pmod` |

### The Arty A7 check at boot

The check finds the Arty by its FT2232H on USB (`0403:6010`). Then, in this order:

1. It reads the FPGA's whole JTAG IDCODE over that FT2232H. It must be an XC7A35T, in any silicon version. The
   report's `jtag` has it decoded (`idcode_version`, `idcode_device` and the others:
   [the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)).
2. It reads the device DNA with `openFPGALoader -b arty --read-dna` over the same FT2232H, which loads nothing.
   A DNA that cannot be read, or is all zeros or all ones, fails the board
   ([the device DNA](idcode-and-dna.md#the-device-dna)).
3. It loads the UART, DDR, SPI flash (`flash`), Ethernet and PMOD pin identification (`wiring`) test designs into SRAM with
   openFPGALoader, one at a time, and runs each one's host test.
4. It reads back the flash's boot image region (the first 2.1 MiB) through openFPGALoader's SPI-over-JTAG
   bridge.

About two of the tests:

- The Ethernet test pings the design through the Pi's USB Ethernet adapter cabled to the Arty's RJ45. It never
  touches an interface the Pi uses itself.
- The `wiring` test (the pin identification scan) checks the PMOD HAT cabling against the expected map (HAT JA/JB/JC to Arty
  JA/JB/JC, [Arty A7 wiring to a Raspberry Pi: PMOD cables](https://docs.fpgas.online/en/latest/boards/arty-a7/setup/wiring.html#pmod-cables)).

A failure in either fails the board, like any other test.

What `changed` compares is the FTDI serial number, the IDCODE, the device DNA, the flash's JEDEC ID and the
sha256 of that flash region. The Arty is left running the SPI-over-JTAG bridge, and comes back to its flash
image at the next power cycle. Only the PMOD loopback test is left to `fpgas-arty-debug`.

### The NeTV2 check at boot

The NeTV2 has no USB, so the check finds it with a JTAG scan over the Pi's header: TCK GPIO4, TMS GPIO17, TDI
GPIO27, TDO GPIO22. The scan drives GPIO 4, 17 and 27. On a host set up with `fpgas-online-netv2` that is all
the check looks for. With `fpgas-online-all-boards` it scans only when no USB or PCI board was found
(`--no-probe` rules the scan out).

Which tool drives JTAG depends on the Pi:

| | Raspberry Pi 3 or 4 | Raspberry Pi 5 |
|---|---|---|
| The scan that finds the board | OpenOCD | openFPGALoader's raw scan |
| The device DNA | openFPGALoader, `libgpiod` cable | openFPGALoader, `rp1pio` cable |
| Loading a test design | OpenOCD | openFPGALoader, `rp1pio` cable |

Then, in this order:

1. The scan reads the whole IDCODE. Its part says which FPGA is fitted, and so which bitstreams to use. Its
   silicon version is reported (the report's `jtag.idcode_version`) and does not matter
   ([the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)). A variant set with `--variant` that is not the IDCODE's
   part fails the board.
2. It reads the device DNA with `openFPGALoader --read-dna` on the same pins, which loads nothing, and puts the
   pins back as after the scan. A DNA that cannot be read, or is all zeros or all ones, fails the board
   ([the device DNA](idcode-and-dna.md#the-device-dna)).
3. It loads the UART, DDR and SPI flash (`flash`) test designs into SRAM, and runs each design's host test on
   `/dev/ttyAMA0`.
4. It reads back the flash's boot image region.

What `changed` compares is the IDCODE, the device DNA, the flash's JEDEC ID and the sha256 of that flash region.

### The Fomu EVT check at boot

The EVT sits on the Pi's GPIO header ([Fomu EVT wiring to a Raspberry Pi](https://docs.fpgas.online/en/latest/boards/fomu-evt/setup/wiring.html#connections-to-the-pi)).

How the check works with it:
- **Finding it.** The check reads the iCE40's CDONE (GPIO17), which drives nothing: high means the board is there and running a design. foboot's DFU bootloader on USB (`1209:5bf0`) finds it too, but is not needed. A Fomu whose USB is being analysed, or that runs a design with no USB, is still found.
- **Identifying it**, before any test. The check holds the iCE40 in reset and reads the flash's JEDEC ID and 64-bit unique ID over the header with read commands only. It then sets every line back to an input and lets the iCE40 boot from its flash, into foboot, as at power-up. That stops whatever design was running, so only the check does it. The `header` test judges the reading.
- **The board's label** is the flash's unique ID (`flash_uid`): foboot has no USB serial number.
- **The `foboot` test** passes when foboot enumerates on USB within 10 s of the reset: a new enumeration (a new USB device number), not the foboot from before the reset, which can still be listed for a moment after it ([#347](https://github.com/fpgas-online/fpgas.online-test-designs/issues/347)).
- **The UART test.** The check loads the UART test design with openFPGALoader over DFU and runs its host test on `/dev/serial0`. That is the only test that loads a design at boot. A DFU load replaces the bootloader until the next reset, and it writes the design into the flash's user image. So the flash's contents are not part of what `changed` compares; its IDs are.
- **The `foboot-after` step.** When the `header` and `foboot` tests passed, the check ends by resetting the iCE40 through the header again, so foboot is back on USB for the next user. It fails when foboot does not enumerate again within 10 s.
- `fpgas-fomu-debug` runs the `flash`, `pmod` and `pmod-pin-id` (pin identification) tests, one at a time. After each, the Fomu runs a design with no USB. `sudo fpgas-fomu-debug reset` puts foboot back, or the site operator power-cycles the Pi. The PMOD tests assume a PMOD HAT ([Fomu EVT wiring to a Raspberry Pi: not a loopback on the EVT](https://docs.fpgas.online/en/latest/boards/fomu-evt/setup/wiring.html#not-a-loopback-on-the-evt)).
