# fpgas-online-verify

Boot-time verification of the FPGA board attached to an fpgas.online Raspberry Pi: find the board, load the
fpgas.online test bitstreams into it, run their host tests, and catch a board or a flash that has changed
since the last run.

Installed from the fpgas.online apt repository (see the repository's top-level README):

| Install | For |
|---|---|
| `fpgas-online-<board>` (acorn, arty, netv2, fomu, tt-fpga) | a Pi with that one board: not finding it is fatal |
| `fpgas-online-all-boards` | a netboot root, or a Pi that should find whichever board it has |
| `fpgas-online-multi-board` + `fpgas-online-<board>-tools` | the same, among the boards you choose |
| `fpgas-online-<board>-debug` | the tools for when a board's verify fails |

Commands: `fpgas-verify` (what the boot unit runs), `fpgas-<board>-verify`, `fpgas-<board>-debug`, and
`fpgas-acorn-flash`. The design is in `docs/plans/2026-09-26-fpgas-online-verify-design.md`.

From a checkout, without installing: `uv run --no-project python -m fpgas_online_verify --help` with
`PYTHONPATH=verify/src`.
