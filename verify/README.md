# fpgas-online-verify

Boot-time verification of the FPGA board attached to an fpgas.online Raspberry Pi: find the board, load the
fpgas.online test bitstreams into it, run their host tests, and catch a board or a flash that has changed
since the last run.

Installed from the fpgas.online apt repository; the full guide is [docs/verify.md](../docs/verify.md):

| Install | For |
|---|---|
| `fpgas-online-<board>` (acorn, arty, netv2, fomu, tt-fpga) | a Pi with that one board: not finding it is fatal |
| `fpgas-online-all-boards` | a netboot root, or a Pi that should find whichever board it has |
| `fpgas-online-multi-board` + `fpgas-online-<board>-tools` | the same, among the boards you choose |
| `fpgas-online-<board>-debug` | the tools for when a board's verify fails |

Commands: `fpgas-verify` (what the boot unit runs), `fpgas-<board>-verify`, `fpgas-<board>-debug`, and
`fpgas-acorn-flash`.

| Command | Does |
|---|---|
| `fpgas-verify --identify` | prints who the board is as one JSON document ([docs/identity.md](../docs/identity.md)), from reads that disturb nothing |
| `fpgas-verify --label [--out F] [--list]` | makes this Pi's and its board's labels with [rpi-hwid](https://github.com/mithro/rpi-hwid) (`rpi-hwid labels --this-host`) |

rpi-hwid is optional: `--label` runs its command if it is installed (`python3-rpi-hwid`, or the `labels`
extra: `pip install 'fpgas-online-verify[labels]'`) and says how to install it if not. Inside `--label`,
`FPGAS_VERIFY_IDENTITY` makes `--identify` print the outer run's document and every other mode refuse
([docs/verify/identity-and-labels.md](../docs/verify/identity-and-labels.md#identity-and-labels)).

The guide is [docs/verify.md](../docs/verify.md); the design notes are in
[docs/plans/2026-09-26-fpgas-online-verify-design.md](../docs/plans/2026-09-26-fpgas-online-verify-design.md).

From a checkout, without installing: `uv run --no-project python -m fpgas_online_verify --help` with
`PYTHONPATH=verify/src`.
