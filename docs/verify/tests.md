# fpgas-verify: what an Arty, NeTV2, Fomu or TT FPGA check tests

You have an Arty, NeTV2, Fomu or TT FPGA board and want to know what each test of its check does and when
it passes.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## What each board's check tests

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
| Fomu EVT | USB `1209:5bf0` (DFU bootloader) | openFPGALoader over DFU | `/dev/serial0` | `uart` | `spiflash`, `pmod`, `pin-id` | USB serial |
| TT FPGA | USB `2e8a:0005`, `2e8a:000f` (and `2e8a:0003`, the RP2's boot loader, which fails) | `tt_fpga_program.py` over `mpremote` | `/dev/ttyACM0` | `sdk` (loads nothing), `pin-id`, `uart`; a board with a Tiny Tapeout chip: `sdk` only, and it fails until its wiring test exists | `pmod` | USB serial |

* The Arty and NeTV2 are left running openFPGALoader's SPI-over-JTAG bridge (used to read the flash back), the
  Fomu its test design, and the TT FPGA a design that moves its display
  ([what the TT FPGA is left running](tt-fpga.md#what-the-tt-fpga-is-left-running)). Each returns to its flash image at
  its next power cycle (the TT FPGA has none: it is empty until something is loaded).
* The Arty and NeTV2 have their whole JTAG IDCODE read and decoded before the tests
  ([the JTAG IDCODE](idcode-and-dna.md#the-jtag-idcode)): a part that is not the variant's fails the board. Then their device
  DNA is read over the same JTAG ([the device DNA](idcode-and-dna.md#the-device-dna)): one that cannot be read, or is all zeros
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
  started even when the check is interrupted or the report cannot be written. While it is stopped, and before the first test, rpi-hwid reads who the board is ([TT FPGA identity](tt-fpga.md#tt-fpga-identity)).
* The NeTV2 has no USB, so finding it means driving the GPIO header. With `fpga-board = auto` the JTAG scan
  runs only if nothing was found on USB or PCI (or only a Xilinx PCIe design the Acorn check cannot name);
  `--no-probe` turns it off.
