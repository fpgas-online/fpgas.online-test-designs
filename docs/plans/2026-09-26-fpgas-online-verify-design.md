# fpgas-online-verify: boot-time FPGA board verification, packaged per board

Date: 2026-09-26. Status: implemented (`verify/`, `packaging/debs/`); the non-Acorn boards not yet run on hardware.

## What it is for

A Raspberry Pi with an FPGA board attached checks, at boot, that the board and its wiring to the Pi work, by
loading the fpgas.online test bitstreams and running their host tests. Three ways of setting a host up:

1. **One board, persistent storage.** `apt install fpgas-online-arty` on a Pi that has an Arty. The check runs
   only the Arty's verify; no Arty found is a loud, fatal error, even if some other board is attached. Only the
   Arty's bitstreams and tooling are installed.
2. **The netboot root.** `apt install fpgas-online-all-boards` into the NFS root. Every board's tooling is
   there; at boot each Pi finds which board it has and runs that verify. Finding none is fatal.
3. **Several boards, by choice, persistent storage.** `apt install fpgas-online-all-boards` (every board) or
   `fpgas-online-multi-board` plus the board tool packages wanted. As 2. Installing two boards must be a
   deliberate choice: the per-board packages conflict with each other and with the multi-board ones.

On a host with persistent storage, the verify also remembers the board it found and what its flash holds: a
different board, or a changed flash (a new image written to it), is a loud, fatal "changed" result until
`fpgas-verify --update` accepts it (run it after flashing on purpose). Loading a design into SRAM (every
verify does) and upgrading the packages are not changes. A netboot root keeps /var/lib in tmpfs, so there
every boot is a first run.

## Packages

Per board B (acorn, arty, netv2, fomu, tt-fpga), all `Architecture: all`:

| Package | Contents | Depends |
|---|---|---|
| `fpgas-online-B` | Nothing but `/usr/share/fpgas-online/verify/mode.d/B.ini` (`fpga-board = B`); enables `fpgas-verify.service` | `fpgas-online-B-tools` (= v), `fpgas-online-verify` (= v). Provides and Conflicts `fpgas-online-verify-mode` |
| `fpgas-online-B-tools` | The board's module (`fpgas_online_verify/boards/B.py`), `/usr/bin/fpgas-B-verify` | `fpgas-online-verify` (= v), the bitstreams, and only this board's programmer and libraries |
| `fpgas-online-B-bitstreams` | `/usr/share/fpgas-online/B/bitstreams/` and a sha256 manifest. The Acorn's are the pinned Vivado release (`packaging/acorn-pcie/release.toml`); the others are the commit's CI builds | none |
| `fpgas-online-B-debug` | `/usr/bin/fpgas-B-debug` (step-by-step: detect, list, check, program, test) and the dependencies of the tests the boot check leaves out | `fpgas-online-B-tools` (= v), e.g. python3-libgpiod, arping |

Shared:

| Package | Contents |
|---|---|
| `fpgas-online-verify` | The `fpgas_online_verify` Python package: detection, bitstream checks, reports, fleet-events, state, the host test scripts; `fpgas-verify`, `fpgas-debug`; `fpgas-verify.service` (installed, enabled only by a mode package) |
| `fpgas-online-multi-board` | `mode.d/auto.ini` (`fpga-board = auto`); enables the unit. Provides and Conflicts `fpgas-online-verify-mode` |
| `fpgas-online-all-boards` | Depends on `fpgas-online-multi-board` and every `fpgas-online-B-tools`; Recommends every `-debug` |

`fpgas-online-acorn-tools` loses its own `fpgas-acorn-verify.service`: the Acorn verify (the prototype for
all of this) becomes the Acorn's board module, and its generic parts (PCI and USB scans, the manifest check,
reports, fleet-events, the lock) became the shared core. The fleet's NFS root must enable
`fpgas-verify.service` (by installing `fpgas-online-acorn` or `fpgas-online-all-boards`) instead.

## Configuration

`fpgas-verify` reads `*.ini` files, `[verify] fpga-board = <board>|auto`, from
`/usr/share/fpgas-online/verify/mode.d/` (the mode packages' own, not conffiles, so switching mode packages
leaves no stale file) and then `/etc/fpgas-verify/` (the admin's, which wins). No setting at all is a fatal
error that says which package to install. `fpgas-B-verify` and `fpgas-verify --board B` are always
single-board.

## Results

`pass`, `degraded` (Acorn running its golden image), `unconverted` (Acorn on SQRL's factory image),
`changed` (identity or flash differs from the recorded state), `fail` (a test or load failed), `missing` (the
configured board, or with `auto` any board, was not found), `error` (the check itself could not run).
Worst wins; the exit status is 0 only for `pass`. Reports go to `/run/fpgas-online/verify.json` and are
published as the fleet-event stage `fpga-verified`.

## What each board checks, and what "state" means for it

| Board | Found by | Loaded with | Boot-check tests | State (a change is fatal) |
|---|---|---|---|---|
| Acorn | PCI 10ee/1e24 | (runs from its flash) | running image, flash slots vs release | PCI slot and IDs, flash part and unique id, sha256 of both flash slots |
| Arty A7 | USB 0403:6010 | openFPGALoader | uart, ddr, spiflash | FTDI serial; flash JEDEC id; sha256 of the flash's boot image region, read with `openFPGALoader --dump-flash` |
| NeTV2 | JTAG IDCODE over GPIO 4/17/22/27 (only when no other board is found, or when configured) | openocd (Pi 3/4), openFPGALoader rp1pio (Pi 5) | uart, ddr, spiflash | IDCODE (part); flash JEDEC id; sha256 of the boot image region via openFPGALoader |
| Fomu EVT | USB 1209:5bf0 (foboot) | openFPGALoader DFU | uart | foboot's USB serial only: loading by DFU rewrites the user image in flash, so its flash cannot be a state |
| TT FPGA | USB 2e8a (RP2350) | RP2350 bridge | uart, spiflash | the RP2350's USB serial only: every load rewrites the bitstream file on the RP2350 |

The Arty and NeTV2 flash readback and every non-Acorn verify are not yet run on hardware.

## Python packaging (PyPI later)

The code is one importable package, `verify/src/fpgas_online_verify/`, with a `pyproject.toml`, so the debs
and future wheels share it. `fpgas_online_verify.boards` is a namespace package: each board's module can
ship in its own deb (and later its own wheel), and the installed boards are the ones whose modules are there.
The host test scripts stay in `designs/*/host/` (verify_hardware.py uses them) and are copied into
`fpgas_online_verify/host_tests/` when a package is built. Bitstreams are found at the deb path, or (later)
in an installed `fpgas_online_bitstreams_<board>` package.
