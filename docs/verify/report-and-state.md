# fpgas-verify: the report and the recorded state

You want to read the check's JSON report, or know what the recorded state holds and when a board is
`changed`.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## The report and the recorded state

* The report, `/run/fpgas-online/verify.json` (this boot's only, `schema_version` 2):

  | Field | Holds |
  |---|---|
  | `result`, `reason` | the result, and why, when no board was checked |
  | `checked_at` | when (UTC, ISO 8601) |
  | `mode`, `configured_by`, `chosen_by` | `auto` or the board, the file (or "command line") that said so, and how the boards were found |
  | `boards[]` | per board: `board`, `variant`, `found`, `result`, `reason` (every fault), `bitstreams`, `tests[]` (`test`, `result`, `reason`, `output`, and what the test read or measured), `identity` ([who the board is](../identity.md)), `state`. The Arty's and NeTV2's also have `jtag`: `result`, `reason`, the [IDCODE's fields](idcode-and-dna.md#the-jtag-idcode), and `dna` or `dna_error` ([the device DNA](idcode-and-dna.md#the-device-dna)). The Acorn's also has `setup`, `running`, `flash`, `not_run`, and `driver` when one was unbound. `not_run` (test: why) is on a Tiny Tapeout board with a chip when its `sdk` test did not pass: `wiring` needs it, so `wiring` is listed there, and the board fails. A TT FPGA board's has `left_running` (`design`, `bitstream`: the design the check loaded last and left), or `warnings` (a list of sentences) when that load failed; a warning never changes `result` |
  | `state` | `file`, and `recorded` (`first run` or `--update`) or `changes` |

  ```bash
  python3 -c 'import json; r = json.load(open("/run/fpgas-online/verify.json")); print(r["result"]); [print(b["board"], t["test"], t["result"]) for b in r["boards"] for t in b.get("tests", [])]'
  ```
* The first run records each board's identity and flash fingerprint in `/var/lib/fpgas-online/verify-state.json`.
  Later runs compare against it; a difference is `changed` until `sudo fpgas-verify --update`.
* Loading a test design and upgrading the packages are not changes. A flash that could not be read is not compared.
* An IDCODE recorded without its version (a record with `schema_version` below 3) takes the whole one
  quietly. On a newer record, another version is a change: it is another chip.
* One swap is missed because of that, once. A NeTV2 on a Pi 3/4 recorded its whole IDCODE even before
  schema 3 (OpenOCD prints it), but the record cannot say whether its value was whole or masked. A version 0
  value looks the same either way. So if such a board's version 0 chip was swapped for a version 1 chip of
  the same part, the first run on schema 3 takes the new IDCODE quietly instead of reporting `changed`.
  Later runs compare the whole IDCODE as usual.
* A device DNA recorded without its leading zeros (a record with `schema_version` below 4) takes the 16-digit
  spelling quietly. Another DNA is a change.
* On a record with `schema_version` below 4, a flash part name that changed while its JEDEC ID and unique ID
  did not is a corrected name, taken quietly: the part is now named from RDID byte 6, so an S25FS256S is no
  longer called an S25FL256S. A different JEDEC ID or unique ID is still a change, and so is a rewritten flash.
* A device DNA missing from a record with `schema_version` below 5 is added quietly, once: until then only the
  Acorn's was read. This goes for every board, so an Acorn whose record has no DNA (neither BAR0 nor JTAG
  read one that run) also gets its DNA added quietly. On a newer record a DNA not recorded before is a
  change, as is another DNA.
* A `--test` run neither records nor compares the state.
