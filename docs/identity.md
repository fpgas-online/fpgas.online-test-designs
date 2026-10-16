# Board identity

fpgas-verify describes each board it finds as one flat set of fields. The same fields are in three places:

* the boot report, `/run/fpgas-online/verify.json`, as each board's `identity`;
* the `fpga-board-identified` event, sent once for each board found;
* the identity document (see [The document](#the-document)).

The field names are [rpi-hwid](https://github.com/mithro/rpi-hwid)'s `FpgaBoard` fields, spelled the same, a
Tiny Tapeout board's `TinyTapeoutBoard` fields, and some fields only fpgas-verify has. The code is
[`identity.py`](../verify/src/fpgas_online_verify/identity.py).

## Rules

* **A missing field was not read.** A field is never present with an empty value. `null` means the field
  was read and there is no value: only a [Tiny Tapeout field](#tiny-tapeout-fields) can be `null`.
* **A read that was tried and failed** gives `<field>_error` instead, with the reason in words: `dna_error`,
  `idcode_error`, `flash_error`, `flash_sfdp_error`, and `tinytapeout_error` for all the Tiny Tapeout
  fields together.
* **Hex identifiers** are lower case, start with `0x`, and have a fixed number of digits. The flash's unique ID
  is the exception: plain hex with no `0x`, as rpi-hwid writes it.
* **Types.** In the report and the document, numbers are JSON numbers and true/false are JSON booleans. In the
  event every value is a string (see [The event](#the-event)).

## Fields

rpi-hwid's `FpgaBoard` fields:

| Field | Type | Value | Missing when |
|---|---|---|---|
| `kind` | string | `acorn`, `arty`, `netv2`, `tt`, `fomu`, `pcileech`, or `unknown-fpga` for a PCIe FPGA design that is not known | never |
| `serial` | string | the USB serial number (Arty: its FT2232H; TT: its RP2350) | the board is not found on USB, or has no USB serial (the Fomu: foboot has none) |
| `dna` | string | the Xilinx device DNA, 16 hex digits: `0x0054b48664b04854` | not read: the board has no DNA (TT, Fomu). The Acorn reads it over BAR0, or over JTAG when BAR0 cannot be used; the Arty and NeTV2 over JTAG (`openFPGALoader --read-dna`). When the JTAG read fails or is not run (the chain did not show the one FPGA expected, or the scan that showed it exited non-zero), `dna_error` says why the DNA itself was not read. A DNA of all zeros or all ones means the DNA port is not being read, so it is no DNA: on the Acorn the other path's is used if it is good, and otherwise `dna_error` says so |
| `idcode` | string | the whole 32-bit JTAG IDCODE, 8 hex digits: `0x13636093` | the board has no JTAG link to the Pi (TT, Fomu), or the JTAG test was not run. The NeTV2 is found by scanning its JTAG chain, so it has the IDCODE that scan read even when its JTAG test is not run |
| `flash` | string | the flash part: `S25FL256S`, `S25FS256S`, told apart by RDID byte 6 (the family ID); the family's name, `S25Fx256S`, when byte 6 is not known. Never sent for the Arty and NeTV2: openFPGALoader's name for the JEDEC ID comes from its own list of parts, not from the chip, and several parts share an ID (the NeTV2's Macronix `0xc22017` does), so rpi-hwid names the family from the JEDEC ID, the extended ID and the SFDP instead | the flash was not read, its part is not known, or (Arty, NeTV2) the chip does not name it |
| `flash_jedec` | string | RDID bytes 1-3, 6 hex digits: `0x010219` | the flash was not read |
| `flash_extended_id` | string | RDID bytes 4-6, 6 hex digits: `0x4d0180` | the flash was not read, or (Arty, NeTV2) its family defines no RDID bytes after the JEDEC ID |
| `flash_sfdp` | string | the SFDP revision the flash answered Read SFDP with, `major.minor`: `1.6`; or `none` when its answer has no SFDP signature, which is what an S25FL256S gives (see [SFDP](#sfdp)) | the flash was not read; `flash_sfdp_error` says why when the flash's IDs were read but Read SFDP failed |
| `flash_uid` | string | the flash's factory unique ID, plain hex | the flash was not read, or `flash_uid_state` is not `read` |
| `flash_uid_bits` | number | the unique ID's length in bits: `128` | the flash was not read, or `flash_uid_state` is `none` |
| `flash_uid_state` | string | `read`; `blank` when every byte read is `00` or `ff`; `none` (Arty, NeTV2) when no unique ID was read: with `flash_uid_note` the chip said it has none, without it openFPGALoader knows no unique ID command for the part, which says nothing about the chip (rpi-hwid makes no label then) | the flash was not read |
| `flash_uid_note` | string | why a flash with `flash_uid_state` `none` has no unique ID, in the chip's own words: `no factory ESN: …`, as openFPGALoader gives it | `flash_uid_state` is not `none`, or openFPGALoader knows no unique ID command for the part |
| `flash_error` | string | why the flash could not be read | the flash was read, or reading it was not tried |
| `flash_source` | string | how the flash was read: `pcie` through the Acorn's own SoC; `header` over the Pi's header with the FPGA held in reset (the Fomu); `jtag` through openFPGALoader's SPI-over-JTAG bridge, which replaced the running design (the Arty, the NeTV2) | the flash was not read |
| `soc_model` | string | the card the Acorn's SoC says it was built for, from the variant its identifier string names: `cle-215+`, `cle-101` (as rpi-hwid reads it) | not an Acorn running our SoC (SQRL's factory image, a design we do not know), BAR0 could not be read, or the identifier names no variant |

fpgas-verify's own fields:

| Field | Type | Value | Missing when |
|---|---|---|---|
| `board` | string | the board's name in the state and the events: `acorn`, or `acorn@0001:01:00.0` when there are two of a kind | never |
| `variant` | string | the board's variant: `a7-35`, `cle-215+` | the variant is not known |
| `bdf` | string | the PCI slot: `0001:01:00.0` | not a PCIe board |
| `usb` | string | the USB path: `1-1.2` | not a USB board |
| `identifier` | string | the identifier string of the build the Acorn runs | not an Acorn running a design we built, or BAR0 could not be read |
| `build` | string | which build of the installed release runs: `operational` or `golden` | the identifier is not one of the release's builds |
| `idcode_version` | number | IDCODE bits 31-28, the silicon revision | as `idcode` |
| `idcode_part_number` | string | IDCODE bits 27-12, 4 hex digits: `0x3636` | as `idcode` |
| `idcode_manufacturer_id` | string | IDCODE bits 11-1, the JEP106 code, 3 hex digits: `0x049` | as `idcode` |
| `idcode_manufacturer` | string | `Xilinx`, `Lattice`, or `unknown` | as `idcode` |
| `idcode_device` | string | `XC7A200T`, or `unknown` | as `idcode` |
| `flash_size_bytes` | number | the flash's size from its RDID (Arty, NeTV2: the SFDP's density, or openFPGALoader's size when it did not take it from its list of parts): `33554432` | the flash was not read, or its RDID gives no size |
| `flash_status` | string | status register 1, 2 hex digits: `0x00` | the flash was not read |
| `flash_config` | string | the configuration register, 2 hex digits: `0x02` | the flash was not read |
| `flash_quad` | boolean | the configuration register's QUAD bit | the flash was not read |
| `flash_uid_opcode` | string | the command that read the unique ID: `0x4b` | as `flash_uid_bits` |
| `tinytapeout_note` | string | why the [Tiny Tapeout fields](#tiny-tapeout-fields) were not read: rpi-hwid is not installed (the board then has no `variant`, and its check is an error) | not a TT board, or rpi-hwid is installed |
| `tinytapeout_error` | string | why rpi-hwid could not give the Tiny Tapeout fields: it failed, gave no usable answer, did not see the board, found no Tiny Tapeout SDK on it, gave an empty field, or could not read `mcu`, `chip`, `demoboard` or `sdk` | not a TT board, rpi-hwid gave the fields, or it is not installed |

### Tiny Tapeout fields

A TT board's fields are rpi-hwid's `TinyTapeoutBoard` fields, under its names. The site makes rpi-hwid's Tiny
Tapeout label from them. Except `usb_serial`, they come from `rpi-hwid tinytapeout --json --no-stop-service`,
which the boot check runs while it holds the board's port (see [fpgas-verify: TT FPGA identity](verify/tt-fpga.md#tt-fpga-identity)).
rpi-hwid gives `null` for a field it read and found no value for: the TT FPGA has no shuttle, for example.
Every TT FPGA board has an `mcu`, `chip`, `demoboard` and `sdk`, so rpi-hwid giving `null` for one of those
means its read failed: the identity then has `tinytapeout_error` instead of the Tiny Tapeout fields. A field
rpi-hwid leaves out was not read, and is missing from the identity too.

| Field | Type | Value | Missing when |
|---|---|---|---|
| `usb_serial` | string | the RP2350's USB serial number, the same as `serial`; the site drops a TT board without it | the board is not found on USB |
| `mcu` | string | the demo board's microcontroller: `RP2350`, `RP2040` | rpi-hwid did not read the board (`tinytapeout_note` or `tinytapeout_error` says why), or did not give the field |
| `shuttle` | string or null | the Tiny Tapeout shuttle of the chip, from its ROM: `tt06` | as `mcu` |
| `chip` | string | `asic`, or `fpga` for the FPGA breakout | as `mcu` |
| `repo` | string or null | the chip's repository, from its ROM | as `mcu` |
| `commit` | string or null | the chip's commit, from its ROM | as `mcu` |
| `demoboard` | string | the demo board as the SDK detected it: `TTDBv3 [3.2]` | as `mcu` |
| `demoboard_version` | string or null | the demo board version that shipped with the shuttle's kit: `v2.0.1` | as `mcu` |
| `sdk` | string | the Tiny Tapeout SDK release on the board | as `mcu` |

## SFDP

SFDP (Serial Flash Discoverable Parameters, JEDEC JESD216) is a table a flash keeps about itself, read with
the Read SFDP command: opcode `5Ah`, a 3-byte address, then 8 dummy clocks. The Acorn reads the 8-byte header
at address 0 through its SoC's SPI master, the same way as the flash's IDs: it is a read, writes nothing to
the flash, and is part of `--identify`. In the header, bytes 0-3 are the signature, the ASCII letters `SFDP`;
byte 4 is the minor revision and byte 5 the major revision. `flash_sfdp` is `major.minor`, or `none` when the
first four bytes are not the signature. An answer shorter than 8 bytes is not a read, and gives no
`flash_sfdp`.

The Acorn's S25FL256S has no SFDP. Its datasheet (Infineon 002-19099 Rev. *D, S25FL128S/S25FL256S) has no
`5Ah` in its command summary (section 13.1) and does not mention SFDP. The part describes itself only in its
ID-CFI space, read with RDID (sections 7.3, 11.2.2 and 13.2). Read SFDP is not one of its commands, so its
answer has no signature and `flash_sfdp` should be `none`. This comes from the datasheet. The S25FS256S, the 1.8 V part of the same family, does answer Read SFDP. rpi-hwid
uses `flash_sfdp` to tell an S25FL127S (which has SFDP) from an S25FL128S (which has not), parts that share
their RDID bytes.

A failed Read SFDP gives `flash_sfdp_error` and fails the Acorn's `pcie-bar0` test; the flash's other fields
still stand.

## What each board has

| Board | Fields |
|---|---|
| Acorn | `board`, `kind`, `variant`, `soc_model`, `bdf`, `identifier`, `build`, `dna`, the IDCODE fields, and every flash field |
| Arty | `board`, `kind`, `variant`, `serial`, `usb`, `dna`, the IDCODE fields, and the [flash fields read over JTAG](#the-arty-and-netv2-flash) (or `flash_error`) |
| NeTV2 | `board`, `kind`, `variant`, `dna`, the IDCODE fields, and the [flash fields read over JTAG](#the-arty-and-netv2-flash) (or `flash_error`) |
| TT | `board`, `kind`, `variant`, `serial`, `usb`, and the Tiny Tapeout fields (or `tinytapeout_note`, or `tinytapeout_error`) |
| Fomu | `board`, `kind`, `variant`, `usb` (when foboot came back after the reset), and the flash fields read over the header: `flash`, `flash_jedec`, `flash_size_bytes`, `flash_status`, `flash_uid`, `flash_uid_bits`, `flash_uid_state`, `flash_uid_opcode`, `flash_source` (or `flash_error`) |

## The Arty and NeTV2 flash

The boot check reads the flash's identity with `openFPGALoader --flash-info-json FILE`, over the board's JTAG:
`-b arty` on the Arty; on the NeTV2 the header's pins (`--pins 27:22:4:17`, `libgpiod` on a Pi 3/4, `rp1pio` on a
Pi 5) with `--fpga-part xc7a35tfgg484` or `xc7a100tfgg484`. Only the fpgas.online builds of openFPGALoader have
`--flash-info-json`. It writes a JSON document, `{"format": "openFPGALoader-flash-info", "version": 2,
"flashes": [...]}`, and the check takes only version 2 of that format, with exactly one flash. It gives:

| Field | From the document |
|---|---|
| `flash_jedec` | `jedec_id` |
| `flash_extended_id` | `extended_id`, when not `null` |
| `flash_size_bytes` | the SFDP's `bfpt.density_bits` / 8, the chip's own; else `size_bytes` unless its `size_source` is `database`. `part` is not taken: it is always openFPGALoader's database |
| `flash_uid_state` | `unique_id.state`: `read`, `blank` or `none` |
| `flash_uid`, `flash_uid_bits`, `flash_uid_opcode` | `unique_id.value` (when `read`), `bits` and `opcode` (when `read` or `blank`) |
| `flash_uid_note` | `unique_id.note`, when the state is `none` and the note is not `null` |
| `flash_sfdp` | `sfdp.revision`, or `none` when `sfdp` is `null` (the part has no SFDP) |
| `flash_source` | `jtag` |

* openFPGALoader reaches the flash through its SPI-over-JTAG bridge: it loads the bridge in place of the
  running design, and afterwards the FPGA reloads from its flash. So the check reads it after the JTAG test
  (IDCODE and device DNA) has passed and before it loads any test design, and before it sends
  `fpga-board-identified`, which carries the fields. `--identify` loads nothing, so it never reads them: they
  come from the boot report.
* A read that fails gives `flash_error`, and the board's result is `error`, its reason naming it: openFPGALoader
  could not run, exited non-zero, wrote no file (it writes none when a unique ID or SFDP read fails), or wrote
  one that is not JSON, not version 2 of that format, does not have exactly one flash, or reads all `00` or `ff`
  as a unique ID it says it read. When the JTAG test did not pass, the flash is not read and `flash_error` says
  so; the JTAG test has already failed the board.
* The state's `flash_jedec`, compared from one run to the next, is this `flash_jedec`. The `flash` test's design
  prints the JEDEC ID it reads too; that stays in its test entry.

## The event

`fpga-board-identified` carries the fields as flat `key=value` strings:

* strings as they are;
* numbers in decimal: `flash_size_bytes=33554432`;
* booleans as `true` or `false`: `flash_quad=true`;
* a list or object as one key whose value is compact JSON with sorted keys: `["a","b"]`, holding only strings,
  whole numbers, booleans, null, and lists and objects of those (object keys are strings) at any depth;
* `-` only for a field that was read and has no value; a field that was not read is left out;
* plus `schema=fpga-identity/1`.

The Acorn sends it once PCIe and JTAG have said who it is; every other board sends it before its tests. A board
whose check stops before it says who the board is, or that is not checked at all (`--test` naming none of its
tests), still gets one, with what finding the board showed (for the NeTV2, the IDCODE fields). In
`fpga-verified` the same fields appear per board as `board0_identity_<field>`. A field whose value has no
event form (a bug in the board's module) is left out of both, and that board's result is `error`, its
reason naming the field; the other boards are still checked.

## The Pi's own facts: `pi-identified`

The Pi's label needs facts about the Pi that its registration does not carry: what is on its 40-pin header
(the HAT's EEPROM), its power class and, on a Pi 5, the fan and the RTC battery. At every boot, before any
board's lock is taken, the boot check runs `rpi-hwid label-input --pi-only` and sends what it read as one
`pi-identified` event, once the boards are found ([`pi_identity.py`](../verify/src/fpgas_online_verify/pi_identity.py); rpi-hwid's
`docs/LABEL-CONTRACT.md`, section 5). The site puts these with the registration's model, serial, revision,
memory and MACs, and makes the Pi's label.

| Detail | Value |
|---|---|
| `schema` | `pi-identity/1` |
| `reader` | `rpi-hwid`, or `none` when rpi-hwid is not installed (then no other field is sent) |
| `reader_error` | why rpi-hwid did not give the facts: it failed, did not finish, or printed something that is not a label input |
| `user_bus` | what became of the scan of the header's user bus (GPIO2/3), sent with the facts: `not needed` (the ID bus or the firmware gave the header), `scanned`, `scanned: header not read` (rpi-hwid could not read that bus either), `scan failed` (with the scan's `reader_error`), `skipped: <board> wired to GPIO2/3`, `skipped: Compute Module`, `skipped: compatible not read`, `skipped: rpi-hwid too old` (the installed rpi-hwid does not say it leaves the Pi as found), or `skipped: boards not known: <why>` |
| `compatible`, `power_class`, `hat_uuid`, `fan`, `rtc_battery`, `max_current_ma`, `ext5v_v`, `header`, `macs`, `usb_net` | rpi-hwid's `Summary` fields of the same names, as `--pi-only` read them |

The values are encoded as in [the event](#the-event) above, and a decimal (`ext5v_v`) is written as a decimal
number: `5.08`. `header`, `macs` and `usb_net` are each one key of compact JSON. A `header` nobody read (nothing on
the HAT ID bus named a HAT) is left out, never sent as `[]`, so the site refuses the label rather than print
"HAT none": a HAT known only by its chips on the user bus (a Waveshare PoE HAT (B)) is invisible on the ID bus.

So when the ID bus gave no header, the boot check scans the user bus (GPIO2/3, I2C1) for one by running
`rpi-hwid label-input --pi-only --user-bus` again (Tim, 17 Oct 2026, coord-78: "(B) User-bus scan per setup"). It
asks this only of an rpi-hwid whose first read says `sources.header_buses = "as-found"` (mithro/rpi-hwid #93): one
that reads the bus without a `dtparam` or a module (bit-banged through the GPIO character device, or through an
`/dev/i2c-1` already there), only reads on it (one-byte reads at each address), and puts back and checks every bus
pin's function and pad and the loaded i2c modules, or exits 1 (a `reader_error`). An older rpi-hwid is not asked
(`skipped: rpi-hwid too old`): 0.0.post597's `--user-bus` applied the `i2c_arm` dtparam at runtime and left a Pi 5's
GPIO2/3 muxed and two i2c modules loaded while saying it had put everything back (17 Oct 2026). The read is the
whole `--pi-only` read again, bounded by the same 120 s. It does so after finding the boards and before taking any board's lock, and only where no board is wired
to GPIO2/3: neither a board it found nor the one the host is set up for (`fpga-board = <board>`, found or not).
Each board's definition says whether it is (`Board.user_bus`), held by a test to the board's wiring source; a board
that does not say counts as wired:

| Board | Wired to GPIO2/3 | Wiring source |
|---|---|---|
| Sqrl Acorn | yes: P2's J5 is GPIO3 | `designs/_shared/acorn_p2.py` |
| Digilent Arty A7 | yes: the Pmod HAT's JB9/JB10 | `identify_pmod_pins.BOARDS["arty"]` |
| TT FPGA Demo Board | yes: the Pmod HAT's JB9/JB10 | `identify_pmod_pins.BOARDS["tt"]` |
| Fomu EVT | no | `boards/fomu.py` `HEADER_GPIOS`, CRESET, CDONE, the UART |
| Kosagi NeTV2 | no | `boards/netv2.py` `JTAG_GPIOS`, the UART |

A Pi with no board (the check's result is `missing`) is scanned, unless the host is set up for a wired board. A
Compute Module is never scanned, as rpi-hwid leaves it alone by itself: its header pins are the carrier's (a Compute
Blade has an Acorn's JTAG on GPIO2/3); nor is a Pi whose `compatible` was not read, since whether it is one is then
not known. Nor is a Pi whose boards could not be looked for (the search failed or
crashed): `skipped: boards not known`, sent before the check goes on. The Arty and TT FPGA hosts' Pmod HAT and the
Acorn hosts' HAT+ carry an ID EEPROM, so their header comes from the ID bus and the scan is not needed there. With
the scan, a header found empty on both buses is read, none (`[]`, "HAT none" on the label), as rpi-hwid's contract
says; without it the header stays not read, and `user_bus` says why.

A `reader_error` is said in the event and in the boot report (`pi`), and the check's summary says the Pi's own
facts were NOT READ; the site refuses the Pi's own label and shows the reason. The boards' result is untouched: a
Pi-label read is not a board test (the coordinator's decision of 17 Oct 2026, from Tim's rules of 5 Oct, fixes never
take visitor controls away, and 16 Oct, "fail until tested" is about a board's planned checks). `--pi-only` (rpi-hwid 0.0.post597 and later, mithro/rpi-hwid
#92) reads the HAT's EEPROM over GPIO0/1 itself, as an I2C master through the GPIO character device, with no
`dtparam` and no module loaded; where `/dev/i2c-0` already exists it reads through that. It reads each pin's
function and pull before and after and puts them back, and anything it cannot read or put back is an error
(exit 1), which here is a `reader_error`. rpi-hwid's stdout is the document; what it says on stderr is kept apart,
and named in the reason when it fails. `--test` runs and
`fpgas-<board>-debug` do not read the Pi. The report keeps the read as `pi`.

## The document

The identity document holds the fields of every board found:

```json
{
 "schema": "fpgas-verify/identity",
 "identity_version": 1,
 "tool": "fpgas-online-verify 0.0.post808",
 "read_at": "2026-10-02T00:00:00+00:00",
 "source": "live",
 "boards": [{"board": "acorn", "kind": "acorn", "dna": "0x0054b48664b04854", "...": "..."}]
}
```

`source` is always `live`. A run inside `fpgas-verify --label` prints the outer run's document byte for byte,
so it says `live` too.

[`tests/data/identity-v1-acorn-p48.json`](../tests/data/identity-v1-acorn-p48.json) is an example: an
Acorn CLE-215+ on a Raspberry Pi 5. rpi-hwid keeps a byte-identical copy and tests its reader on it. It is exactly what
that board printed, which did not include `flash_sfdp`.

## Versions

* The event's `schema` is `fpga-identity/1`, and the document's `identity_version` is `1`.
* Version 1 may gain new fields. A reader ignores fields it does not know.
* Renaming or removing a field, or changing a value's type or spelling, makes version 2.
* A reader refuses any version other than the one it knows.
