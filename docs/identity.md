# Board identity

fpgas-verify describes each board it finds as one flat set of fields. The same fields are in three places:

* the boot report, `/run/fpgas-online/verify.json`, as each board's `identity`;
* the `fpga-board-identified` event, sent once for each board found;
* the identity document (see [The document](#the-document)).

The field names are [rpi-hwid](https://github.com/mithro/rpi-hwid)'s `FpgaBoard` fields, spelled the same, plus
some fields only fpgas-verify has. The code is
[`identity.py`](../verify/src/fpgas_online_verify/identity.py).

## Rules

* **A missing field was not read.** A field is never present with an empty or null value.
* **A read that was tried and failed** gives `<field>_error` instead, with the reason in words: `dna_error`,
  `idcode_error`, `flash_error`.
* **Hex identifiers** are lower case, start with `0x`, and have a fixed number of digits. The flash's unique ID
  is the exception: plain hex with no `0x`, as rpi-hwid writes it.
* **Types.** In the report and the document, numbers are JSON numbers and true/false are JSON booleans. In the
  event every value is a string (see [The event](#the-event)).

## Fields

rpi-hwid's `FpgaBoard` fields:

| Field | Type | Value | Missing when |
|---|---|---|---|
| `kind` | string | `acorn`, `arty`, `netv2`, `tt`, `fomu`, `pcileech`, or `unknown-fpga` for a PCIe FPGA design that is not known | never |
| `serial` | string | the USB serial number (Arty: its FT2232H; TT: its RP2350; Fomu: its bootloader) | the board is not found on USB |
| `dna` | string | the Xilinx device DNA, 16 hex digits: `0x0054b48664b04854` | not read: only the Acorn reads it, over BAR0, or over JTAG when BAR0 cannot be used |
| `idcode` | string | the whole 32-bit JTAG IDCODE, 8 hex digits: `0x13636093` | the board has no JTAG link to the Pi (TT, Fomu), or the JTAG test was not run |
| `flash` | string | the flash part: `S25FL256S`, `S25FS256S`, told apart by RDID byte 6 (the family ID); the family's name, `S25Fx256S`, when byte 6 is not known | the flash was not read, or its part is not known |
| `flash_jedec` | string | RDID bytes 1-3, 6 hex digits: `0x010219` | the flash was not read |
| `flash_extended_id` | string | RDID bytes 4-6, 6 hex digits: `0x4d0180` | the flash was not read |
| `flash_uid` | string | the flash's factory unique ID, plain hex | the flash was not read |
| `flash_uid_bits` | number | the unique ID's length in bits: `128` | as `flash_uid` |
| `flash_uid_state` | string | `read`, or `blank` when every byte is `00` or `ff` | as `flash_uid` |
| `flash_error` | string | why the flash could not be read | the flash was read, or reading it was not tried |
| `flash_source` | string | how the flash was read: `pcie` through the Acorn's own SoC | the flash was not read |
| `soc_model` | string | the Acorn variant its SoC was built for: `cle-215+`, `cle-101` | not an Acorn, or the variant is not known |

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
| `flash_size_bytes` | number | the flash's size from its RDID: `33554432` | the flash was not read, or its RDID gives no size |
| `flash_status` | string | status register 1, 2 hex digits: `0x00` | the flash was not read |
| `flash_config` | string | the configuration register, 2 hex digits: `0x02` | the flash was not read |
| `flash_quad` | boolean | the configuration register's QUAD bit | the flash was not read |
| `flash_uid_opcode` | string | the command that read the unique ID: `0x4b` | as `flash_uid` |

## What each board has

| Board | Fields |
|---|---|
| Acorn | `board`, `kind`, `variant`, `soc_model`, `bdf`, `identifier`, `build`, `dna`, the IDCODE fields, and every flash field |
| Arty | `board`, `kind`, `variant`, `serial`, `usb`, the IDCODE fields |
| NeTV2 | `board`, `kind`, `variant`, the IDCODE fields |
| TT | `board`, `kind`, `variant`, `serial`, `usb` |
| Fomu | `board`, `kind`, `variant`, `serial`, `usb` |

## The event

`fpga-board-identified` carries the fields as flat `key=value` strings:

* strings as they are;
* numbers in decimal: `flash_size_bytes=33554432`;
* booleans as `true` or `false`: `flash_quad=true`;
* a list or object as one key whose value is compact JSON with sorted keys: `["a","b"]`;
* `-` only for a field that was read and has no value; a field that was not read is left out;
* plus `schema=fpga-identity/1`.

The Acorn sends it once PCIe and JTAG have said who it is; every other board sends it before its tests. A board
whose check stops before it says who the board is, or that is not checked at all (`--test` naming none of its
tests), still gets one, with what finding the board showed. In
`fpga-verified` the same fields appear per board as `board0_identity_<field>`.

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

[`tests/data/identity-v1-acorn-p48.json`](../tests/data/identity-v1-acorn-p48.json) is a complete example: the
Acorn on pi-sw2-p48. rpi-hwid keeps a byte-identical copy and tests its reader on it.

## Versions

* The event's `schema` is `fpga-identity/1`, and the document's `identity_version` is `1`.
* Version 1 may gain new fields. A reader ignores fields it does not know.
* Renaming or removing a field, or changing a value's type or spelling, makes version 2.
* A reader refuses any version other than the one it knows.
