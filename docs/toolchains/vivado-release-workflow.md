# Publishing Vivado-built bitstreams as a GitHub Release

GitHub Actions CI builds the open-source flows (`yosys-nextpnr` /
openXC7, iCE40 via yosys+nextpnr-ice40), but the `vivado-vivado` and
`yosys-vivado` flows require a paid Xilinx Vivado license and cannot
run in public CI. Those two flows are built locally and published to
GitHub Releases by
[`scripts/publish_vivado_bitstreams.py`](../../scripts/publish_vivado_bitstreams.py).

## Prerequisites

- Vivado ML Standard installed and working — see
  [`vivado.md`](vivado.md). The script defaults to
  `/opt/Xilinx/2025.2/Vivado/settings64.sh`; override with
  `--vivado-settings PATH` if you installed elsewhere.
- `gh` CLI authenticated against the fork you have push access to:
  ```sh
  gh auth status
  ```
  If not logged in:
  ```sh
  gh auth login
  ```
- A clean `git status` on the `vivado-xilinx-flows` branch. A dirty
  tree is rejected by default; see [Dirty builds](#dirty-builds) if
  you really want to publish one.
- Repo setup complete:
  ```sh
  make setup       # venv + LiteX + toolchains (one-time)
  make check-vivado
  ```

## One-command workflow

```sh
# Sanity check without publishing — builds, collects, writes manifest,
# leaves staged artifacts at tmp/vivado-release/ for inspection.
make publish-vivado-bitstreams ARGS="--dry-run"

# Real publish: creates a GitHub Release with tag
# vivado-bitstreams-<git describe --tags --always --dirty>.
make publish-vivado-bitstreams
```

The script is also directly invocable:

```sh
uv run python scripts/publish_vivado_bitstreams.py --help
```

## What gets built

By default, both Vivado-requiring flows across every Xilinx design:

| Flow             | Synth  | P&R    | Needs Vivado? |
|------------------|--------|--------|---------------|
| `vivado-vivado`  | Vivado | Vivado | yes           |
| `yosys-vivado`   | Yosys  | Vivado | yes           |
| `yosys-nextpnr`  | Yosys  | nextpnr-xilinx | no — CI builds it |

Restrict to one flow with e.g. `--flows vivado-vivado`.

## Release tag convention

The release tag is
`vivado-bitstreams-<git describe --tags --always --dirty>`:

- Clean tree on a tagged commit: `vivado-bitstreams-v0.1`
- Clean tree between tags: `vivado-bitstreams-v0.0-490-g99f0785`
- Dirty tree: `vivado-bitstreams-v0.0-490-g99f0785-dirty`

The tag name encodes everything needed to reproduce the build, so the
script doesn't require you to pass a version number.

## Release contents

Every release contains:

- `*.bit` / `*.bin` / `*.mcs` / `*.svf` bitstream files, each renamed
  to the canonical form
  `<design>_<board>-<variant>_<flow>.<ext>`, e.g.
  `uart_arty-a7-35_vivado-vivado.bit`.
- `manifest.json` — schema-versioned JSON listing every artifact with
  its design/board/variant/flow, size, and SHA-256. Also records the
  git state and Vivado version used to build.
- `SHA256SUMS` — plain `sha256sum`-format file so consumers can verify
  downloads:
  ```sh
  sha256sum -c SHA256SUMS
  ```

## Dirty builds

Publishing from a dirty tree is an opt-in:

```sh
make publish-vivado-bitstreams ARGS="--allow-dirty"
```

When enabled:

- The tag carries a `-dirty` suffix (which is exactly what `git
  describe --dirty` emits).
- A previous `-dirty` release with the same tag is **deleted and
  recreated** — dirty releases are provisional by definition.
- Clean releases are never overwritten. The script aborts with an
  error if a tag without a `-dirty` suffix already exists.

## Reusing a prior build

If the long Vivado build already completed but `gh release create`
failed (e.g. transient auth/network issue), skip the rebuild with
`--skip-build`:

```sh
make publish-vivado-bitstreams ARGS="--skip-build"
```

The script re-collects existing
`designs/*/build/*-{vivado-vivado,yosys-vivado}/gateware/` outputs and
publishes them without re-running Vivado.

## Failure behaviour

Fail-fast throughout:

- Pre-flight failures (no Vivado, `gh` not authed, dirty tree without
  `--allow-dirty`) abort before any build runs.
- A `make` failure aborts before any artifact is collected. **No
  partial release is ever published.**
- After collection, an empty artifact set is treated as an error —
  either the flow suffix filter excluded everything, or the build
  produced no bitstreams.

## Troubleshooting

- `ERROR: gh auth status failed` → `gh auth login` and re-run.
- `ERROR: make check-vivado failed` → verify the settings file exists
  and `vivado -version` runs after sourcing it.
- `ERROR: Release vivado-bitstreams-… already exists on …` → a clean
  release is immutable. Either commit fresh changes (new `git
  describe`), or delete the existing release manually
  (`gh release delete <tag>`) if you really want to recreate it.
- `ERROR: No bitstreams found for requested flows` → the build
  completed but produced no `.bit`/`.bin` under the expected
  `designs/*/build/*-<flow>/gateware/` paths. Check the build logs.
