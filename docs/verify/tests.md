# fpgas-verify: what an Arty, NeTV2, Fomu or TT FPGA check tests

You have an Arty, NeTV2, Fomu or TT FPGA board and want to know what each test of its check does and when
it passes.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## What the check tests on each board

### Arty, NeTV2, Fomu and TT FPGA

Each test checks its bitstream's sha256 against the `-bitstreams` package's manifest (a damaged file is an
`error`, never loaded), loads it, runs its host script, and passes when the script exits 0
([`testbench.py`](../../verify/src/fpgas_online_verify/testbench.py)).

| Test | Host script | Passes when |
|---|---|---|
| `uart` | [`test_uart.py`](../../designs/uart/host/test_uart.py) | the LiteX BIOS banner arrives (Arty only) and printable ASCII echoes back |
| `ddr` | [`test_ddr.py`](../../designs/ddr-memory/host/test_ddr.py) | the BIOS reports DRAM calibration and `Memtest OK` |
| `spiflash` | [`test_spiflash.py`](../../designs/spi-flash-id/host/test_spiflash.py) | the design reads the flash's JEDEC ID and prints `SPI_FLASH_TEST: PASS` |
| `ethernet` | [`test_ethernet.py`](../../designs/ethernet-test/host/test_ethernet.py) | the design answers ARP and ping through the Pi's USB Ethernet adapter (192.168.1.100/24 on that adapter only) |
| `pin-id` | [`identify_pmod_pins.py`](../../designs/pmod-pin-id/host/identify_pmod_pins.py) | each Pmod HAT GPIO the test covers receives the FPGA ball name the expected cabling puts there. TT FPGA: all 24 signal wires of the three ribbons, each on its own (the six that share three Pi pins send in turns). Arty: 18 of 24 (not the six on the shared pins). The test's last lines say which |
| `pmod` | [`test_pmod_loopback.py`](../../designs/pmod-loopback/host/test_pmod_loopback.py) | the loopback wiring reads back; `-debug` only |

| Board | Found by | Loaded with | UART | Boot-check tests, in order | Only in `-debug` | Recorded state |
|---|---|---|---|---|---|---|
| Arty A7 | USB `0403:6010` | `openFPGALoader -b arty` | `/dev/ttyUSB1` | `uart`, `ddr`, `spiflash`, `ethernet`, `pin-id` | `pmod` | FTDI serial, IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's first 2.1 MiB |
| NeTV2 | JTAG IDCODE over GPIO 4/17/27/22 | openocd (Pi 3/4), openFPGALoader `rp1pio` (Pi 5) | `/dev/ttyAMA0` | `uart`, `ddr`, `spiflash` | `ethernet`, `pmod`, `pin-id` | IDCODE, device DNA, flash JEDEC ID, sha256 of the flash's boot image |
| Fomu EVT | CDONE high on the Pi's header (GPIO17), or USB `1209:5bf0` (foboot) | openFPGALoader over DFU | `/dev/serial0` | `header`, `foboot` (both load nothing), `uart` | `spiflash`; `pmod` and `pin-id`, which cannot pass on the EVT ([#202](https://github.com/fpgas-online/fpgas.online-test-designs/issues/202)) | the flash's JEDEC ID and unique ID, read over the header |
| TT FPGA | USB `2e8a:0005`, `2e8a:000f` (and `2e8a:0003`, the RP2's boot loader, which fails) | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | `sdk` (loads nothing), `dip-switches`, `pin-id`, `uart`; a board with a Tiny Tapeout chip: `sdk`, then `wiring` (nothing is loaded) | `pmod` | USB serial |

* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  Fomu its test design, and the TT FPGA a design that moves its display
  ([what the TT FPGA is left running](tt-fpga.md#what-the-tt-fpga-is-left-running)). Each returns to its flash image at
  its next power cycle (the TT FPGA has none: it is empty until something is loaded).
* The Arty and NeTV2 have their whole JTAG IDCODE read and decoded before the tests
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
  with a unique ID that is not all `00` or all `ff`. `foboot` passes when foboot is on USB within 10 s of the
  reset: the DFU loads need it.
* The Fomu runs only `uart` at boot: a DFU load replaces the bootloader until the next reset.
* The TT FPGA's `fpgas-tt.service` is stopped for the tests and started again once the report is written, so
  it never starts against the report of the run before. If it cannot be started again the result is `error`
  and the report says so, in `services_failed` at the top of the report: the board's own entry keeps the
  result of its tests, and the state recorded for it stands, since the board itself was read. The service is
  started even when the check is interrupted or the report cannot be written. While it is stopped, and before the first test, rpi-hwid reads who the board is ([TT FPGA identity](tt-fpga.md#tt-fpga-identity)).
* The NeTV2 has no USB, so finding it means driving the GPIO header. With `fpga-board = auto` the JTAG scan
  runs only if nothing was found on USB or PCI (or only a Xilinx PCIe design the Acorn check cannot name);
  `--no-probe` turns it off.

### The Arty A7 check at boot

The check finds the Arty by its FT2232H on USB (`0403:6010`). Then, in this order:

1. It reads the FPGA's whole JTAG IDCODE over that FT2232H. It must be an XC7A35T, in any silicon version. The
   report's `jtag` has it decoded (`idcode_version`, `idcode_device` and the others:
   [the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)).
2. It reads the device DNA with `openFPGALoader -b arty --read-dna` over the same FT2232H, which loads nothing.
   A DNA that cannot be read, or is all zeros or all ones, fails the board
   ([the device DNA](idcode-and-dna.md#the-device-dna)).
3. It loads the UART, DDR, SPI flash, Ethernet and PMOD pin identification test designs into SRAM with
   openFPGALoader, one at a time, and runs each one's host test.
4. It reads back the flash's boot image region (the first 2.1 MiB) through openFPGALoader's SPI-over-JTAG
   bridge.

About two of the tests:

- The Ethernet test pings the design through the Pi's USB Ethernet adapter cabled to the Arty's RJ45. It never
  touches an interface the Pi uses itself.
- The pin identification scan checks the PMOD HAT cabling against the expected map (HAT JA/JB/JC to Arty
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
3. It loads the UART, DDR and SPI flash test designs into SRAM, and runs each design's host test on
   `/dev/ttyAMA0`.
4. It reads back the flash's boot image region.

What `changed` compares is the IDCODE, the device DNA, the flash's JEDEC ID and the sha256 of that flash region.

### The Fomu EVT check at boot

The EVT sits on the Pi's GPIO header ([Fomu EVT wiring to a Raspberry Pi](https://docs.fpgas.online/en/latest/boards/fomu-evt/setup/wiring.html#connections-to-the-pi)).

How the check works with it:
- **Finding it.** The check reads the iCE40's CDONE (GPIO17), which drives nothing: high means the board is there and running a design. foboot's DFU bootloader on USB (`1209:5bf0`) finds it too, but is not needed. A Fomu whose USB is being analysed, or that runs a design with no USB, is still found.
- **Identifying it**, before any test. The check holds the iCE40 in reset and reads the flash's JEDEC ID and 64-bit unique ID over the header with read commands only. It then sets every line back to an input and lets the iCE40 boot from its flash, into foboot, as at power-up. That stops whatever design was running, so only the check does it. The `header` test judges the reading.
- **The board's label** is the flash's unique ID (`flash_uid`): foboot has no USB serial number.
- **The `foboot` test** passes when foboot appears on USB within 10 s of the reset.
- **The UART test.** The check loads the UART test design with openFPGALoader over DFU and runs its host test on `/dev/serial0`. That is the only test that loads a design at boot. A DFU load replaces the bootloader until the next reset, and it writes the design into the flash's user image. So the flash's contents are not part of what `changed` compares; its IDs are.
- `fpgas-fomu-debug` runs the SPI flash, PMOD loopback and pin identification tests, one per power cycle. The PMOD tests assume a PMOD HAT ([not a loopback on the EVT](../hardware/fomu-pin-mapping.md#not-a-loopback-on-the-evt)).
