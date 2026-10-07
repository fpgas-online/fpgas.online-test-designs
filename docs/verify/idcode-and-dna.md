# fpgas-verify: the JTAG IDCODE and the device DNA

You have an Acorn, Arty or NeTV2 and want to know how the check reads and judges its FPGA's JTAG IDCODE and
device DNA.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## The JTAG IDCODE

Every board with JTAG has its FPGA's whole 32-bit IDCODE read and decoded
([`idcode.py`](../../verify/src/fpgas_online_verify/idcode.py)):

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

## The device DNA

The Acorn, Arty and NeTV2 have their FPGA's device DNA read: a 57-bit number fused into each chip, different on
every one ([`dna.py`](../../verify/src/fpgas_online_verify/dna.py)).

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
* A good DNA is `dna` in the `jtag` entry, the [identity](../identity.md) and the recorded state, as 16 hex digits
  (`0x0054b48664b04854`). Otherwise the identity has `dna_error`, with why.

openFPGALoader has `--read-dna` from 0.13.0:

| openFPGALoader | `--read-dna` |
|---|---|
| Debian bookworm's (0.10.0) | no, so the board packages need 0.13.0 or later: on bookworm, fpgas.online's |
| 0.13.0 and later, and fpgas.online's `openfpgaloader-fpgasonline` (1.1.1) and `openfpgaloader-fpgasonline-git` | yes, over any JTAG cable: the read is in openFPGALoader's Xilinx code (`Xilinx::fuse_dna_read` in `src/xilinx.cpp`), after the cable is open. That covers `-b arty` (its `digilent` FT2232 cable), `libgpiod`, and `rp1pio` (fpgas.online's builds only) |
