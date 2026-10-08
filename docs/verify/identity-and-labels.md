# fpgas-verify: identity and labels

You have a board checked by `fpgas-verify` and want to print who it is, or make its labels with rpi-hwid.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Identity and labels

Two commands say who the board is, for [rpi-hwid](https://github.com/mithro/rpi-hwid)'s labels. Neither runs
the check, publishes anything or records any state.

| Command | Does |
|---|---|
| `fpgas-verify --identify` (also `--board B`, `fpgas-<board>-verify --identify`, `fpgas-acorn-debug identify`) | prints one identity document (JSON) for every board found |
| `fpgas-verify --label [--out F] [--list]` | reads the identity, then runs `rpi-hwid labels --this-host [--out F] [--list]` to make this Pi's and its board's labels |

`--identify`:

* The document and every field in it are described in [identity.md](../identity.md). It is printed with sorted
  keys and an indent of 1.
* What it reads live:

  | Board | Read live |
  |---|---|
  | Acorn | the running build, device DNA and flash identity over BAR0 (the check's `pcie-bar0`), and the IDCODE and DNA over P1 JTAG (`jtag`) |
  | Arty | the JTAG IDCODE and the device DNA ([the device DNA](idcode-and-dna.md#the-device-dna)) |
  | NeTV2 | the JTAG IDCODE, from the scan that finds it, and the device DNA |
  | Fomu | how the board was found: CDONE on its header, or foboot on USB. Its flash IDs (its label, `flash_uid`) come from the boot report: reading them resets the FPGA |
  | TT FPGA | how the board was found (its USB serial) |

  A TT board's [Tiny Tapeout fields](../identity.md#tiny-tapeout-fields) are not read live: they come from the
  boot report (see below).

* Nothing is loaded into a board and no flash is written. Some reads do change state on the way, and each
  is put back:
  * Acorn, BAR0: memory decoding is switched on in the board's PCI COMMAND register for the read and
    switched off again if it was off. If a kernel driver (litepcie) is bound to the board, it is unbound for
    the read and bound again afterwards. To read the flash's IDs (RDID and OTPR) and its SFDP header (Read
    SFDP), the SoC's SPI master registers and the flash's chip select are written. No other CSR of the SoC
    is written; `--identify` refuses any other write, so the SoC is never reset through `ctrl_reset`.
  * Acorn, P1 JTAG, and NeTV2: openFPGALoader (or openocd) drives the Pi's JTAG GPIOs. Their state is read
    with `pinctrl` first and put back afterwards; a pin that was an output goes back as an input. Without
    `pinctrl` neither the scan nor the DNA read is run.
  * A SIGTERM during the read (rpi-hwid sends one to a slow `--identify`, then SIGKILL) exits 143 after
    putting all of this back and letting go of the locks; a second SIGTERM meanwhile is ignored.
* Each board is read under its lock, as a check is. `--identify` waits at most 30 s for it; a board still in
  use then has its fields missing, for the reason `board busy`. A NeTV2 is also looked for under its lock,
  since finding it drives its JTAG pins; one that could not be looked for, its lock busy, is in the document
  all the same, with its fields missing for that reason, even when other boards were found (`--identify`
  then exits 1). `--identify` holds one board's lock at a time: the NeTV2's is let go after its scan and
  taken again for its read, so no two locks are ever taken in an order that could deadlock with rpi-hwid's
  (acorn < arty < netv2).
* A field only the boot check reads comes from the boot report, `/run/fpgas-online/verify.json`, when the
  board there is this one by a key no other board has: a TT board's `usb_serial`, the Arty's USB serial, the
  Acorn's PCI slot, or the device DNA. These are the Arty's and NeTV2's flash fields, which need a design
  loaded for openFPGALoader's SPI-over-JTAG bridge, and a TT board's Tiny Tapeout fields with
  `tinytapeout_note` or `tinytapeout_error`, which need the port `fpgas-tt.service` holds. Those fields are
  listed in the board's `from_report`. An IDCODE names a part, not a board, so a board known only by its
  IDCODE (a NeTV2 whose DNA could not be read) gets nothing from the report: the fields stay missing, for
  the reason
  `no board-unique match in the boot report`.
* The exit status is 0 when every board's identity is whole (no field missing, no `<field>_error`), 1
  otherwise. Each missing field is printed on stderr with why. The document is printed either way; readers
  use it and ignore the exit status.
* For an Arty or a NeTV2, `--identify` always exits 1 for now: their labels need the flash's unique ID
  (`flash_uid`), and neither the boot check nor `--identify` reads it yet (see [Not done yet](not-done-yet.md#not-done-yet)).
  Their IDCODE and device DNA, and any flash fields the boot report has for them, are still in the document.
* For a TT board, `--identify` exits 0 only when the boot report has the fields rpi-hwid's Tiny Tapeout label
  needs (`mcu`, `chip`, `demoboard`, `demoboard_version`, `sdk`, besides `usb_serial`). So it exits 1 when
  rpi-hwid was not installed at boot.

`--label`:

1. reads the identity, as `--identify` does;
2. releases every board's lock;
3. writes the document to `/run/fpgas-online/identity-<pid>.json`, a new file readable by root alone (it never
   writes over a file or through a link already there);
4. runs `rpi-hwid labels --this-host [--out F] [--list]` with `FPGAS_VERIFY_IDENTITY` set to that file;
5. deletes the file, whatever happened: an error, Ctrl-C, or a SIGTERM (which exits 143).

Its exit status is rpi-hwid's, or 128 + N when rpi-hwid was killed by signal N, as a shell reports it (137
for SIGKILL). It exits 2, saying why, when rpi-hwid is not installed or when the file cannot be written: run it
as root. `--list` (with `--label`) lists the labels rpi-hwid would make; `--out F` is where rpi-hwid writes
them. `--label` writes no report or state and publishes nothing, so `--report`, `--state` and `--no-publish`
are refused with it (exit 2).

Nesting: rpi-hwid gets the board's identity by running `fpgas-verify --identify`. So that the inner run never
waits on a lock the outer run holds, reads a board twice or starts rpi-hwid again, a run with
`FPGAS_VERIFY_IDENTITY` set (an empty value counts as not set):

| Mode | Does |
|---|---|
| `--identify` (and `fpgas-acorn-debug identify`) | checks that the file is an identity document with `identity_version` 1 and prints it unchanged, byte for byte. It takes no lock and runs no board code |
| a missing or bad file | an error (exit 1). It never falls back to reading the hardware |
| any other mode, `--label` included | refuses (exit 2) |

rpi-hwid is a soft dependency:

* fpgas-verify finds the `rpi-hwid` command on `PATH` and runs it. It never imports rpi-hwid's Python code.
* Without it, `--label` exits 2 and says how to install it: `sudo apt install python3-rpi-hwid`, or
  `uv tool install 'rpi-hwid[labels]'` (Python 3.11 or newer).
* The `fpgas-online-verify` deb lists `python3-rpi-hwid` in Suggests. The Python package has a `labels` extra
  (`fpgas-online-verify[labels]`).
* `--identify` does not need rpi-hwid.
