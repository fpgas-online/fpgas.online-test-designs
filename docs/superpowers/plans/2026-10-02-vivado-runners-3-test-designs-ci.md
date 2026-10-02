# Vivado Runners Plan 3: test-designs CI (Vivado matrix and releases) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build every Xilinx test design in this repository with Vivado 2025.2 on the sandboxed self-hosted runners, beside the unchanged openXC7 builds, and publish the Vivado releases from CI without a write token ever reaching a runner.

**Architecture:** One new workflow, `Build: Vivado`, runs one job per entry of a Python matrix (`scripts/vivado_matrix.py`). Each job runs `scripts/vivado_build.py`, which builds the entry, fails unless the `.bit` header says Vivado 2025.2 and the right part, and stages an artifact carrying a `build-info.json`. A second workflow, `Release: Vivado bitstreams`, runs on `ubuntu-latest`, downloads those artifacts for a commit and puts a release together from them (`scripts/vivado_release.py`, and the existing `designs/acorn-pcie/tools/publish_release.py`).

**Tech Stack:** GitHub Actions, Python 3.12 (standard library only in the three scripts), `uv`, pytest, ruff, LiteX with the Vivado toolchain, `gh`.

**Spec:** `docs/superpowers/specs/2026-09-25-vivado-runners-design.md` (sections "test-designs changes", "Releases", rollout Phases 3 and 5). This is Plan 3 of 3. Plan 1 (runner repository) and Plan 2 (deployment, and the `vivado-runner-sandbox.yml` acceptance workflow) come first: **no pull request of this plan may merge before Plan 2's runners are live**, because a queued Vivado job with no runner stays pending.

## What was checked while writing this plan

Everything below was run on desktop.buddy.mithis.com on 2026-10-02, against `origin/main` at `b1218ee` (the base of branch `docs/vivado-runners-spec`), with the main checkout's LiteX environment and `/opt/Xilinx/2025.2`.

| Claim | Evidence |
|---|---|
| On `main`, every LiteX SoC test design fails at once with `--toolchain vivado` | All 21 `uart`, `spi-flash-id`, `ddr-memory` and `ethernet-test` script/variant pairs (and `pcie-enumeration`'s 5): `AssertionError: Toolchain does not have '_yosys_template' attribute` (`designs/_shared/yosys_workarounds.py`). The bare `pmod-loopback` and `pmod-pin-id` designs and the `acorn-pcie` SoC do not call that helper and construct. |
| With the one-function fix of Task 1, all 39 matrix entries construct under `--toolchain vivado` | The same probe, 33 test-design entries + 6 `acorn-pcie` ones, all exit 0 (no `--build`, so Vivado itself not run). |
| A real Vivado build through `scripts/vivado_build.py` works for a SoC | `uart-acorn-cle-215p`: 3 min 34 s wall, peak RSS 2.8 GB, `Vivado 2025.2, part 7a200tfbg484, 6 files` (`sqrl_acorn{,_fallback,_operational}.{bin,bit}`); `sqrl_acorn_timing.rpt` says "All user specified timing constraints are met." |
| ... and for bare designs, whose build is named `top` | `pmod-pin-id-netv2-a7-35`: `top.bit`, part `7a35tfgg484`. `pmod-loopback-arty-a7-35`: `top.bit` + `top.bin`, part `7a35ticsg324`. |
| ... and for the largest design, whose artifacts must satisfy `publish_release.py` | `acorn-pcie-acorn-cle-215p`: 8 min 25 s, peak RSS 3.3 GB, 8 files. `acorn-pcie-acorn-cle-215p-golden`: 5 min 28 s, peak RSS 3.0 GB, 8 files. Those two artifacts, through `acorn_pcie_tree()` and `publish_release.py --source-evidence` (stage only): slot, IDCODE and identifier checks pass, flash layout `0x000000 acorn-cle-215p-golden-sqrl_acorn_fallback.bin`, `0x400000 acorn-cle-215p-sqrl_acorn_operational.bin`. |
| `.bit` header strings | `publish_release.bit_header()` on six files of release `vivado-bitstreams-v0.0-496-gf162f60`: `version` is `2025.2`; parts as in `PARTS` in Task 2. |
| The scripts and tests in this plan pass | 17 tests (PR 1 state), 21 (PR 2), 14 + 27 (PR 3), 4 (Task 1); `ruff check` and `ruff format --check` clean; `actionlint` clean but for the custom runner label. |
| The edited `collect-bitstreams.yml` filters work | Both `jq` filters run against the live API for `origin/main`'s runs. |

Not checked, because it needs the runners: anything in a real GitHub Actions run. Each pull request's exit check says what its run exercised.

## Where this plan departs from the spec

1. **Vivado jobs are one separate workflow, not jobs added to each `build-*.yml`.** `collect-bitstreams.yml` does two things the spec did not account for: it waits for *every other workflow run* of the commit to complete (not only for jobs matching `^(Arty|NeTV2|Fomu|TT FPGA|netv2)`), and it downloads artifacts only from completed, successful runs. A Vivado job inside `build-uart-test.yml` would keep that whole run incomplete while it waits for a runner, so a runner outage would stall the openXC7 bundle for an hour and then fail it. A separate workflow, left out of both steps by name, keeps the spec's promise ("a runner outage delays only the Vivado jobs"). The `Vivado:` job-name prefix is kept as well.
2. **`pcie-enumeration` is not in the matrix.** On `main` its SoCs add the open `pcie_7x` Verilog unconditionally and, under Vivado, `S7PCIEPHY` also emits the Xilinx IP: two definitions of `pcie_s7`. The fix exists only on the unmerged branch `vivado-xilinx-flows` (pull request #14).
3. **The all-designs release was not made by hand.** The spec says no script for it is in the repo. That is true of `main`, but release `vivado-bitstreams-v0.0-496-gf162f60` was made by `scripts/publish_vivado_bitstreams.py` on branch `vivado-xilinx-flows` (pull request #14, open, 266 commits behind `main`), which also builds. This plan writes a smaller script that only assembles a release from CI artifacts, and keeps that release's file naming, `manifest.json` schema and `SHA256SUMS` format. See "Open decisions".

## Global Constraints

- Runner labels, exactly: `runs-on: [self-hosted, vivado-2025.2]`. Runners are selected by label only. No workflow, script or document in this repository names a runner host or depends on which machine a job lands on.
- Guard on every job that uses those runners, exactly: `if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository`.
- Those jobs declare `permissions: contents: read` and `timeout-minutes: 90`, and reference no secrets.
- Job names on those runners start with `Vivado:`. Their artifact names start with `vivado-`.
- Inside the runner VM: user `runner`, no `sudo`, no `apt`, no PyPI, no DNS; only GitHub hosts are reachable through the preset `HTTPS_PROXY`. Preinstalled: `uv`, CPython 3.12, `git`, `make`, `gcc-riscv64-unknown-elf`, a uv cache warmed from `uv.lock`. Vivado is read-only at `/opt/Xilinx/2025.2`; jobs run `source /opt/Xilinx/2025.2/Vivado/settings64.sh`.
- Steps on those runners use neither `astral-sh/setup-uv` nor `sudo`. They use `uv sync --frozen --extra build` and `uv run --no-sync`.
- A Vivado job fails unless the produced `.bit` header reports Vivado `2025.2`, using `bit_header()` from `designs/acorn-pcie/tools/publish_release.py`.
- Vivado 2025.2 needs no licence file for these parts, and no workflow or script here sets `XILINXD_LICENSE_FILE` or `LM_LICENSE_FILE`, or reads, copies or uploads a `.lic` file. Versions that need a licence are Phase 6 (spec, "Vivado licences").
- Nothing publishes from a runner. Releases are made on `ubuntu-latest` with `contents: write`.
- The openXC7 jobs, their names and their artifacts do not change.
- Vivado checks must not be made required status checks: a runner outage would then block every merge.
- Python through `uv` only. No shell with loops or conditionals: write Python. ISO 8601 dates. Apache-2.0. Never redirect stderr to `/dev/null`. No files in `/tmp`: use the repository's ignored `tmp/`.
- Branches and worktrees (`superpowers:using-git-worktrees`, under `.worktrees/`), pull requests only, CI green before merge, `gh pr merge --merge` (never squash or rebase), and a pull request is merged only on the current `origin/main` after a sub-agent review.
- Small commits. Every commit message ends with these two lines:

  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
  ```

  Every pull request description ends with:

  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
  ```

- When checking a run, address it by id and compare its `headSha` with the commit you pushed (`gh run list --limit 1` is not the newest run).

---

## File Structure

| File | Pull request | Responsibility |
|---|---|---|
| `designs/_shared/yosys_workarounds.py` (modify) | 1 | `patch_yosys_template()` does nothing for the Vivado toolchain |
| `tests/test_yosys_workarounds.py` (create) | 1 | that helper, with stand-in toolchains |
| `scripts/vivado_matrix.py` (create) | 1, grows in 2 | the matrix: one `Entry` per design x board x variant; prints it as JSON for the workflow |
| `tests/test_vivado_matrix.py` (create) | 1, grows in 2 | ids, names, commands, paths |
| `scripts/vivado_build.py` (create) | 1 | build one entry, check the `.bit` header, stage `vivado-artifacts/<id>/` with `build-info.json` |
| `tests/test_vivado_build.py` (create) | 1, grows in 2 | the checks and the staging, without Vivado |
| `.github/workflows/build-vivado.yml` (create) | 1, env grows in 3 | `test`, `matrix` and the `Vivado: ...` jobs |
| `.github/workflows/collect-bitstreams.yml` (modify) | 1 | leave the Vivado workflows out of the wait and of the bundle |
| `docs/toolchains/github-actions.md` (modify) | 2 | a section on the Vivado jobs |
| `designs/acorn-pcie/tools/publish_release.py` (modify) | 3 | `--source-evidence`, for a build tree made from CI artifacts |
| `tests/test_acorn_pcie_publish_release.py` (modify) | 3 | two tests for it |
| `scripts/vivado_release.py` (create) | 3 | find the run, download, check every artifact, stage either release, publish on request |
| `tests/test_vivado_release.py` (create) | 3 | all of that but the network |
| `.github/workflows/release-vivado-bitstreams.yml` (create) | 3 | the only job in the Vivado path with `contents: write` |

**Why one matrix workflow and not a reusable workflow or per-file jobs.** The eight build files repeat the same steps per job in YAML today (about 2,300 lines). A reusable workflow (`workflow_call`) would still need a caller job per design in each of those files, and would put Vivado jobs inside the openXC7 runs, which departure 1 rules out. One workflow whose matrix comes from Python needs no per-design YAML at all: adding a design is one row in `scripts/vivado_matrix.py`, the same row names the release's files, and the list is unit-tested.

## The matrix

Confirmed in the code on `main` (argument parsers read and run with `--help`; construction under `--toolchain vivado` probed for every row with the Task 1 fix; three rows built with Vivado). `<v>` is the variant.

| Design | Board, variants | Command (after `uv run --no-sync python`) | Output |
|---|---|---|---|
| uart | arty `a7-35` | `designs/uart/gateware/uart_soc_arty.py --variant <v> --toolchain vivado --build` | `designs/uart/build/arty/gateware/digilent_arty.bit` (+ `.bin`) |
| uart | netv2 `a7-35`, `a7-100` | `designs/uart/gateware/uart_soc_netv2.py --variant <v> --toolchain vivado --build` | `designs/uart/build/netv2/gateware/kosagi_netv2.bit` |
| uart | acorn `cle-215+`, `cle-215`, `cle-101` | `designs/uart/gateware/uart_soc_acorn.py --variant <v> --toolchain vivado --build` | `designs/uart/build/acorn/gateware/sqrl_acorn.bit` (+ `.bin`, `_fallback`, `_operational`) |
| spi-flash-id | arty, netv2, acorn (same variants) | `designs/spi-flash-id/gateware/spiflash_soc_<board>.py --variant <v> --toolchain vivado --build` | `designs/spi-flash-id/build/<board>/gateware/<platform>.bit` |
| ddr-memory | arty, netv2, acorn (same variants) | `designs/ddr-memory/gateware/ddr_soc_<board>.py --variant <v> --toolchain vivado --build` | `designs/ddr-memory/build/<board>/gateware/<platform>.bit` |
| ethernet-test | arty `a7-35`; netv2 `a7-35`, `a7-100` | `designs/ethernet-test/gateware/ethernet_soc_<board>.py --variant <v> --toolchain vivado --build` | `designs/ethernet-test/build/<board>/gateware/<platform>.bit` |
| pmod-loopback | arty, netv2, acorn (same variants) | `designs/pmod-loopback/gateware/gpio_loopback_<board>.py --variant <v> --toolchain vivado --build` | `designs/pmod-loopback/build/<board>/top.bit` |
| pmod-pin-id | arty, netv2, acorn (same variants) | `designs/pmod-pin-id/gateware/pmod_pin_id_<board>.py --variant <v> --toolchain vivado --build` | `designs/pmod-pin-id/build/<board>/top.bit` |
| acorn-pcie | acorn `cle-215+`, `cle-215`, `cle-101`, each plain and `--golden` | `designs/acorn-pcie/gateware/acorn_pcie_soc.py --variant <v> --toolchain vivado [--golden] --build` | `designs/acorn-pcie/build/acorn-<v>[-golden]/gateware/sqrl_acorn{,_fallback,_operational}.{bin,bit}`, `csr.json`, `csr.csv` |

`<platform>` is `digilent_arty`, `kosagi_netv2` or `sqrl_acorn`. That is 33 test-design builds and 6 Acorn PCIe ones: 39 jobs. The boards are the ones the openXC7 jobs build. Not included: `pcie-enumeration` (departure 2), the Arty `a7-100` (no openXC7 job builds it either), and the LiteFury diagnostic bitstreams (`tmp/diag_*.py`, openXC7 debugging aids).

---

# Pull request 1: one design end to end (`ci/vivado-acorn-uart`)

Create the worktree with `superpowers:using-git-worktrees`: `.worktrees/ci-vivado-acorn-uart`, branch `ci/vivado-acorn-uart` from `origin/main`.

### Task 1: `patch_yosys_template()` leaves the Vivado toolchain alone

Without this no LiteX SoC design in the repository builds with Vivado on `main`. This is issue #102 (filed 2026-10-03); the commit message below closes it. If Tim wants the fix sooner than the runners exist, this task can go in as a pull request of its own: it needs no runner, only its unit test.

**Files:**
- Modify: `designs/_shared/yosys_workarounds.py:19-29`
- Create: `tests/test_yosys_workarounds.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `patch_yosys_template(soc)` returns without touching the toolchain when `type(soc.platform.toolchain).__name__ == "XilinxVivadoToolchain"`; unchanged otherwise.

- [ ] **Step 1: Write the failing test**

Create `tests/test_yosys_workarounds.py`:

```python
"""patch_yosys_template: nothing to do for Vivado, which runs no Yosys; still strict for every Yosys toolchain."""

import types

import pytest

yw = pytest.importorskip("designs._shared.yosys_workarounds", reason="needs LiteX: uv sync --extra build")


class XilinxVivadoToolchain:
    """Stands in for litex.build.xilinx.vivado.XilinxVivadoToolchain: the helper goes by the class name."""


class YosysToolchain:
    def __init__(self):
        self._yosys_template = ["read_verilog", "write_json"]


class YosysToolchainWithoutTemplate:
    pass


def _soc(toolchain):
    return types.SimpleNamespace(platform=types.SimpleNamespace(toolchain=toolchain))


def test_vivado_is_left_alone():
    toolchain = XilinxVivadoToolchain()
    yw.patch_yosys_template(_soc(toolchain))
    assert not hasattr(toolchain, "_yosys_template")


def test_a_yosys_toolchain_gets_the_scopeinfo_template():
    toolchain = YosysToolchain()
    yw.patch_yosys_template(_soc(toolchain))
    assert toolchain._yosys_template == yw.YOSYS_TEMPLATE_STRIP_SCOPEINFO
    assert "delete t:$scopeinfo" in toolchain._yosys_template


def test_a_yosys_toolchain_without_the_template_still_fails_early():
    with pytest.raises(AssertionError, match="_yosys_template"):
        yw.patch_yosys_template(_soc(YosysToolchainWithoutTemplate()))


def test_the_stand_in_has_the_real_class_name():
    from litex.build.xilinx.vivado import XilinxVivadoToolchain as Real

    assert Real.__name__ == XilinxVivadoToolchain.__name__
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --extra build --extra dev pytest tests/test_yosys_workarounds.py -q`
Expected: `test_vivado_is_left_alone` FAILS with `AssertionError: Toolchain does not have '_yosys_template' attribute`; the other three pass.

Then see the real symptom (no Vivado needed, nothing is built without `--build`):

Run: `uv run --extra build python designs/uart/gateware/uart_soc_acorn.py --variant cle-215+ --toolchain vivado`
Expected: exit 1, the same `AssertionError`.

- [ ] **Step 3: Fix the helper**

In `designs/_shared/yosys_workarounds.py`, replace the whole `patch_yosys_template` function with:

```python
def patch_yosys_template(soc):
    """Apply the ``$scopeinfo`` workaround to *soc*'s platform toolchain.

    Vivado runs no Yosys, so its toolchain has no ``_yosys_template`` and
    there is nothing to patch. Every other toolchain the designs build with
    is a Yosys one: assert it exposes ``_yosys_template`` so we fail early
    if the LiteX internals change.
    """
    toolchain = soc.platform.toolchain
    if type(toolchain).__name__ == "XilinxVivadoToolchain":
        return
    assert hasattr(toolchain, "_yosys_template"), (
        "Toolchain does not have '_yosys_template' attribute — "
        "the LiteX API may have changed"
    )
    toolchain._yosys_template = list(YOSYS_TEMPLATE_STRIP_SCOPEINFO)
```

- [ ] **Step 4: Run the tests and the script again**

Run: `uv run --extra build --extra dev pytest tests/test_yosys_workarounds.py -q`
Expected: `4 passed`.

Run: `uv run --extra build python designs/uart/gateware/uart_soc_acorn.py --variant cle-215+ --toolchain vivado`
Expected: exit 0.

Run: `uv run --extra dev ruff check designs/_shared/yosys_workarounds.py tests/test_yosys_workarounds.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add designs/_shared/yosys_workarounds.py tests/test_yosys_workarounds.py
git commit -m "yosys_workarounds: Vivado runs no Yosys, so leave its toolchain alone" -m "patch_yosys_template() asserted that every toolchain has _yosys_template, which LiteX's Vivado toolchain does not: every SoC design failed with --toolchain vivado before building anything. Yosys toolchains are still required to have it." -m "Fixes #102" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 2: the matrix, with one entry

**Files:**
- Create: `scripts/vivado_matrix.py`
- Test: `tests/test_vivado_matrix.py`

**Interfaces:**
- Consumes: nothing (standard library only).
- Produces, all in module `vivado_matrix`:
  - constants `VIVADO_VERSION = "2025.2"`, `VIVADO_SETTINGS`, `FLOW = "vivado-vivado"`, `PARTS`, `ACORN_PCIE_IMAGES`
  - `Entry` (frozen dataclass): fields `design, board, variant, script, build_dir, bit, keep, required, extra_args, golden`; properties `slug` (variant with `+` as `p`), `id`, `name`, `part`; method `command() -> list[str]` (the gateware script and its arguments, without the interpreter)
  - `ENTRIES: tuple[Entry, ...]`, `entry(entry_id) -> Entry` (raises `KeyError`), `as_matrix(entries=ENTRIES) -> {"include": [{"id", "name"}, ...]}`
  - CLI: `--github-output` appends `matrix=<one line of JSON>` to `$GITHUB_OUTPUT`; with no argument it lists ids and commands.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vivado_matrix.py`:

```python
"""The Vivado build matrix (scripts/vivado_matrix.py): what CI builds with Vivado, and how each job is named."""

import fnmatch
import importlib.util
import json
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vivado_matrix", _ROOT / "scripts" / "vivado_matrix.py")
vm = importlib.util.module_from_spec(_spec)
sys.modules["vivado_matrix"] = vm  # dataclasses looks its module up there
_spec.loader.exec_module(vm)


def test_the_first_matrix_is_the_acorn_uart_alone():
    assert [e.id for e in vm.ENTRIES] == ["uart-acorn-cle-215p"]


def test_ids_are_safe_as_artifact_and_file_names():
    for e in vm.ENTRIES:
        assert re.fullmatch(r"[a-z0-9-]+", e.id), e.id


def test_every_entry_names_a_gateware_script_that_exists():
    for e in vm.ENTRIES:
        assert (_ROOT / e.script).is_file(), e.script


def test_every_entry_has_a_part_and_keeps_its_bit():
    for e in vm.ENTRIES:
        assert e.part == vm.PARTS[(e.board, e.variant)]
        assert any(fnmatch.fnmatch(e.bit, pattern) for pattern in e.keep), e.id


def test_the_command_builds_with_vivado():
    e = vm.entry("uart-acorn-cle-215p")
    assert e.command() == [
        "designs/uart/gateware/uart_soc_acorn.py",
        "--variant",
        "cle-215+",
        "--toolchain",
        "vivado",
        "--build",
    ]
    assert e.build_dir == "designs/uart/build/acorn"
    assert e.bit == "gateware/sqrl_acorn.bit"
    assert e.part == "7a200tfbg484"


def test_job_names_cannot_match_the_bundle_job_patterns():
    # collect-bitstreams.yml waits for check runs named ^(Arty|NeTV2|Fomu|TT FPGA|netv2): the workflow
    # prefixes these names with "Vivado: ", and none may start with a board name on its own.
    for row in vm.as_matrix()["include"]:
        assert not re.match(r"(Arty|NeTV2|Fomu|TT FPGA|netv2)", row["name"]), row["name"]
        assert set(row) == {"id", "name"}


def test_unknown_id_is_a_key_error():
    try:
        vm.entry("uart-arty-a7-200")
    except KeyError as e:
        assert e.args == ("uart-arty-a7-200",)
    else:
        raise AssertionError("no KeyError")


def test_github_output_is_one_line_of_json(tmp_path, monkeypatch):
    out = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    vm.main(["--github-output"])
    key, _, value = out.read_text().rstrip("\n").partition("=")
    assert key == "matrix" and "\n" not in value
    assert json.loads(value) == vm.as_matrix()
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py -q`
Expected: an error during collection, `FileNotFoundError: ... scripts/vivado_matrix.py`.

- [ ] **Step 3: Write the matrix**

Create `scripts/vivado_matrix.py`:

```python
#!/usr/bin/env python3
"""The Vivado build matrix: every design x board x variant that CI builds with Vivado.

One list, with two readers:

  * .github/workflows/build-vivado.yml asks for it as JSON (`--github-output`) and runs one job per entry;
  * scripts/vivado_build.py builds one entry and checks what Vivado left.

This first version has one entry, the Acorn CLE-215+ UART SoC: it proves the path from a pull request to a
sandboxed runner and back. The other designs and boards follow it.

Standard library only, so the workflow's first job runs it without installing anything.

    uv run --no-project python scripts/vivado_matrix.py          # list the entries and their commands
"""

import argparse
import dataclasses
import json
import os

VIVADO_VERSION = "2025.2"
VIVADO_SETTINGS = "/opt/Xilinx/2025.2/Vivado/settings64.sh"
FLOW = "vivado-vivado"  # Vivado synthesis, Vivado place and route: the name the 2026-04 release used

# The part Vivado writes in a .bit header, read from the files of release vivado-bitstreams-v0.0-496-gf162f60.
PARTS = {
    ("arty", "a7-35"): "7a35ticsg324",
    ("netv2", "a7-35"): "7a35tfgg484",
    ("netv2", "a7-100"): "7a100tfgg484",
    ("acorn", "cle-215+"): "7a200tfbg484",
    ("acorn", "cle-215"): "7a200tfbg484",
    ("acorn", "cle-101"): "7a100tfgg484",
}
PLATFORM = {"arty": "digilent_arty", "netv2": "kosagi_netv2", "acorn": "sqrl_acorn"}
BOARD_TITLE = {"arty": "Arty", "netv2": "NeTV2", "acorn": "Acorn"}
VARIANTS = {"acorn": ("cle-215+",)}

# LiteX SoCs: Builder writes <build dir>/gateware/<platform>.bit. (design, gateware script, boards)
SOC_DESIGNS = (("uart", "uart_soc_{board}.py", ("acorn",)),)
# Bare modules built with platform.build(): no gateware/ directory, and the build is named "top".
BARE_DESIGNS = ()
# The Acorn PCIe SoC: each variant as the operational image and as the golden one.
ACORN_PCIE_VARIANTS = ()
ACORN_PCIE_IMAGES = tuple(
    f"gateware/sqrl_acorn{suffix}{ext}" for suffix in ("", "_fallback", "_operational") for ext in (".bin", ".bit")
)


@dataclasses.dataclass(frozen=True)
class Entry:
    design: str  # the directory under designs/
    board: str  # arty, netv2 or acorn
    variant: str  # as the gateware script's --variant takes it
    script: str  # the gateware script, from the repository root
    build_dir: str  # where that script builds, from the repository root
    bit: str  # the plain .bit, from build_dir: the file whose header is checked
    keep: tuple  # globs from build_dir: what the job's artifact carries
    required: tuple = ()  # files from build_dir that must exist besides `bit`
    extra_args: tuple = ()
    golden: bool = False

    @property
    def slug(self):
        """The variant as file and artifact names spell it: `+` is `p`."""
        return self.variant.replace("+", "p")

    @property
    def id(self):
        return f"{self.design}-{self.board}-{self.slug}" + ("-golden" if self.golden else "")

    @property
    def name(self):
        return f"{self.design} / {BOARD_TITLE[self.board]} {self.variant}" + (" (golden)" if self.golden else "")

    @property
    def part(self):
        return PARTS[(self.board, self.variant)]

    def command(self):
        """The gateware script and its arguments (run with the project's Python, from the repository root)."""
        return [self.script, "--variant", self.variant, "--toolchain", "vivado", *self.extra_args, "--build"]


def _entries():
    out = []
    for design, script, boards in SOC_DESIGNS:
        for board in boards:
            for variant in VARIANTS[board]:
                out.append(
                    Entry(
                        design=design,
                        board=board,
                        variant=variant,
                        script=f"designs/{design}/gateware/{script.format(board=board)}",
                        build_dir=f"designs/{design}/build/{board}",
                        bit=f"gateware/{PLATFORM[board]}.bit",
                        keep=("gateware/*.bit", "gateware/*.bin"),
                    )
                )
    for design, script, boards in BARE_DESIGNS:
        for board in boards:
            for variant in VARIANTS[board]:
                out.append(
                    Entry(
                        design=design,
                        board=board,
                        variant=variant,
                        script=f"designs/{design}/gateware/{script.format(board=board)}",
                        build_dir=f"designs/{design}/build/{board}",
                        bit="top.bit",
                        keep=("*.bit", "*.bin"),
                    )
                )
    for variant in ACORN_PCIE_VARIANTS:
        for golden in (False, True):
            out.append(
                Entry(
                    design="acorn-pcie",
                    board="acorn",
                    variant=variant,
                    script="designs/acorn-pcie/gateware/acorn_pcie_soc.py",
                    build_dir=f"designs/acorn-pcie/build/acorn-{variant}{'-golden' if golden else ''}",
                    bit="gateware/sqrl_acorn.bit",
                    keep=("gateware/sqrl_acorn*.bit", "gateware/sqrl_acorn*.bin", "csr.json", "csr.csv"),
                    required=(*ACORN_PCIE_IMAGES, "csr.json", "csr.csv"),
                    extra_args=("--golden",) if golden else (),
                    golden=golden,
                )
            )
    return tuple(out)


ENTRIES = _entries()


def entry(entry_id):
    """The entry with that id; KeyError if there is none."""
    for e in ENTRIES:
        if e.id == entry_id:
            return e
    raise KeyError(entry_id)


def as_matrix(entries=ENTRIES):
    """What `strategy.matrix` takes: one {id, name} per entry."""
    return {"include": [{"id": e.id, "name": e.name} for e in entries]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--github-output", action="store_true", help="append matrix=<json> to $GITHUB_OUTPUT")
    args = parser.parse_args(argv)
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json.dumps(as_matrix(), separators=(',', ':'))}\n")
        print(f"{len(ENTRIES)} Vivado builds")
        return
    for e in ENTRIES:
        print(f"{e.id:42} {' '.join(e.command())}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, the linter and the script**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py -q`
Expected: `8 passed`.

Run: `uv run --no-project --with ruff ruff check scripts/vivado_matrix.py tests/test_vivado_matrix.py` and then `uv run --no-project --with ruff ruff format --check scripts/vivado_matrix.py tests/test_vivado_matrix.py`
Expected: `All checks passed!` and `2 files already formatted`.

Run: `uv run --no-project python scripts/vivado_matrix.py`
Expected: one line: `uart-acorn-cle-215p`, padding, then `designs/uart/gateware/uart_soc_acorn.py --variant cle-215+ --toolchain vivado --build`.

- [ ] **Step 5: Commit**

```bash
git add scripts/vivado_matrix.py tests/test_vivado_matrix.py
git commit -m "vivado_matrix: the Vivado build matrix, starting with the Acorn UART" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 3: build one entry, check it, stage it

**Files:**
- Create: `scripts/vivado_build.py`
- Test: `tests/test_vivado_build.py`

**Interfaces:**
- Consumes: `vivado_matrix` (Task 2); `bit_header(data) -> {"design", "version", "part"}` and `ReleaseError` from `designs/acorn-pcie/tools/publish_release.py` (existing).
- Produces, in module `vivado_build`:
  - `BuildError`
  - `check_bit(path, entry) -> dict`, `build(entry, repo, run=subprocess.run)`, `stage(entry, repo, commit) -> pathlib.Path`
  - `stage()` writes `<repo>/vivado-artifacts/<entry.id>/` holding the files matching `entry.keep` (paths relative to `entry.build_dir`) and `build-info.json`:
    `{"schema": 1, "id", "design", "board", "variant", "golden", "source_commit", "vivado_version", "part", "files": [{"path", "size_bytes", "sha256"}]}`
  - CLI: `--id <entry id>`, run with Vivado on the `PATH` from the repository root.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vivado_build.py`:

```python
"""scripts/vivado_build.py without Vivado: the build directory is cleaned, the .bit header decides, and the
artifact carries what the release needs."""

import hashlib
import importlib.util
import json
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vivado_build", _ROOT / "scripts" / "vivado_build.py")
vb = importlib.util.module_from_spec(_spec)
sys.modules["vivado_build"] = vb
_spec.loader.exec_module(vb)

COMMIT = "e568a408e7bd" + "0" * 28


def bit(version="2025.2", part="7a200tfbg484", design="sqrl_acorn", body=b"\xff" * 32):
    """A .bit: Xilinx's TLV header as Vivado writes it, then the configuration data."""

    def field(key, text):
        raw = text.encode() + b"\x00"
        return key + len(raw).to_bytes(2, "big") + raw

    head = bytes.fromhex("0009") + bytes.fromhex("0ff00ff00ff00ff000") + bytes.fromhex("0001")
    head += field(b"a", f"{design};UserID=0XFFFFFFFF;COMPRESS=TRUE;Version={version}")
    head += field(b"b", part) + field(b"c", "2026/10/02") + field(b"d", "09:30:00")
    return head + b"e" + len(body).to_bytes(4, "big") + body


def built(repo, entry, **kw):
    """What a successful build of `entry` leaves in its build directory."""
    build_dir = repo / entry.build_dir
    (build_dir / entry.bit).parent.mkdir(parents=True, exist_ok=True)
    (build_dir / entry.bit).write_bytes(bit(part=entry.part, **kw))
    for name in entry.required:
        (build_dir / name).parent.mkdir(parents=True, exist_ok=True)
        if not (build_dir / name).exists():
            (build_dir / name).write_bytes(b"required " + name.encode())
    return build_dir


UART = vb.matrix.entry("uart-acorn-cle-215p")


def test_a_good_build_is_staged_with_its_provenance(tmp_path):
    build_dir = built(tmp_path, UART)
    (build_dir / "gateware" / "sqrl_acorn.bin").write_bytes(b"bin")
    (build_dir / "gateware" / "sqrl_acorn_route.dcp").write_bytes(b"not kept")
    out = vb.stage(UART, tmp_path, COMMIT)
    assert out == tmp_path / "vivado-artifacts" / "uart-acorn-cle-215p"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "build-info.json",
        "gateware/sqrl_acorn.bin",
        "gateware/sqrl_acorn.bit",
    ]
    info = json.loads((out / "build-info.json").read_text())
    assert info["id"] == "uart-acorn-cle-215p"
    assert (info["design"], info["board"], info["variant"], info["golden"]) == ("uart", "acorn", "cle-215+", False)
    assert (info["source_commit"], info["vivado_version"], info["part"]) == (COMMIT, "2025.2", "7a200tfbg484")
    by_path = {f["path"]: f for f in info["files"]}
    assert by_path["gateware/sqrl_acorn.bin"] == {
        "path": "gateware/sqrl_acorn.bin",
        "size_bytes": 3,
        "sha256": hashlib.sha256(b"bin").hexdigest(),
    }


def test_a_bit_from_another_vivado_is_refused(tmp_path):
    built(tmp_path, UART, version="2024.1")
    with pytest.raises(vb.BuildError, match=r"written by Vivado 2024\.1, not 2025\.2"):
        vb.stage(UART, tmp_path, COMMIT)


def test_a_bit_for_another_part_is_refused(tmp_path):
    build_dir = built(tmp_path, UART)
    (build_dir / UART.bit).write_bytes(bit(part="7a100tfgg484"))
    with pytest.raises(vb.BuildError, match="built for part 7a100tfgg484, not 7a200tfbg484"):
        vb.stage(UART, tmp_path, COMMIT)


def test_a_missing_bit_is_refused(tmp_path):
    with pytest.raises(vb.BuildError, match="was not built"):
        vb.stage(UART, tmp_path, COMMIT)


def test_a_file_that_is_not_a_bit_is_refused(tmp_path):
    build_dir = built(tmp_path, UART)
    (build_dir / UART.bit).write_bytes(b"\xff" * 64)
    with pytest.raises(vb.BuildError, match=r"not a Xilinx \.bit file"):
        vb.stage(UART, tmp_path, COMMIT)


def test_restaging_replaces_the_previous_artifact(tmp_path):
    built(tmp_path, UART)
    stale = tmp_path / "vivado-artifacts" / UART.id / "gateware" / "old.bit"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    vb.stage(UART, tmp_path, COMMIT)
    assert not stale.exists()


def test_build_starts_from_an_empty_build_directory_and_runs_the_entry_command(tmp_path):
    stale = tmp_path / UART.build_dir / "gateware" / "sqrl_acorn.bit"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(bit())
    calls = []

    def run(argv, cwd):
        calls.append((argv, cwd))
        assert not stale.exists(), "the old build was still there when the new one started"
        return types.SimpleNamespace(returncode=0)

    vb.build(UART, tmp_path, run=run)
    assert calls == [([sys.executable, *UART.command()], tmp_path)]


def test_a_failed_gateware_script_is_a_build_error(tmp_path):
    with pytest.raises(vb.BuildError, match="exited 1"):
        vb.build(UART, tmp_path, run=lambda argv, cwd: types.SimpleNamespace(returncode=1))


def test_an_unknown_id_exits_with_the_way_to_list_them():
    with pytest.raises(SystemExit, match="no matrix entry 'uart-arty-a7-200'"):
        vb.main(["--id", "uart-arty-a7-200"])
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_build.py -q`
Expected: an error during collection, `FileNotFoundError: ... scripts/vivado_build.py`.

- [ ] **Step 3: Write the script**

Create `scripts/vivado_build.py`:

```python
#!/usr/bin/env python3
"""Build one entry of scripts/vivado_matrix.py with Vivado, check it, and stage it as the job's artifact.

Run it from the repository root, in the project's environment, with Vivado on the PATH:

    source /opt/Xilinx/2025.2/Vivado/settings64.sh
    uv run --no-sync python scripts/vivado_build.py --id uart-acorn-cle-215p

It removes the entry's build directory first, so nothing an older build left can be taken for this one's, and
runs the entry's gateware script. The build then fails unless the entry's plain .bit exists and its header
says Vivado 2025.2 wrote it for the entry's part (the header parser is publish_release.py's, the one the
release uses). What the entry keeps is copied to vivado-artifacts/<id>/ beside a build-info.json naming the
commit, the Vivado version and each file's sha256: build-vivado.yml uploads that directory as `vivado-<id>`.
"""

import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = "vivado-artifacts"
INFO_SCHEMA = 1


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its module up there
    spec.loader.exec_module(module)
    return module


matrix = _load("vivado_matrix", REPO / "scripts" / "vivado_matrix.py")
publish_release = _load("publish_release", REPO / "designs" / "acorn-pcie" / "tools" / "publish_release.py")


class BuildError(Exception):
    pass


def check_bit(path, entry):
    """The header of the entry's plain .bit; BuildError unless Vivado 2025.2 wrote it for the entry's part."""
    if not path.is_file():
        raise BuildError(f"{path} was not built")
    try:
        header = publish_release.bit_header(path.read_bytes())
    except publish_release.ReleaseError as e:
        raise BuildError(f"{path}: {e}") from None
    if header["version"] != matrix.VIVADO_VERSION:
        raise BuildError(f"{path}: written by Vivado {header['version']}, not {matrix.VIVADO_VERSION}")
    if header["part"] != entry.part:
        raise BuildError(f"{path}: built for part {header['part']}, not {entry.part} ({entry.board} {entry.variant})")
    return header


def build(entry, repo, run=subprocess.run):
    """Run the entry's gateware script in a build directory that holds nothing from an earlier build."""
    build_dir = repo / entry.build_dir
    if build_dir.exists():
        shutil.rmtree(build_dir)
    result = run([sys.executable, *entry.command()], cwd=repo)
    if result.returncode:
        raise BuildError(f"{' '.join(entry.command())} exited {result.returncode}")


def stage(entry, repo, commit):
    """Check the build and copy what the entry keeps to vivado-artifacts/<id>/. Returns that directory."""
    build_dir = repo / entry.build_dir
    header = check_bit(build_dir / entry.bit, entry)
    missing = [name for name in entry.required if not (build_dir / name).is_file()]
    if missing:
        raise BuildError(f"{entry.id}: the build left no {', '.join(missing)} in {build_dir}")
    kept = sorted({p for pattern in entry.keep for p in build_dir.glob(pattern) if p.is_file()})
    out = repo / ARTIFACTS / entry.id
    if out.exists():
        shutil.rmtree(out)
    files = []
    for src in kept:
        rel = src.relative_to(build_dir)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        data = dst.read_bytes()
        files.append({"path": rel.as_posix(), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    info = {
        "schema": INFO_SCHEMA,
        "id": entry.id,
        "design": entry.design,
        "board": entry.board,
        "variant": entry.variant,
        "golden": entry.golden,
        "source_commit": commit,
        "vivado_version": header["version"],
        "part": header["part"],
        "files": files,
    }
    (out / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    return out


def head_commit(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--id", required=True, help="an entry id from scripts/vivado_matrix.py")
    args = parser.parse_args(argv)
    try:
        entry = matrix.entry(args.id)
    except KeyError:
        sys.exit(f"error: no matrix entry {args.id!r} (uv run --no-project python scripts/vivado_matrix.py lists them)")
    try:
        if shutil.which("vivado") is None:
            raise BuildError(f"vivado is not on the PATH: source {matrix.VIVADO_SETTINGS} first")
        build(entry, REPO)
        out = stage(entry, REPO, head_commit(REPO))
    except BuildError as e:
        sys.exit(f"error: {e}")
    info = json.loads((out / "build-info.json").read_text())
    print(f"{entry.id}: Vivado {info['vivado_version']}, part {info['part']}, {len(info['files'])} files in {out}")
    for f in info["files"]:
        print(f"  {f['sha256']}  {f['path']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and the linter**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py tests/test_vivado_build.py -q`
Expected: `17 passed`.

Run: `uv run --no-project --with ruff ruff check scripts/vivado_build.py tests/test_vivado_build.py` and then `uv run --no-project --with ruff ruff format --check scripts/vivado_build.py tests/test_vivado_build.py`
Expected: `All checks passed!` and `2 files already formatted`.

- [ ] **Step 5: Build for real, where Vivado is installed (desktop.buddy.mithis.com)**

This step is the only local proof that the script drives Vivado. Skip it only on a machine without `/opt/Xilinx/2025.2`, and say so in the pull request.

```bash
uv sync --extra build
source /opt/Xilinx/2025.2/Vivado/settings64.sh
uv run --no-sync python scripts/vivado_build.py --id uart-acorn-cle-215p
```

Expected (about 4 minutes): the last lines are

```
uart-acorn-cle-215p: Vivado 2025.2, part 7a200tfbg484, 6 files in .../vivado-artifacts/uart-acorn-cle-215p
  <sha256>  gateware/sqrl_acorn.bin
  <sha256>  gateware/sqrl_acorn.bit
  <sha256>  gateware/sqrl_acorn_fallback.bin
  <sha256>  gateware/sqrl_acorn_fallback.bit
  <sha256>  gateware/sqrl_acorn_operational.bin
  <sha256>  gateware/sqrl_acorn_operational.bit
```

`vivado-artifacts/` is not ignored yet: add it to `.gitignore` in this step, under the existing `**/build/` line:

```
vivado-artifacts/
```

Run: `git status --short`
Expected: only `.gitignore`, `scripts/vivado_build.py` and `tests/test_vivado_build.py`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore scripts/vivado_build.py tests/test_vivado_build.py
git commit -m "vivado_build: build one matrix entry, check its .bit header, stage the artifact" -m "The header must say Vivado 2025.2 and the entry's part, read with publish_release.py's parser. The artifact carries a build-info.json (commit, Vivado version, each file's sha256) for the release job to check." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 4: the workflow, and keeping the openXC7 bundle independent of it

**Files:**
- Create: `.github/workflows/build-vivado.yml`
- Modify: `.github/workflows/collect-bitstreams.yml` (the step "Wait for every other workflow run on this commit to finish" and the step "Download artifacts from all build workflows")

**Interfaces:**
- Consumes: `scripts/vivado_matrix.py --github-output` (Task 2), `scripts/vivado_build.py --id` (Task 3), runners labelled `[self-hosted, vivado-2025.2]` (Plan 2).
- Produces: workflow named exactly `Build: Vivado` (file `build-vivado.yml`); jobs named `Vivado: <entry.name>`; one artifact per entry named `vivado-<entry.id>` whose root is the staged directory (so `build-info.json` is at the artifact's top level). Task 8's release script finds runs by the file name `build-vivado.yml`.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/build-vivado.yml`:

```yaml
# .github/workflows/build-vivado.yml
#
# Vivado builds of the test designs, beside the openXC7 ones (which stay on GitHub-hosted runners, in the
# build-*.yml workflows). The matrix is scripts/vivado_matrix.py; each entry is one job on a sandboxed
# self-hosted runner (docs/superpowers/specs/2026-09-25-vivado-runners-design.md):
#
#   test    lint and unit-test the scripts below, on a GitHub-hosted runner
#   matrix  print the matrix as JSON, on a GitHub-hosted runner
#   build   one "Vivado: <design> / <board> <variant>" job per entry: scripts/vivado_build.py builds it,
#           fails unless the .bit header says Vivado 2025.2 and the right part, and stages the artifact
#           `vivado-<id>`
#
# The runner is a fresh VM per job with no sudo, no apt, no PyPI and no DNS: only GitHub is reachable, uv,
# Python 3.12, git, make and the RISC-V GCC are already installed, and Vivado is read-only at /opt/Xilinx.
# So the build job installs nothing, and takes its Python packages from the image's uv cache (--frozen).
#
# A pull request from a fork never gets a build job (the `if:` below): forks keep the openXC7 builds.
# This workflow is separate from the build-*.yml ones, and "Collect Bitstreams" leaves it out by name, so
# that a runner outage delays these jobs and nothing else.
name: "Build: Vivado"

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

# A new push to a pull request cancels that pull request's older, now stale, run.
# Anything else (main, workflow_dispatch) is grouped by commit, so it never waits
# behind or cancels another run: every merge builds, exactly as before.
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}
  cancel-in-progress: true

permissions:
  contents: read

env:
  PY: >-
    scripts/vivado_matrix.py scripts/vivado_build.py
    tests/test_vivado_matrix.py tests/test_vivado_build.py
  TESTS: tests/test_vivado_matrix.py tests/test_vivado_build.py

jobs:
  test:
    name: "Vivado CI scripts: lint and unit tests"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Lint
        run: |
          # shellcheck disable=SC2086 # the list is meant to split into paths
          uv run --no-project --with ruff ruff check $PY
          # shellcheck disable=SC2086
          uv run --no-project --with ruff ruff format --check $PY

      - name: Tests
        run: |
          # shellcheck disable=SC2086 # the list is meant to split into paths
          uv run --no-project --python 3.12 --with pytest pytest $TESTS

  matrix:
    name: "Vivado matrix"
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.matrix.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Print the matrix
        id: matrix
        run: uv run --no-project python scripts/vivado_matrix.py --github-output

  build:
    name: "Vivado: ${{ matrix.name }}"
    needs: matrix
    if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
    runs-on: [self-hosted, vivado-2025.2]
    permissions:
      contents: read
    timeout-minutes: 90
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.matrix.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4

      - name: Install Python dependencies (from the image's uv cache)
        run: uv sync --frozen --extra build

      - name: Build with Vivado, check the bitstream, stage the artifact
        shell: bash
        env:
          ENTRY: ${{ matrix.id }}
        run: |
          source /opt/Xilinx/2025.2/Vivado/settings64.sh
          uv run --no-sync python scripts/vivado_build.py --id "$ENTRY"

      - name: Upload the bitstreams
        uses: actions/upload-artifact@v4
        with:
          name: vivado-${{ matrix.id }}
          path: vivado-artifacts/${{ matrix.id }}/
          if-no-files-found: error
```

- [ ] **Step 2: Leave the Vivado workflows out of the bundle's wait**

In `.github/workflows/collect-bitstreams.yml`, replace

```yaml
      # DDR (01:25:18) and PCIe (01:26:42) runs entirely. So wait for every other run on this commit.
      - name: Wait for every other workflow run on this commit to finish
```

with

```yaml
      # DDR (01:25:18) and PCIe (01:26:42) runs entirely. So wait for every other run on this commit.
      #
      # Except the Vivado workflows ("Build: Vivado", "Release: Vivado bitstreams"): their jobs wait for a
      # self-hosted runner, and this bundle is the openXC7 and iCE40 bitstreams only, so a runner outage
      # must not hold it up. Their artifacts (vivado-*) are left out of the bundle below for the same reason.
      - name: Wait for every other workflow run on this commit to finish
```

and, in that step's script, replace

```
              --jq "[.workflow_runs[] | select(.status != \"completed\" and .id != ${RUN_ID} and .name != \"${WORKFLOW}\") | .name] | join(\", \")" || echo "?")"
```

with

```
              --jq "[.workflow_runs[] | select(.status != \"completed\" and .id != ${RUN_ID} and .name != \"${WORKFLOW}\" and (.name | test(\"Vivado\") | not)) | .name] | join(\", \")" || echo "?")"
```

- [ ] **Step 3: Leave their artifacts out of the bundle**

In the step "Download artifacts from all build workflows", replace

```
          # List all workflow runs for this commit
          runs=$(gh api "repos/${{ github.repository }}/actions/runs?head_sha=${HEAD_SHA}&status=completed&per_page=100" \
            --jq '.workflow_runs[] | select(.conclusion == "success") | .id')
```

with

```
          # List all workflow runs for this commit, but the Vivado workflows' (see the wait above)
          runs=$(gh api "repos/${{ github.repository }}/actions/runs?head_sha=${HEAD_SHA}&status=completed&per_page=100" \
            --jq '.workflow_runs[] | select(.conclusion == "success" and (.name | test("Vivado") | not)) | .id')
```

- [ ] **Step 4: Lint the workflows**

Run: `uvx --from actionlint-py actionlint .github/workflows/build-vivado.yml .github/workflows/collect-bitstreams.yml`
Expected: exactly one finding, `label "vivado-2025.2" is unknown` on `build-vivado.yml` (it is the custom runner label), and nothing for `collect-bitstreams.yml`.

Run both new filters against the live API, to see that `gh`'s jq accepts them:

```bash
gh api "repos/fpgas-online/fpgas.online-test-designs/actions/runs?head_sha=$(git rev-parse origin/main)&status=completed&per_page=100" --jq '[.workflow_runs[] | select(.conclusion == "success" and (.name | test("Vivado") | not)) | .name] | join(", ")'
```

Expected: the names of `main`'s successful runs (`Build: UART Test`, `Collect Bitstreams`, ...), exit 0.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/build-vivado.yml .github/workflows/collect-bitstreams.yml
git commit -m "ci: build the Acorn UART with Vivado on the sandboxed runners" -m "A separate workflow, which Collect Bitstreams leaves out of its wait and its bundle by name: a runner outage delays the Vivado jobs and nothing else. Fork pull requests get no Vivado job." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

- [ ] **Step 6: Push, open the pull request, and check what the run did**

```bash
git push -u origin ci/vivado-acorn-uart
gh pr create --base main --head ci/vivado-acorn-uart --title "ci: build the Acorn UART with Vivado on the sandboxed runners" --body-file tmp/pr1-body.md
```

Write `tmp/pr1-body.md` first (`tmp/` is ignored), with this text; the "Checked" list is filled in from the exit check below with `gh pr edit --body-file`:

```markdown
Builds one design, the Acorn CLE-215+ UART SoC, with Vivado 2025.2 on the sandboxed self-hosted runners,
beside the unchanged openXC7 builds. First of three pull requests of
`docs/superpowers/plans/2026-10-02-vivado-runners-3-test-designs-ci.md`; the rest of the matrix and the
release workflow follow.

- `designs/_shared/yosys_workarounds.py`: `patch_yosys_template()` no longer asserts on the Vivado
  toolchain, which has no Yosys template. Before this, no LiteX SoC design built with `--toolchain vivado`.
- `scripts/vivado_matrix.py`: the Vivado build matrix (one entry for now), printed as JSON for the workflow.
- `scripts/vivado_build.py`: builds one entry, fails unless the `.bit` header says Vivado 2025.2 and the
  entry's part, and stages the artifact with a `build-info.json`.
- `.github/workflows/build-vivado.yml`: the `Build: Vivado` workflow. Fork pull requests get no Vivado job.
- `.github/workflows/collect-bitstreams.yml`: leaves the Vivado workflows out of its wait and its bundle.

## One workflow, not jobs in each build-*.yml

The spec put Vivado jobs in each `build-*.yml`. `Collect Bitstreams` waits for every other workflow run of
the commit and downloads artifacts only from completed runs, so a Vivado job waiting for a runner inside
`build-uart-test.yml` would stall the openXC7 bundle. A separate workflow, left out by name, means a runner
outage delays the Vivado jobs and nothing else.

## Checked

- [ ] `Vivado: uart / Acorn cle-215+` succeeded on runner `...` in run `...` (head `...`), in `...` minutes
- [ ] its log: `uart-acorn-cle-215p: Vivado 2025.2, part 7a200tfbg484, 6 files`
- [ ] artifact `vivado-uart-acorn-cle-215p` exists
- [ ] `all-bitstreams` of the same commit has no `vivado-*` directory

Not exercised: the fork guard (no fork pull request exists), a runner outage, any other design.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
```

**Exit check for pull request 1.** Record each result, with the run id, in the pull request before asking for the merge.

1. The run is this commit's: `gh run list --workflow build-vivado.yml --branch ci/vivado-acorn-uart --json databaseId,headSha,status,conclusion --limit 5`, and the row whose `headSha` equals `git rev-parse HEAD` has `conclusion` `success`.
2. The Vivado job ran on a sandboxed runner: `gh run view <id> --json jobs --jq '.jobs[] | "\(.name) \(.conclusion) \(.runnerName)"'` shows `Vivado: uart / Acorn cle-215+ success <host>-slot<N>-<uuid>`.
3. The header check ran on real output: `gh run view <id> --log | grep "Vivado 2025.2, part 7a200tfbg484"` prints the `uart-acorn-cle-215p: ... 6 files` line.
4. The artifact exists: `gh api repos/fpgas-online/fpgas.online-test-designs/actions/runs/<id>/artifacts --jq '.artifacts[].name'` prints `vivado-uart-acorn-cle-215p`.
5. The openXC7 bundle did not take it: download `all-bitstreams` from this commit's `Collect Bitstreams` run with `gh run download <collect run id> --name all-bitstreams --dir tmp/pr1-bundle`, then `ls tmp/pr1-bundle` shows no directory starting with `vivado-`. Remove `tmp/pr1-bundle` afterwards.
6. Write down the job's duration (`gh run view <id> --json jobs --jq '.jobs[] | "\(.name) \(.startedAt) \(.completedAt)"'`): Task 5 uses it to estimate the full matrix.

What this run exercises: checkout, `uv sync --frozen --extra build` from the image's cache, a Vivado build of one SoC, the header check, artifact upload through the proxy, and the bundle's independence. What it does not: the fork guard (no fork pull request exists; it is the `if:` line, read it), a runner outage, and any design but this one.

---

# Pull request 2: the whole matrix (`ci/vivado-matrix`)

After pull request 1 is merged. Worktree `.worktrees/ci-vivado-matrix`, branch `ci/vivado-matrix` from the new `origin/main`.

### Task 5: every design, board and variant

**Files:**
- Modify: `scripts/vivado_matrix.py` (the docstring's second paragraph and the four tables)
- Modify: `tests/test_vivado_matrix.py` (replace), `tests/test_vivado_build.py` (append)

**Interfaces:**
- Consumes: Tasks 2 and 3 as they are.
- Produces: `ENTRIES` with 39 entries, ids as in "The matrix" above: `<design>-<board>-<variant with p for +>` and `acorn-pcie-acorn-<variant>[-golden]`. `Entry.required` is non-empty only for the `acorn-pcie` entries (`ACORN_PCIE_IMAGES` + `csr.json`, `csr.csv`): the tree `publish_release.py` reads.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_vivado_matrix.py` with:

```python
"""The Vivado build matrix (scripts/vivado_matrix.py): what CI builds with Vivado, and how each job is named."""

import fnmatch
import importlib.util
import json
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vivado_matrix", _ROOT / "scripts" / "vivado_matrix.py")
vm = importlib.util.module_from_spec(_spec)
sys.modules["vivado_matrix"] = vm  # dataclasses looks its module up there
_spec.loader.exec_module(vm)


def test_the_matrix_is_every_design_on_every_board_it_supports():
    ids = [e.id for e in vm.ENTRIES]
    assert len(ids) == len(set(ids)) == 39
    # 4 SoC designs and 2 bare ones on 6 board variants, less ethernet-test on the Acorns (no Ethernet there)
    assert len([i for i in ids if not i.startswith("acorn-pcie-")]) == 6 * 6 - 3
    assert "uart-acorn-cle-215p" in ids
    assert "ethernet-test-netv2-a7-100" in ids
    assert not any(i.startswith("ethernet-test-acorn") for i in ids)
    assert not any(i.startswith("pcie-enumeration") for i in ids)
    assert [i for i in ids if i.startswith("acorn-pcie-")] == [
        "acorn-pcie-acorn-cle-215p",
        "acorn-pcie-acorn-cle-215p-golden",
        "acorn-pcie-acorn-cle-215",
        "acorn-pcie-acorn-cle-215-golden",
        "acorn-pcie-acorn-cle-101",
        "acorn-pcie-acorn-cle-101-golden",
    ]


def test_ids_are_safe_as_artifact_and_file_names():
    for e in vm.ENTRIES:
        assert re.fullmatch(r"[a-z0-9-]+", e.id), e.id


def test_every_entry_names_a_gateware_script_that_exists():
    for e in vm.ENTRIES:
        assert (_ROOT / e.script).is_file(), e.script


def test_every_entry_has_a_part_and_keeps_its_bit():
    for e in vm.ENTRIES:
        assert e.part == vm.PARTS[(e.board, e.variant)]
        assert any(fnmatch.fnmatch(e.bit, pattern) for pattern in e.keep), e.id


def test_the_command_builds_with_vivado():
    e = vm.entry("uart-acorn-cle-215p")
    assert e.command() == [
        "designs/uart/gateware/uart_soc_acorn.py",
        "--variant",
        "cle-215+",
        "--toolchain",
        "vivado",
        "--build",
    ]
    assert e.build_dir == "designs/uart/build/acorn"
    assert e.bit == "gateware/sqrl_acorn.bit"
    assert e.part == "7a200tfbg484"


def test_bare_designs_build_as_top_beside_no_gateware_directory():
    e = vm.entry("pmod-pin-id-netv2-a7-35")
    assert (e.build_dir, e.bit, e.keep) == ("designs/pmod-pin-id/build/netv2", "top.bit", ("*.bit", "*.bin"))


def test_the_golden_acorn_pcie_build_has_its_own_directory_and_flag():
    e = vm.entry("acorn-pcie-acorn-cle-215p-golden")
    assert e.command()[-2:] == ["--golden", "--build"]
    assert e.build_dir == "designs/acorn-pcie/build/acorn-cle-215+-golden"
    assert "csr.json" in e.required and "gateware/sqrl_acorn_fallback.bin" in e.required


def test_job_names_cannot_match_the_bundle_job_patterns():
    # collect-bitstreams.yml waits for check runs named ^(Arty|NeTV2|Fomu|TT FPGA|netv2): the workflow
    # prefixes these names with "Vivado: ", and none may start with a board name on its own.
    for row in vm.as_matrix()["include"]:
        assert not re.match(r"(Arty|NeTV2|Fomu|TT FPGA|netv2)", row["name"]), row["name"]
        assert set(row) == {"id", "name"}


def test_unknown_id_is_a_key_error():
    try:
        vm.entry("uart-arty-a7-200")
    except KeyError as e:
        assert e.args == ("uart-arty-a7-200",)
    else:
        raise AssertionError("no KeyError")


def test_github_output_is_one_line_of_json(tmp_path, monkeypatch):
    out = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    vm.main(["--github-output"])
    key, _, value = out.read_text().rstrip("\n").partition("=")
    assert key == "matrix" and "\n" not in value
    assert json.loads(value) == vm.as_matrix()
```

Append to `tests/test_vivado_build.py`:

```python
def test_a_build_missing_a_file_the_release_needs_is_refused(tmp_path):
    entry = vb.matrix.entry("acorn-pcie-acorn-cle-215p")
    build_dir = built(tmp_path, entry)
    (build_dir / "csr.json").unlink()
    with pytest.raises(vb.BuildError, match=r"the build left no csr\.json"):
        vb.stage(entry, tmp_path, COMMIT)


def test_the_acorn_pcie_artifact_is_the_tree_publish_release_reads(tmp_path):
    entry = vb.matrix.entry("acorn-pcie-acorn-cle-215p-golden")
    built(tmp_path, entry)
    out = vb.stage(entry, tmp_path, COMMIT)
    names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert names == sorted(["build-info.json", "csr.csv", "csr.json", *vb.matrix.ACORN_PCIE_IMAGES])
    assert json.loads((out / "build-info.json").read_text())["golden"] is True
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py tests/test_vivado_build.py -q`
Expected: failures in `test_the_matrix_is_every_design_on_every_board_it_supports` (`assert 1 == 39`) and `KeyError` for `pmod-pin-id-netv2-a7-35` and the `acorn-pcie-...` ids.

- [ ] **Step 3: Fill in the tables**

Replace `scripts/vivado_matrix.py` with:

```python
#!/usr/bin/env python3
"""The Vivado build matrix: every design x board x variant that CI builds with Vivado.

One list, with two readers:

  * .github/workflows/build-vivado.yml asks for it as JSON (`--github-output`) and runs one job per entry;
  * scripts/vivado_build.py builds one entry and checks what Vivado left.

It mirrors the boards the openXC7 jobs build (the Arty A7-35T, both NeTV2s, the three Acorns), plus the Acorn
PCIe SoC, which only Vivado builds. pcie-enumeration is not here: with `--toolchain vivado` it adds both the
open pcie_7x core and the Xilinx IP, two definitions of `pcie_s7` (pull request #14 has the fix).

Standard library only, so the workflow's first job runs it without installing anything.

    uv run --no-project python scripts/vivado_matrix.py          # list the entries and their commands
"""

import argparse
import dataclasses
import json
import os

VIVADO_VERSION = "2025.2"
VIVADO_SETTINGS = "/opt/Xilinx/2025.2/Vivado/settings64.sh"
FLOW = "vivado-vivado"  # Vivado synthesis, Vivado place and route: the name the 2026-04 release used

# The part Vivado writes in a .bit header, read from the files of release vivado-bitstreams-v0.0-496-gf162f60.
PARTS = {
    ("arty", "a7-35"): "7a35ticsg324",
    ("netv2", "a7-35"): "7a35tfgg484",
    ("netv2", "a7-100"): "7a100tfgg484",
    ("acorn", "cle-215+"): "7a200tfbg484",
    ("acorn", "cle-215"): "7a200tfbg484",
    ("acorn", "cle-101"): "7a100tfgg484",
}
PLATFORM = {"arty": "digilent_arty", "netv2": "kosagi_netv2", "acorn": "sqrl_acorn"}
BOARD_TITLE = {"arty": "Arty", "netv2": "NeTV2", "acorn": "Acorn"}
VARIANTS = {"arty": ("a7-35",), "netv2": ("a7-35", "a7-100"), "acorn": ("cle-215+", "cle-215", "cle-101")}

# LiteX SoCs: Builder writes <build dir>/gateware/<platform>.bit. (design, gateware script, boards)
SOC_DESIGNS = (
    ("uart", "uart_soc_{board}.py", ("arty", "netv2", "acorn")),
    ("spi-flash-id", "spiflash_soc_{board}.py", ("arty", "netv2", "acorn")),
    ("ddr-memory", "ddr_soc_{board}.py", ("arty", "netv2", "acorn")),
    ("ethernet-test", "ethernet_soc_{board}.py", ("arty", "netv2")),
)
# Bare modules built with platform.build(): no gateware/ directory, and the build is named "top".
BARE_DESIGNS = (
    ("pmod-loopback", "gpio_loopback_{board}.py", ("arty", "netv2", "acorn")),
    ("pmod-pin-id", "pmod_pin_id_{board}.py", ("arty", "netv2", "acorn")),
)
# The Acorn PCIe SoC: each variant as the operational image and as the golden one.
ACORN_PCIE_VARIANTS = ("cle-215+", "cle-215", "cle-101")
ACORN_PCIE_IMAGES = tuple(
    f"gateware/sqrl_acorn{suffix}{ext}" for suffix in ("", "_fallback", "_operational") for ext in (".bin", ".bit")
)


@dataclasses.dataclass(frozen=True)
class Entry:
    design: str  # the directory under designs/
    board: str  # arty, netv2 or acorn
    variant: str  # as the gateware script's --variant takes it
    script: str  # the gateware script, from the repository root
    build_dir: str  # where that script builds, from the repository root
    bit: str  # the plain .bit, from build_dir: the file whose header is checked
    keep: tuple  # globs from build_dir: what the job's artifact carries
    required: tuple = ()  # files from build_dir that must exist besides `bit`
    extra_args: tuple = ()
    golden: bool = False

    @property
    def slug(self):
        """The variant as file and artifact names spell it: `+` is `p`."""
        return self.variant.replace("+", "p")

    @property
    def id(self):
        return f"{self.design}-{self.board}-{self.slug}" + ("-golden" if self.golden else "")

    @property
    def name(self):
        return f"{self.design} / {BOARD_TITLE[self.board]} {self.variant}" + (" (golden)" if self.golden else "")

    @property
    def part(self):
        return PARTS[(self.board, self.variant)]

    def command(self):
        """The gateware script and its arguments (run with the project's Python, from the repository root)."""
        return [self.script, "--variant", self.variant, "--toolchain", "vivado", *self.extra_args, "--build"]


def _entries():
    out = []
    for design, script, boards in SOC_DESIGNS:
        for board in boards:
            for variant in VARIANTS[board]:
                out.append(
                    Entry(
                        design=design,
                        board=board,
                        variant=variant,
                        script=f"designs/{design}/gateware/{script.format(board=board)}",
                        build_dir=f"designs/{design}/build/{board}",
                        bit=f"gateware/{PLATFORM[board]}.bit",
                        keep=("gateware/*.bit", "gateware/*.bin"),
                    )
                )
    for design, script, boards in BARE_DESIGNS:
        for board in boards:
            for variant in VARIANTS[board]:
                out.append(
                    Entry(
                        design=design,
                        board=board,
                        variant=variant,
                        script=f"designs/{design}/gateware/{script.format(board=board)}",
                        build_dir=f"designs/{design}/build/{board}",
                        bit="top.bit",
                        keep=("*.bit", "*.bin"),
                    )
                )
    for variant in ACORN_PCIE_VARIANTS:
        for golden in (False, True):
            out.append(
                Entry(
                    design="acorn-pcie",
                    board="acorn",
                    variant=variant,
                    script="designs/acorn-pcie/gateware/acorn_pcie_soc.py",
                    build_dir=f"designs/acorn-pcie/build/acorn-{variant}{'-golden' if golden else ''}",
                    bit="gateware/sqrl_acorn.bit",
                    keep=("gateware/sqrl_acorn*.bit", "gateware/sqrl_acorn*.bin", "csr.json", "csr.csv"),
                    required=(*ACORN_PCIE_IMAGES, "csr.json", "csr.csv"),
                    extra_args=("--golden",) if golden else (),
                    golden=golden,
                )
            )
    return tuple(out)


ENTRIES = _entries()


def entry(entry_id):
    """The entry with that id; KeyError if there is none."""
    for e in ENTRIES:
        if e.id == entry_id:
            return e
    raise KeyError(entry_id)


def as_matrix(entries=ENTRIES):
    """What `strategy.matrix` takes: one {id, name} per entry."""
    return {"include": [{"id": e.id, "name": e.name} for e in entries]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--github-output", action="store_true", help="append matrix=<json> to $GITHUB_OUTPUT")
    args = parser.parse_args(argv)
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json.dumps(as_matrix(), separators=(',', ':'))}\n")
        print(f"{len(ENTRIES)} Vivado builds")
        return
    for e in ENTRIES:
        print(f"{e.id:42} {' '.join(e.command())}")


if __name__ == "__main__":
    main()
```

Only the docstring's second paragraph and the tables `VARIANTS`, `SOC_DESIGNS`, `BARE_DESIGNS` and `ACORN_PCIE_VARIANTS` differ from pull request 1.

- [ ] **Step 4: Run the tests, the linter and the list**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py tests/test_vivado_build.py -q`
Expected: `21 passed`.

Run: `uv run --no-project --with ruff ruff check scripts/vivado_matrix.py tests/test_vivado_matrix.py tests/test_vivado_build.py` and then the same paths with `ruff format --check`
Expected: `All checks passed!` and `3 files already formatted`.

Run: `uv run --no-project python scripts/vivado_matrix.py`
Expected: 39 lines, the first `uart-arty-a7-35 ...`, the last `acorn-pcie-acorn-cle-101-golden   designs/acorn-pcie/gateware/acorn_pcie_soc.py --variant cle-101 --toolchain vivado --golden --build`.

- [ ] **Step 5: Check that every entry constructs under Vivado before spending runner time**

No Vivado is needed: without `--build` the scripts stop after elaboration. Write `tmp/vivado_elab.py`:

```python
"""Run every matrix entry's gateware script with --toolchain vivado and no --build: each must exit 0."""

import importlib.util
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vivado_matrix", REPO / "scripts" / "vivado_matrix.py")
matrix = importlib.util.module_from_spec(spec)
sys.modules["vivado_matrix"] = matrix
spec.loader.exec_module(matrix)

failed = []
for entry in matrix.ENTRIES:
    argv = [a for a in entry.command() if a != "--build"]
    if entry.design == "acorn-pcie":
        argv.append("--no-compile-software")  # its Builder runs even without --build
    result = subprocess.run([sys.executable, *argv], cwd=REPO, capture_output=True, text=True)
    print(f"rc={result.returncode} {entry.id}")
    if result.returncode:
        failed.append(entry.id)
        print((result.stdout + result.stderr)[-800:])
sys.exit(f"did not construct: {', '.join(failed)}" if failed else 0)
```

Run: `uv run --extra build python tmp/vivado_elab.py`
Expected: 39 lines `rc=0 <id>` and exit 0. Then delete `tmp/vivado_elab.py` and the `designs/*/build` directories it made (`git status --short --ignored designs` lists them).

- [ ] **Step 6: Commit**

```bash
git add scripts/vivado_matrix.py tests/test_vivado_matrix.py tests/test_vivado_build.py
git commit -m "vivado_matrix: every Xilinx test design on every board, and the Acorn PCIe SoC" -m "33 test-design builds on the boards the openXC7 jobs build, and the Acorn PCIe SoC's six images (three variants, operational and golden). pcie-enumeration is left out: under Vivado it defines pcie_s7 twice (see #14)." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 6: document the Vivado jobs, and get the matrix green

**Files:**
- Modify: `docs/toolchains/github-actions.md` (a new section before `## Toolchain Installation in CI`)

**Interfaces:**
- Consumes: the workflow and scripts as merged and as changed in Task 5.
- Produces: documentation only.

- [ ] **Step 1: Add the section**

In `docs/toolchains/github-actions.md`, insert before the line `## Toolchain Installation in CI`:

````markdown
## Vivado builds (sandboxed self-hosted runners)

The builds above use open toolchains on GitHub-hosted runners. The Xilinx designs are also built with AMD
Vivado 2025.2, by the `Build: Vivado` workflow (`.github/workflows/build-vivado.yml`), on sandboxed
self-hosted runners (selected by label; which machines they are on does not matter). Vivado cannot go in a public runner image: its licence allows
installing it, not redistributing it.

The design is in
[`docs/superpowers/specs/2026-09-25-vivado-runners-design.md`](../superpowers/specs/2026-09-25-vivado-runners-design.md).
What a workflow author needs to know:

- **Each job gets a fresh VM that is destroyed afterwards.** It has no `sudo`, no `apt`, no PyPI and no
  DNS; only GitHub is reachable. `uv`, Python 3.12, `git`, `make` and the RISC-V GCC are installed, the uv
  cache already holds everything in `uv.lock`, and Vivado is read-only at `/opt/Xilinx/2025.2`. A job
  installs nothing: it runs `uv sync --frozen --extra build`, then
  `source /opt/Xilinx/2025.2/Vivado/settings64.sh`.
- **A change to `uv.lock` that adds or bumps a PyPI package fails** with a proxy refusal naming `pypi.org`
  until the runner image is rebuilt. The openXC7 jobs are not affected.
- **The matrix is `scripts/vivado_matrix.py`**, not YAML: one row per design, board and variant.
  `uv run --no-project python scripts/vivado_matrix.py` lists the entries and their commands. To build a
  new design with Vivado, add its row there; `tests/test_vivado_matrix.py` checks the list.
- **Each entry is one job named `Vivado: <design> / <board> <variant>`**, which runs
  `scripts/vivado_build.py --id <id>`. The job fails unless the `.bit` header says Vivado 2025.2 wrote it
  for the entry's part. Its artifact is `vivado-<id>`: the bitstreams and a `build-info.json` with the
  commit, the Vivado version and each file's sha256.
- **Who gets Vivado builds:** pushes to `main`, manual runs, and pull requests from branches of this
  repository. A pull request from a fork gets the openXC7 builds only.
- **The openXC7 bundle does not depend on them.** `Collect Bitstreams` leaves the Vivado workflows out of
  its wait and out of `all-bitstreams`, so a runner outage delays the `Vivado:` jobs and nothing else. Do
  not make them required status checks.
- **Not built with Vivado:** `pcie-enumeration`, whose SoCs define `pcie_s7` twice under Vivado (the open
  `pcie_7x` core and the Xilinx IP).

To run one entry by hand on a machine with Vivado:

```bash
uv sync --extra build
source /opt/Xilinx/2025.2/Vivado/settings64.sh
uv run --no-sync python scripts/vivado_build.py --id uart-acorn-cle-215p
```

````

- [ ] **Step 2: Fix the sentence above it that is no longer true**

In the same file, in the list under `## Strategy`, replace

```markdown
1. **Build** (GitHub-hosted runners) -- Install toolchains, synthesize bitstreams,
   upload artifacts.
```

with

```markdown
1. **Build** (GitHub-hosted runners, and for Vivado sandboxed self-hosted ones --
   see "Vivado builds" below) -- Install toolchains, synthesize bitstreams,
   upload artifacts.
```

- [ ] **Step 3: Commit, push, open the pull request**

```bash
git add docs/toolchains/github-actions.md
git commit -m "docs(github-actions): the Vivado jobs and what their runner gives them" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
git push -u origin ci/vivado-matrix
gh pr create --base main --head ci/vivado-matrix --title "ci: build every Xilinx test design with Vivado" --body-file tmp/pr2-body.md
```

Write `tmp/pr2-body.md` first, with this text; fill "Checked" in from the exit check below:

```markdown
Builds every Xilinx test design with Vivado 2025.2 on the sandboxed runners: 33 test-design builds on the
boards the openXC7 jobs build (Arty A7-35T, NeTV2 A7-35T and A7-100T, Acorn CLE-215+, CLE-215 and CLE-101),
and the Acorn PCIe SoC's six images (three variants, operational and golden). Second of three pull requests
of `docs/superpowers/plans/2026-10-02-vivado-runners-3-test-designs-ci.md`.

- `scripts/vivado_matrix.py`: the full matrix, 39 entries.
- `docs/toolchains/github-actions.md`: what the Vivado jobs are and what their runner gives them.

Not in the matrix: `pcie-enumeration`. Under Vivado its SoCs define `pcie_s7` twice (the open `pcie_7x`
core, added unconditionally, and the Xilinx IP that `S7PCIEPHY` emits). The fix is on #14.

## Checked

- [ ] all 39 `Vivado:` jobs succeeded in run `...` (head `...`)
- [ ] one `vivado-<id>` artifact per entry
- [ ] `build-info.json` of `vivado-uart-arty-a7-35`, `vivado-ddr-memory-netv2-a7-100` and
      `vivado-acorn-pcie-acorn-cle-215p-golden`: Vivado 2025.2, parts `7a35ticsg324`, `7a100tfgg484`, `7a200tfbg484`
- [ ] the whole run took `...` minutes, the longest job `...` (`...` minutes), `...` jobs at once
- [ ] `Collect Bitstreams` succeeded and `all-bitstreams` has no `vivado-*` directory

Not exercised: the bitstreams on hardware (no board is programmed), and Vivado's timing reports.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
```

- [ ] **Step 4: Get all 39 jobs green**

Find the run as in pull request 1's exit check (by `headSha`), then:

Run: `gh run view <id> --json jobs --jq '.jobs[] | select(.name | startswith("Vivado: ")) | "\(.conclusion) \(.name)"'`
Expected: 39 lines, all `success`.

If a job fails, read its log (`gh run view <id> --log-failed`) and decide by what failed:

- **The runner** (no route to GitHub, `uv sync` refused by the proxy, the VM killed): that is Plan 2's to fix. Do not change this pull request; re-run the job when the runner is fixed.
- **The design under Vivado** (a Vivado `ERROR:`, a missing output, the header check): fix the design in this pull request if the fix is small and belongs to the design. If it is not, remove that row from its table in `scripts/vivado_matrix.py`, update the count in `tests/test_vivado_matrix.py`, add the design to "Not built with Vivado" in the documentation with the error, and open an issue titled `Vivado build fails: <id>` quoting the error. Never use `continue-on-error`: a red job nobody reads is worse than a missing one.

**Exit check for pull request 2.**

1. All 39 `Vivado:` jobs `success` in the run whose `headSha` is the pushed commit (or the reduced count, with the removed rows listed in the pull request).
2. `gh api repos/fpgas-online/fpgas.online-test-designs/actions/runs/<id>/artifacts --paginate --jq '.artifacts[].name'` lists one `vivado-<id>` per entry.
3. For three artifacts of different boards (`vivado-uart-arty-a7-35`, `vivado-ddr-memory-netv2-a7-100`, `vivado-acorn-pcie-acorn-cle-215p-golden`), download each into `tmp/pr2-check/` with `gh run download <id> --name <artifact> --dir tmp/pr2-check/<artifact>` and read `build-info.json`: `vivado_version` is `2025.2`, `part` is `7a35ticsg324`, `7a100tfgg484` and `7a200tfbg484`. Remove `tmp/pr2-check` afterwards.
4. Record in the pull request: the wall-clock time of the whole run, the longest job, and how many jobs ran at once. These are the numbers for decision CI-5.
5. The `Collect Bitstreams` run of the same commit succeeded and its `all-bitstreams` has no `vivado-` directory.

What this run exercises: every design in the matrix through Vivado on the runners. What it does not: that the bitstreams work on hardware (no board is programmed), and Vivado's timing reports (see CI-6).

---

# Pull request 3: releases from CI (`ci/vivado-release`)

After pull request 2 is merged and `main`'s `Build: Vivado` run of the merge commit has succeeded. Worktree `.worktrees/ci-vivado-release`, branch `ci/vivado-release` from the new `origin/main`.

### Task 7: `publish_release.py` accepts a stated source for a tree made from CI artifacts

`publish_release.py` proves where a build tree came from by looking at the git worktree around it. A tree put together from downloaded artifacts has no such worktree; what proves its source is the run that built it and the commit each artifact recorded.

**Files:**
- Modify: `designs/acorn-pcie/tools/publish_release.py` (the module docstring; `main()`)
- Modify: `tests/test_acorn_pcie_publish_release.py` (append two tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `publish_release.py --source-evidence TEXT`: `TEXT` becomes the manifest's `source_commit_evidence` and `verify_source()` is not called. It is an error together with `--unverified-source-commit`. `main(argv)` is called by Task 8 with a list of arguments.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_acorn_pcie_publish_release.py`:

```python
def test_stated_evidence_replaces_the_worktree_check(build, tmp_path):
    # `build` is in no git worktree: without the statement, verify_source() refuses it.
    out = tmp_path / "staged"
    evidence = "built by GitHub Actions run 123 from f3355dccf443"
    pr.main(["--build-dir", str(build), "--source-commit", "HEAD", "--source-evidence", evidence, "--out", str(out)])
    assert json.loads((out / "manifest.json").read_text())["source_commit_evidence"] == evidence


def test_stated_evidence_does_not_combine_with_the_override(build, tmp_path):
    with pytest.raises(SystemExit):
        pr.main(
            [
                "--build-dir",
                str(build),
                "--source-commit",
                "HEAD",
                "--source-evidence",
                "x",
                "--unverified-source-commit",
            ]
        )
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_acorn_pcie_publish_release.py -q`
Expected: `1 failed, 26 passed`. `test_stated_evidence_replaces_the_worktree_check` fails with `SystemExit: 2` (argparse: `unrecognized arguments: --source-evidence`). The other new test passes already, for the wrong reason (the same argparse error is a `SystemExit`); after Step 3 it passes because of `parser.error`.

- [ ] **Step 3: Add the option**

In `designs/acorn-pcie/tools/publish_release.py`, in the module docstring replace

```
(build/ itself is ignored). `--unverified-source-commit` skips the check, and
the manifest says so either way.
```

with

```
(build/ itself is ignored). `--unverified-source-commit` skips the check, and
the manifest says so either way. A tree put together from CI artifacts
(scripts/vivado_release.py) has no such worktree: `--source-evidence` then
states the run that built it, and the manifest records that instead.
```

In `main()`, replace

```python
    parser.add_argument("--variants", nargs="+", help="variant directories to include (default: all)")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="staging directory")
    parser.add_argument("--repo", default="fpgas-online/fpgas.online-test-designs")
    parser.add_argument("--publish", action="store_true", help="create the GitHub Release (default: stage only)")
    args = parser.parse_args(argv)

    try:
        source = source_identity(_REPO, args.source_commit)
        source["evidence"] = verify_source(args.build_dir, source["commit"], args.unverified_source_commit)
```

with

```python
    parser.add_argument(
        "--source-evidence",
        help="what shows the build tree was built from --source-commit, recorded in the manifest in place of the "
        "worktree check (CI: the run that built it, whose artifacts record the commit)",
    )
    parser.add_argument("--variants", nargs="+", help="variant directories to include (default: all)")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="staging directory")
    parser.add_argument("--repo", default="fpgas-online/fpgas.online-test-designs")
    parser.add_argument("--publish", action="store_true", help="create the GitHub Release (default: stage only)")
    args = parser.parse_args(argv)
    if args.source_evidence and args.unverified_source_commit:
        parser.error("--source-evidence states what was checked; it does not combine with --unverified-source-commit")

    try:
        source = source_identity(_REPO, args.source_commit)
        source["evidence"] = args.source_evidence or verify_source(
            args.build_dir, source["commit"], args.unverified_source_commit
        )
```

- [ ] **Step 4: Run the tests and the linter**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_acorn_pcie_publish_release.py -q`
Expected: `27 passed`.

Run: `uv run --no-project --with ruff ruff check designs/acorn-pcie/tools/publish_release.py tests/test_acorn_pcie_publish_release.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add designs/acorn-pcie/tools/publish_release.py tests/test_acorn_pcie_publish_release.py
git commit -m "publish_release: --source-evidence, for a build tree made from CI artifacts" -m "Such a tree has no worktree to check: the run that built it and the commit each artifact recorded are the evidence, and the manifest now says which it was." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 8: put a release together from a run's artifacts

**Files:**
- Create: `scripts/vivado_release.py`
- Test: `tests/test_vivado_release.py`
- Modify: `scripts/vivado_matrix.py` (docstring: the third reader)
- Modify: `.github/workflows/build-vivado.yml` (`env`: lint and test the new files on every pull request)

**Interfaces:**
- Consumes: `vivado_matrix.ENTRIES`, `Entry.slug`, `FLOW`, `VIVADO_VERSION`, `VIVADO_SETTINGS`; the artifact layout and `build-info.json` of Task 3; workflow file name `build-vivado.yml` (Task 4); `publish_release.main(argv)` with `--source-evidence` (Task 7).
- Produces, in module `vivado_release`:
  - `ReleaseError`
  - `find_run(repo, commit, api=gh_json) -> dict` (the GitHub run object: `id`, `html_url`, `head_sha`, `head_branch`, `event`, `conclusion`, `created_at`)
  - `asset_name(entry, path) -> str`: `<design>_<board>-<slug>_vivado-vivado_<file name>`
  - `read_artifact(artifacts, entry, commit) -> [(recorded file dict, pathlib.Path)]`
  - `collect(artifacts, commit, describe, run, generated_at, entries=None) -> (manifest, {file name: path})`
  - `stage(manifest, staged, out) -> [paths]`, `release_notes(manifest) -> str`
  - `acorn_pcie_tree(artifacts, commit, tree, entries=None) -> [variant directories]`
  - CLI: `--commit REV --kind {all-designs,acorn-pcie} [--publish {true,false}] [--work DIR] [--repo OWNER/NAME]`. It stages into `<work>/vivado-release/` (+ `<work>/vivado-release-notes.md`) or, for `acorn-pcie`, lays the tree out in `<work>/acorn-pcie-ci-build/` and has `publish_release.py` stage into `<work>/acorn-pcie-release/`. `<work>` defaults to the repository's `tmp/`.
  - The all-designs `manifest.json` (schema 1, the keys of release `vivado-bitstreams-v0.0-496-gf162f60`, plus `build.run_id` and `build.run_url`):
    `{"schema": 1, "generated_at", "git": {"describe", "sha", "branch", "dirty"}, "tool": {"vivado_version", "settings_path"}, "build": {"flows", "make_targets", "jobs", "run_id", "run_url"}, "artifacts": [{"filename", "design", "board", "variant", "flow", "size_bytes", "sha256"}]}`.
    `SHA256SUMS` lists the bitstreams only, as that release's did. `tool.vivado_version` is the `.bit` header's `2025.2`, where that release had `vivado -version`'s `vivado v2025.2 (64-bit)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vivado_release.py`:

```python
"""scripts/vivado_release.py: a release is put together from one CI run's artifacts, all of them or none.

The artifacts are made by vivado_build.stage() from synthetic build trees, so they are what the Vivado jobs
upload: `vivado-<id>/` holding the kept files and a build-info.json.
"""

import hashlib
import importlib.util
import json
import pathlib
import shutil
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vr = _load("vivado_release")
vb = _load("vivado_build")

COMMIT = "e568a408e7bd" + "0" * 28
RUN = {
    "id": 4242,
    "html_url": "https://github.com/fpgas-online/fpgas.online-test-designs/actions/runs/4242",
    "head_sha": COMMIT,
    "head_branch": "main",
    "conclusion": "success",
    "event": "push",
    "created_at": "2026-10-02T01:00:00Z",
}
NOW = "2026-10-02T02:00:00+00:00"


def _bit(entry):
    def field(key, text):
        raw = text.encode() + b"\x00"
        return key + len(raw).to_bytes(2, "big") + raw

    head = bytes.fromhex("0009") + bytes.fromhex("0ff00ff00ff00ff000") + bytes.fromhex("0001")
    head += field(b"a", f"top;UserID=0XFFFFFFFF;Version={vr.matrix.VIVADO_VERSION}")
    head += field(b"b", entry.part) + field(b"c", "2026/10/02") + field(b"d", "09:30:00")
    body = entry.id.encode()
    return head + b"e" + len(body).to_bytes(4, "big") + body


def upload(artifacts, entry, commit=COMMIT):
    """What the entry's Vivado job uploads, as `gh run download` unpacks it under `artifacts`."""
    repo = artifacts.parent / "checkout" / entry.id
    build_dir = repo / entry.build_dir
    for name in (entry.bit, *entry.required):
        (build_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (build_dir / name).write_bytes(_bit(entry) if name == entry.bit else f"{entry.id} {name}".encode())
    staged = vb.stage(entry, repo, commit)
    shutil.copytree(staged, artifacts / f"vivado-{entry.id}")


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "vivado-run-4242"
    for entry in vr.matrix.ENTRIES:
        upload(root, entry)
    return root


def _collect(artifacts, **kw):
    return vr.collect(artifacts, kw.pop("commit", COMMIT), "v0.0-900-ge568a40", RUN, NOW, **kw)


def test_files_are_named_as_the_first_release_named_them(artifacts):
    manifest, staged = _collect(artifacts)
    names = [a["filename"] for a in manifest["artifacts"]]
    assert names == sorted(names) == sorted(staged)
    assert "uart_acorn-cle-215p_vivado-vivado_sqrl_acorn.bit" in names
    assert "ethernet-test_netv2-a7-100_vivado-vivado_kosagi_netv2.bit" in names
    assert "pmod-pin-id_arty-a7-35_vivado-vivado_top.bit" in names


def test_the_acorn_pcie_images_are_not_in_the_all_designs_release(artifacts):
    manifest, _ = _collect(artifacts)
    assert not any(a["design"] == "acorn-pcie" for a in manifest["artifacts"])
    assert manifest["build"]["jobs"] == len(vr.matrix.ENTRIES) - 6


def test_the_manifest_has_the_first_release_schema_and_the_run(artifacts):
    manifest, _ = _collect(artifacts)
    assert set(manifest) == {"schema", "generated_at", "git", "tool", "build", "artifacts"}
    assert manifest["schema"] == 1 and manifest["generated_at"] == NOW
    assert manifest["git"] == {"describe": "v0.0-900-ge568a40", "sha": COMMIT, "branch": "main", "dirty": False}
    assert manifest["tool"] == {
        "vivado_version": "2025.2",
        "settings_path": "/opt/Xilinx/2025.2/Vivado/settings64.sh",
    }
    assert manifest["build"]["flows"] == ["vivado-vivado"] and manifest["build"]["run_id"] == 4242
    first = manifest["artifacts"][0]
    assert set(first) == {"filename", "design", "board", "variant", "flow", "size_bytes", "sha256"}
    by_name = {a["filename"]: a for a in manifest["artifacts"]}
    assert by_name["uart_acorn-cle-215p_vivado-vivado_sqrl_acorn.bit"]["variant"] == "cle-215p"


def test_sha256sums_covers_every_bitstream_and_matches_the_staged_files(artifacts, tmp_path):
    manifest, staged = _collect(artifacts)
    out = tmp_path / "vivado-release"
    paths = vr.stage(manifest, staged, out)
    assert [p.name for p in paths[-2:]] == ["manifest.json", "SHA256SUMS"]
    lines = (out / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == len(staged)
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert json.loads((out / "manifest.json").read_text()) == manifest


def test_a_missing_artifact_stops_the_release(artifacts):
    shutil.rmtree(artifacts / "vivado-ddr-memory-netv2-a7-35")
    with pytest.raises(vr.ReleaseError, match="no artifact for ddr-memory-netv2-a7-35"):
        _collect(artifacts)


def test_an_artifact_built_from_another_commit_stops_the_release(artifacts):
    with pytest.raises(vr.ReleaseError, match="was built from e568a408e7bd, not ffffffffffff"):
        _collect(artifacts, commit="f" * 40)


def test_a_file_changed_after_the_build_stops_the_release(artifacts):
    (artifacts / "vivado-uart-arty-a7-35" / "gateware" / "digilent_arty.bit").write_bytes(b"tampered")
    with pytest.raises(vr.ReleaseError, match="not the file that was built"):
        _collect(artifacts)


def test_an_artifact_from_another_vivado_stops_the_release(artifacts):
    info = artifacts / "vivado-uart-arty-a7-35" / "build-info.json"
    info.write_text(json.dumps({**json.loads(info.read_text()), "vivado_version": "2024.1"}))
    with pytest.raises(vr.ReleaseError, match=r"built with Vivado 2024\.1"):
        _collect(artifacts)


def test_staging_refuses_a_directory_that_already_holds_files(artifacts, tmp_path):
    manifest, staged = _collect(artifacts)
    out = tmp_path / "vivado-release"
    out.mkdir()
    (out / "notes.txt").write_text("mine")
    with pytest.raises(vr.ReleaseError, match="is not empty"):
        vr.stage(manifest, staged, out)


def test_the_notes_name_the_run_and_count_each_board(artifacts):
    notes = vr.release_notes(_collect(artifacts)[0])
    assert "[4242](https://github.com/fpgas-online/fpgas.online-test-designs/actions/runs/4242)" in notes
    assert "| uart | netv2 | a7-100 | 1 |" in notes


def test_the_acorn_pcie_artifacts_become_the_tree_publish_release_reads(artifacts, tmp_path):
    tree = tmp_path / "acorn-pcie-ci-build"
    made = vr.acorn_pcie_tree(artifacts, COMMIT, tree)
    assert sorted(d.name for d in made) == [
        "acorn-cle-101",
        "acorn-cle-101-golden",
        "acorn-cle-215",
        "acorn-cle-215+",
        "acorn-cle-215+-golden",
        "acorn-cle-215-golden",
    ]
    golden = tree / "acorn-cle-215+-golden"
    assert (golden / "csr.json").is_file() and (golden / "gateware" / "sqrl_acorn_fallback.bin").is_file()
    assert not (golden / "build-info.json").exists()


def test_the_acorn_pcie_tree_needs_every_variant(artifacts, tmp_path):
    shutil.rmtree(artifacts / "vivado-acorn-pcie-acorn-cle-101-golden")
    with pytest.raises(vr.ReleaseError, match="no artifact for acorn-pcie-acorn-cle-101-golden"):
        vr.acorn_pcie_tree(artifacts, COMMIT, tmp_path / "tree")


def _api(runs):
    def api(path):
        assert path.startswith("repos/o/r/actions/workflows/build-vivado.yml/runs?head_sha=" + COMMIT)
        return {"workflow_runs": runs}

    return api


def test_the_run_is_the_newest_successful_one_of_that_commit():
    older = {**RUN, "id": 1, "created_at": "2026-10-01T00:00:00Z"}
    newer = {**RUN, "id": 2, "created_at": "2026-10-02T00:00:00Z", "event": "workflow_dispatch"}
    assert vr.find_run("o/r", COMMIT, api=_api([older, newer]))["id"] == 2


def test_a_pull_request_run_or_another_commit_is_not_a_release_build():
    pull = {**RUN, "id": 3, "event": "pull_request"}
    other = {**RUN, "id": 4, "head_sha": "f" * 40}
    failed = {**RUN, "id": 5, "conclusion": "failure"}
    with pytest.raises(vr.ReleaseError, match=r"no successful build-vivado\.yml run of e568a408e7bd"):
        vr.find_run("o/r", COMMIT, api=_api([pull, other, failed]))
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_release.py -q`
Expected: an error during collection, `FileNotFoundError: ... scripts/vivado_release.py`.

- [ ] **Step 3: Write the script**

Create `scripts/vivado_release.py`:

```python
#!/usr/bin/env python3
"""Make a Vivado bitstream release from what CI built: nothing is built here, and nothing here runs Vivado.

The "Build: Vivado" workflow builds every entry of scripts/vivado_matrix.py on the sandboxed runners, which
hold no token that can write to the repository. This runs afterwards on a GitHub-hosted runner: it finds
that workflow's successful run of a commit, downloads its `vivado-<id>` artifacts, checks each against its
build-info.json (the commit it was built from, the Vivado version, every file's sha256), and stages one of:

  --kind all-designs   every test design's bitstreams, as `vivado-bitstreams-<git describe>`, with the
                       manifest.json and SHA256SUMS of the 2026-04 release (vivado-bitstreams-v0.0-496-gf162f60):
                       files are `<design>_<board>-<variant>_vivado-vivado_<file>`
  --kind acorn-pcie    the Acorn PCIe SoC images: the artifacts are laid out as the build tree
                       designs/acorn-pcie/tools/publish_release.py reads, and that script does the rest

A release is all or nothing: an entry with no artifact, or one built from another commit, stops it.

    uv run --no-project python scripts/vivado_release.py --commit HEAD --kind all-designs   # stage only
    ... --publish true                                                                      # and create it
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = "build-vivado.yml"
TAG_PREFIX = "vivado-bitstreams"
SCHEMA = 1
ACORN_PCIE = "acorn-pcie"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its module up there
    spec.loader.exec_module(module)
    return module


matrix = _load("vivado_matrix", REPO / "scripts" / "vivado_matrix.py")
publish_release = _load("publish_release", REPO / "designs" / "acorn-pcie" / "tools" / "publish_release.py")


class ReleaseError(Exception):
    pass


def _run(argv, cwd=REPO):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise ReleaseError(f"{' '.join(argv)}: {result.stderr.strip()}")
    return result.stdout.strip()


def gh_json(path):
    return json.loads(_run(["gh", "api", path]))


def find_run(repo, commit, api=gh_json):
    """The newest successful "Build: Vivado" run of exactly `commit` that a pull request did not start."""
    data = api(f"repos/{repo}/actions/workflows/{BUILD_WORKFLOW}/runs?head_sha={commit}&status=success&per_page=100")
    runs = [
        r
        for r in data["workflow_runs"]
        if r["head_sha"] == commit and r["conclusion"] == "success" and r["event"] != "pull_request"
    ]
    if not runs:
        raise ReleaseError(
            f"no successful {BUILD_WORKFLOW} run of {commit[:12]} (pushes to main and manual runs count; "
            "a pull request's run builds the merge commit, not this one)"
        )
    return max(runs, key=lambda r: r["created_at"])


def asset_name(entry, path):
    """`<design>_<board>-<variant>_<flow>_<file>`, as release vivado-bitstreams-v0.0-496-gf162f60 named its files."""
    return f"{entry.design}_{entry.board}-{entry.slug}_{matrix.FLOW}_{pathlib.PurePosixPath(path).name}"


def read_artifact(artifacts, entry, commit):
    """One entry's downloaded artifact, checked against its build-info.json. Returns [(recorded file, path)]."""
    root = pathlib.Path(artifacts) / f"vivado-{entry.id}"
    info_path = root / "build-info.json"
    if not info_path.is_file():
        raise ReleaseError(f"no artifact for {entry.id}: {info_path} is missing")
    info = json.loads(info_path.read_text())
    if info["id"] != entry.id:
        raise ReleaseError(f"{info_path} is for {info['id']}, not {entry.id}")
    if info["source_commit"] != commit:
        raise ReleaseError(f"{entry.id} was built from {info['source_commit'][:12]}, not {commit[:12]}")
    if info["vivado_version"] != matrix.VIVADO_VERSION:
        raise ReleaseError(f"{entry.id} was built with Vivado {info['vivado_version']}, not {matrix.VIVADO_VERSION}")
    files = []
    for recorded in info["files"]:
        path = root / recorded["path"]
        if not path.is_file():
            raise ReleaseError(f"{entry.id}: {recorded['path']} is in build-info.json but not in the artifact")
        if hashlib.sha256(path.read_bytes()).hexdigest() != recorded["sha256"]:
            raise ReleaseError(f"{entry.id}: {recorded['path']} is not the file that was built (sha256 differs)")
        files.append((recorded, path))
    return files


def collect(artifacts, commit, describe, run, generated_at, entries=None):
    """Check every test design's artifact and describe the release. Returns (manifest, {file name: path})."""
    entries = [e for e in (matrix.ENTRIES if entries is None else entries) if e.design != ACORN_PCIE]
    if not entries:
        raise ReleaseError("the matrix has no test-design entries")
    listed, staged = [], {}
    for entry in entries:
        for recorded, path in read_artifact(artifacts, entry, commit):
            name = asset_name(entry, recorded["path"])
            if name in staged:
                raise ReleaseError(f"two files would be published as {name}")
            staged[name] = path
            listed.append(
                {
                    "filename": name,
                    "design": entry.design,
                    "board": entry.board,
                    "variant": entry.slug,
                    "flow": matrix.FLOW,
                    "size_bytes": recorded["size_bytes"],
                    "sha256": recorded["sha256"],
                }
            )
    manifest = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "git": {"describe": describe, "sha": commit, "branch": run["head_branch"], "dirty": False},
        "tool": {"vivado_version": matrix.VIVADO_VERSION, "settings_path": matrix.VIVADO_SETTINGS},
        "build": {
            "flows": [matrix.FLOW],
            "make_targets": [],
            "jobs": len(entries),
            "run_id": run["id"],
            "run_url": run["html_url"],
        },
        "artifacts": sorted(listed, key=lambda a: a["filename"]),
    }
    return manifest, staged


def stage(manifest, staged, out):
    """Copy the release's files to `out`, which must not hold anything yet. Returns the paths to upload."""
    out = pathlib.Path(out)
    if out.exists() and any(out.iterdir()):
        raise ReleaseError(f"{out} is not empty: remove it, or stage somewhere else with --out")
    out.mkdir(parents=True, exist_ok=True)
    for name, src in staged.items():
        shutil.copyfile(src, out / name)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    sums = "".join(f"{a['sha256']}  {a['filename']}\n" for a in manifest["artifacts"])
    (out / "SHA256SUMS").write_text(sums)
    return [out / name for name in sorted(staged)] + [out / "manifest.json", out / "SHA256SUMS"]


def release_notes(manifest):
    git, build = manifest["git"], manifest["build"]
    lines = [
        f"Vivado-built bitstreams of every Xilinx test design, from `{git['sha'][:12]}` (`{git['describe']}`).",
        "",
        f"Built with Vivado {manifest['tool']['vivado_version']} by GitHub Actions run "
        f"[{build['run_id']}]({build['run_url']}) on the sandboxed Vivado runners; this release was put together "
        "from that run's artifacts, each checked against the commit and sha256 its build recorded.",
        "",
        "Files are `<design>_<board>-<variant>_vivado-vivado_<file>`. `manifest.json` lists each one's design, "
        "board, variant, size and sha256; `sha256sum -c SHA256SUMS` checks a download.",
        "",
        "| design | board | variant | files |",
        "|---|---|---|---|",
    ]
    groups = {}
    for a in manifest["artifacts"]:
        groups.setdefault((a["design"], a["board"], a["variant"]), []).append(a["filename"])
    for (design, board, variant), names in sorted(groups.items()):
        lines.append(f"| {design} | {board} | {variant} | {len(names)} |")
    return "\n".join(lines) + "\n"


def acorn_pcie_tree(artifacts, commit, tree, entries=None):
    """Lay the Acorn PCIe artifacts out as publish_release.py's build tree. Returns the variant directories made."""
    entries = [e for e in (matrix.ENTRIES if entries is None else entries) if e.design == ACORN_PCIE]
    if not entries:
        raise ReleaseError("the matrix has no acorn-pcie entries")
    tree = pathlib.Path(tree)
    if tree.exists() and any(tree.iterdir()):
        raise ReleaseError(f"{tree} is not empty: remove it first")
    made = []
    for entry in entries:
        vdir = tree / pathlib.PurePosixPath(entry.build_dir).name
        for recorded, path in read_artifact(artifacts, entry, commit):
            dst = vdir / recorded["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dst)
        made.append(vdir)
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--commit", required=True, help="the commit to release (any revision git understands)")
    parser.add_argument("--kind", required=True, choices=["all-designs", ACORN_PCIE])
    parser.add_argument(
        "--publish",
        choices=["true", "false"],
        default="false",
        help="create the GitHub Release (default: stage only). Text, because that is how a workflow passes a boolean",
    )
    parser.add_argument("--work", type=pathlib.Path, default=REPO / "tmp", help="where artifacts and staging go")
    parser.add_argument("--repo", default="fpgas-online/fpgas.online-test-designs")
    args = parser.parse_args(argv)
    publish = args.publish == "true"

    try:
        commit = _run(["git", "rev-parse", "--verify", f"{args.commit}^{{commit}}"])
        run = find_run(args.repo, commit)
        artifacts = args.work / f"vivado-run-{run['id']}"
        if not artifacts.exists():
            _run(["gh", "run", "download", str(run["id"]), "--repo", args.repo, "--dir", str(artifacts)])
        print(f"{commit[:12]}: built by run {run['id']} ({run['html_url']}), artifacts in {artifacts}")

        if args.kind == ACORN_PCIE:
            tree = args.work / "acorn-pcie-ci-build"
            made = acorn_pcie_tree(artifacts, commit, tree)
            print(f"laid out {len(made)} variant directories in {tree}")
            evidence = (
                f"built by GitHub Actions run {run['id']} ({run['html_url']}) from {commit[:12]}; "
                "each artifact's build-info.json names that commit and its files' sha256, checked at publish time"
            )
            forward = ["--build-dir", str(tree), "--source-commit", commit, "--source-evidence", evidence]
            forward += ["--out", str(args.work / "acorn-pcie-release"), "--repo", args.repo]
            publish_release.main(forward + (["--publish"] if publish else []))
            return

        describe = _run(["git", "describe", "--tags", "--match", "v[0-9]*.[0-9]*", commit])
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        manifest, staged = collect(artifacts, commit, describe, run, now)
        out = args.work / "vivado-release"
        paths = stage(manifest, staged, out)
        notes = args.work / "vivado-release-notes.md"
        notes.write_text(release_notes(manifest))
    except ReleaseError as e:
        sys.exit(f"error: {e}")

    tag = f"{TAG_PREFIX}-{describe}"
    print(f"staged {len(paths)} files in {out} for {tag}")
    if not publish:
        print("stage only: pass --publish true to create the release")
        return
    subprocess.run(
        [
            "gh", "release", "create", tag, *map(str, paths),
            "--repo", args.repo, "--target", commit,
            "--title", f"Vivado-built bitstreams - {describe}", "--notes-file", str(notes),
        ],
        check=True,
    )  # fmt: skip


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Name the third reader in the matrix's docstring**

In `scripts/vivado_matrix.py`, replace

```
One list, with two readers:

  * .github/workflows/build-vivado.yml asks for it as JSON (`--github-output`) and runs one job per entry;
  * scripts/vivado_build.py builds one entry and checks what Vivado left.
```

with

```
One list, with three readers:

  * .github/workflows/build-vivado.yml asks for it as JSON (`--github-output`) and runs one job per entry;
  * scripts/vivado_build.py builds one entry and checks what Vivado left;
  * scripts/vivado_release.py names a release's files from it, and refuses a release with an entry missing.
```

- [ ] **Step 5: Lint and test the new files on every pull request**

In `.github/workflows/build-vivado.yml`, replace

```yaml
env:
  PY: >-
    scripts/vivado_matrix.py scripts/vivado_build.py
    tests/test_vivado_matrix.py tests/test_vivado_build.py
  TESTS: tests/test_vivado_matrix.py tests/test_vivado_build.py
```

with

```yaml
env:
  PY: >-
    scripts/vivado_matrix.py scripts/vivado_build.py scripts/vivado_release.py
    tests/test_vivado_matrix.py tests/test_vivado_build.py tests/test_vivado_release.py
  TESTS: tests/test_vivado_matrix.py tests/test_vivado_build.py tests/test_vivado_release.py
```

(`tests/test_acorn_pcie_publish_release.py` already runs in `Collect Bitstreams`, in `VERIFY_TESTS`.)

- [ ] **Step 6: Run the tests and the linter**

Run: `uv run --no-project --python 3.12 --with pytest pytest tests/test_vivado_matrix.py tests/test_vivado_build.py tests/test_vivado_release.py -q`
Expected: `35 passed`.

Run: `uv run --no-project --with ruff ruff check scripts/vivado_release.py scripts/vivado_matrix.py tests/test_vivado_release.py` and then the same paths with `ruff format --check`
Expected: `All checks passed!` and `3 files already formatted`.

- [ ] **Step 7: Stage both releases from `main`'s real artifacts**

This reads from GitHub and writes only under `tmp/`. It needs `gh auth status` to pass and `main`'s `Build: Vivado` run of `origin/main` to have succeeded (pull request 2's merge).

```bash
git fetch origin
uv run --no-project python scripts/vivado_release.py --commit origin/main --kind all-designs
```

Expected: `<sha12>: built by run <id> (<url>), artifacts in tmp/vivado-run-<id>`, then `staged <N> files in tmp/vivado-release for vivado-bitstreams-v0.0-<n>-g<sha7>` and `stage only: pass --publish true to create the release`.

Run: `sha256sum -c SHA256SUMS` in `tmp/vivado-release`
Expected: every line `OK`.

```bash
uv run --no-project python scripts/vivado_release.py --commit origin/main --kind acorn-pcie
```

Expected: `laid out 6 variant directories in tmp/acorn-pcie-ci-build`, then `publish_release.py`'s own output: `source commit <sha12>: built by GitHub Actions run <id> ...`, `staged 50 files in tmp/acorn-pcie-release for vivado-bitstreams-acorn-pcie-<YYYYMMDD>-g<sha12>`, six flash-layout lines (three boards, slots `0x000000` and `0x400000`), and `dry run: pass --publish to create the release`. This is the check that CI-built images pass `publish_release.py`'s slot, IDCODE and identifier checks.

Leave `tmp/vivado-run-<id>`, `tmp/vivado-release*`, `tmp/acorn-pcie-ci-build` and `tmp/acorn-pcie-release*` in place until Task 9's exit check, then remove them. `tmp/` is ignored, so `git status --short` shows only this task's files.

- [ ] **Step 8: Commit**

```bash
git add scripts/vivado_release.py scripts/vivado_matrix.py tests/test_vivado_release.py .github/workflows/build-vivado.yml
git commit -m "vivado_release: make a release from a Build: Vivado run's artifacts" -m "All or nothing: every matrix entry's artifact must be there, built from the commit being released, with every file's sha256 as its build recorded. The all-designs release keeps the 2026-04 release's file names, manifest schema and SHA256SUMS; the Acorn PCIe one hands the same artifacts to publish_release.py as its build tree." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
```

### Task 9: the release workflow

**Files:**
- Create: `.github/workflows/release-vivado-bitstreams.yml`
- Modify: `docs/toolchains/github-actions.md` (append to the "Vivado builds" section)

**Interfaces:**
- Consumes: `scripts/vivado_release.py` (Task 8).
- Produces: workflow named `Release: Vivado bitstreams` (already left out of `Collect Bitstreams` by Task 4's `test("Vivado")`). Triggers: a pushed tag matching `v[0-9]+.[0-9]+` publishes the all-designs release; `workflow_dispatch` with inputs `commit` (default: the run's ref), `kind` (`all-designs` or `acorn-pcie`), `publish` (boolean, default off). Artifact `staged-release` always.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/release-vivado-bitstreams.yml`:

```yaml
# .github/workflows/release-vivado-bitstreams.yml
#
# Put a Vivado bitstream release together from what "Build: Vivado" already built for a commit
# (scripts/vivado_release.py). Nothing is built here. This is the only job in the Vivado path with a token
# that can write to the repository, and it runs on a GitHub-hosted runner: the sandboxed Vivado runners
# only ever read.
#
#   a vX.Y tag is pushed   publish `vivado-bitstreams-vX.Y`, every test design's bitstreams at that commit
#   run by hand            stage either release kind for any commit, and publish it only if asked:
#                            all-designs  `vivado-bitstreams-<git describe>`
#                            acorn-pcie   `vivado-bitstreams-acorn-pcie-<date>-g<sha>`, the Acorn PCIe SoC images
#                                         (designs/acorn-pcie/tools/publish_release.py)
#
# What was staged is always uploaded as the `staged-release` artifact, published or not. The commit needs a
# successful "Build: Vivado" run that a push to main or a manual run started; if that run has not finished,
# this fails and says so, and can be re-run when it has.
name: "Release: Vivado bitstreams"

on:
  push:
    tags: ["v[0-9]+.[0-9]+"]
  workflow_dispatch:
    inputs:
      commit:
        description: "Commit to release (default: the ref this run is started on)"
        required: false
        default: ""
      kind:
        description: "Which release"
        type: choice
        options: [all-designs, acorn-pcie]
        default: all-designs
      publish:
        description: "Create the GitHub Release (off: stage only, and upload what was staged)"
        type: boolean
        default: false

concurrency:
  group: ${{ github.workflow }}-${{ inputs.kind || 'all-designs' }}-${{ inputs.commit || github.sha }}
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  release:
    name: "Stage ${{ inputs.kind || 'all-designs' }}"
    runs-on: ubuntu-latest
    permissions:
      contents: write # create the release and its vivado-bitstreams-* tag
      actions: read # find the Build: Vivado run and download its artifacts
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # git describe against the vX.Y tags

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Stage the release, and publish it if asked
        env:
          GH_TOKEN: ${{ github.token }}
          COMMIT: ${{ inputs.commit || github.sha }}
          KIND: ${{ inputs.kind || 'all-designs' }}
          PUBLISH: ${{ github.event_name == 'push' || inputs.publish }}
        run: >-
          uv run --no-project python scripts/vivado_release.py
          --commit "$COMMIT" --kind "$KIND" --publish "$PUBLISH" --repo "$GITHUB_REPOSITORY"

      - name: Upload what was staged
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: staged-release
          path: |
            tmp/vivado-release/
            tmp/vivado-release-notes.md
            tmp/acorn-pcie-release/
            tmp/acorn-pcie-release-notes.md
          if-no-files-found: warn
```

The tag patterns the repository's tag ruleset (13744509) lets anyone create are `vX.Y` and `vivado-bitstreams-*`, so the job's `GITHUB_TOKEN` can create the release's tag.

- [ ] **Step 2: Lint it**

Run: `uvx --from actionlint-py actionlint .github/workflows/release-vivado-bitstreams.yml`
Expected: no output, exit 0.

- [ ] **Step 3: Document it**

In `docs/toolchains/github-actions.md`, at the end of the "Vivado builds (sandboxed self-hosted runners)" section (after its last code block), add:

````markdown
### Releases of the Vivado bitstreams

The runners never hold a token that can write. Releases are put together afterwards, on a GitHub-hosted
runner, by `Release: Vivado bitstreams` (`.github/workflows/release-vivado-bitstreams.yml`) from the
artifacts of a commit's successful `Build: Vivado` run. Nothing is rebuilt, and a release is all or nothing:
every matrix entry's artifact must be there, built from that commit, with each file's sha256 as recorded
when it was built.

| Release | Made when | Tag |
|---|---|---|
| Every test design's bitstreams | a `vX.Y` tag is pushed, or by hand | `vivado-bitstreams-<git describe>` |
| The Acorn PCIe SoC images (`publish_release.py`) | by hand only | `vivado-bitstreams-acorn-pcie-<YYYYMMDD>-g<sha12>` |

By hand, in the Actions tab or with:

```bash
gh workflow run release-vivado-bitstreams.yml -f kind=acorn-pcie -f commit=<sha> -f publish=false
```

With `publish=false` (the default) the run only stages the release and uploads it as the `staged-release`
artifact, to look at before publishing. The commit must have a successful `Build: Vivado` run started by a
push to `main` or by hand; a pull request's run builds the merge commit and does not count.

The same staging works on any machine with `gh` logged in:

```bash
uv run --no-project python scripts/vivado_release.py --commit origin/main --kind all-designs
```

The Acorn fleet's images are pinned in `packaging/acorn-pcie/release.toml`. Publishing an Acorn PCIe
release does not change that pin.
````

- [ ] **Step 4: Commit, push, open the pull request**

```bash
git add .github/workflows/release-vivado-bitstreams.yml docs/toolchains/github-actions.md
git commit -m "ci: publish the Vivado releases from CI, on a GitHub-hosted runner" -m "The one job in the Vivado path with contents: write. It builds nothing: it checks and assembles what Build: Vivado already built for the commit. A vX.Y tag publishes the all-designs release; everything else is by hand and stages only unless asked to publish." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y"
git push -u origin ci/vivado-release
gh pr create --base main --head ci/vivado-release --title "ci: publish the Vivado releases from CI" --body-file tmp/pr3-body.md
```

Write `tmp/pr3-body.md` first, with this text; paste Task 8 Step 7's output where marked:

```markdown
Publishes the Vivado releases from CI. The sandboxed runners never hold a token that can write: this adds
a workflow on a GitHub-hosted runner that puts a release together from the artifacts `Build: Vivado`
already made for a commit. Nothing is rebuilt. Last of three pull requests of
`docs/superpowers/plans/2026-10-02-vivado-runners-3-test-designs-ci.md`.

- `scripts/vivado_release.py`: finds the commit's successful `Build: Vivado` run, downloads its artifacts,
  checks each against its `build-info.json` (commit, Vivado version, every file's sha256), and stages
  either the all-designs release or the Acorn PCIe build tree. All or nothing.
- `designs/acorn-pcie/tools/publish_release.py`: `--source-evidence`, for a build tree made from CI
  artifacts, which has no git worktree to check.
- `.github/workflows/release-vivado-bitstreams.yml`: a `vX.Y` tag publishes the all-designs release; by hand
  it stages either kind, and publishes only when asked.

The all-designs release keeps the file names, `manifest.json` schema and `SHA256SUMS` format of
`vivado-bitstreams-v0.0-496-gf162f60`, which `scripts/publish_vivado_bitstreams.py` on #14 made.

## Checked before the merge

Both releases staged on a workstation from `main`'s real artifacts (nothing published):

    <output of the two commands of Task 8 Step 7>

## To check after the merge

The workflow can only be run by hand once it is on `main`: stage both kinds with `publish=false` and look at
the `staged-release` artifact. Creating a release with the job's token is not exercised until the first
real publish.

## For Tim

- Who publishes the first CI-made releases, and when.
- The Acorn PCIe release policy: `publish_release.py` says a release is made from the build tree that was
  flashed. A CI release is published first and flashed afterwards.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
```

**Exit check for pull request 3, before the merge.**

1. This commit's `Build: Vivado` run: the `Vivado CI scripts: lint and unit tests` job passed (it now runs `tests/test_vivado_release.py`), and all `Vivado:` jobs passed.
2. Task 8 Step 7's two stagings succeeded against `main`'s real artifacts, and their output is in the pull request.

A workflow can only be started by hand once its file is on the default branch, so the workflow itself is exercised after the merge:

**Exit check after the merge. Nothing is published in it.**

1. Wait for `main`'s `Build: Vivado` run of the merge commit to succeed (find it by `headSha`).
2. `gh workflow run release-vivado-bitstreams.yml -f kind=all-designs -f publish=false`, then find the run by `gh run list --workflow release-vivado-bitstreams.yml --json databaseId,headSha,status,conclusion,createdAt --limit 5` and wait for `success`.
3. `gh run download <id> --name staged-release --dir tmp/staged-all`: it holds `vivado-release/` with `manifest.json`, `SHA256SUMS` and the bitstreams; `sha256sum -c SHA256SUMS` there says `OK` for every line; `manifest.json`'s `git.sha` is the merge commit and `build.run_id` is the run from step 1.
4. The same with `-f kind=acorn-pcie`: `staged-release` holds `acorn-pcie-release/` with 50 files, and `manifest.json`'s `source_commit_evidence` names the run.
5. `gh release list --limit 5` shows no new release: staging published nothing.
6. Remove `tmp/staged-all`, `tmp/staged-acorn` and Task 8's `tmp/` directories.

What this exercises: the release workflow end to end short of `gh release create`. What it does not: creating a release and its tag with the job's token. The first real publish (decision CI-1) is that test; if `gh release create` is refused, the tag ruleset or the token's permissions are the place to look, and nothing will have been half-published, because the release is created in one call.

---

## Open decisions for Tim

Per the project's rule these go through `AskUserQuestion` when they come up, not as a list in chat. They are recorded here so the plan is complete. They are numbered CI-1 to CI-6 so they cannot be confused with the spec's D-1 to D-3.

- **CI-1: who publishes the first CI-made releases, and when.** The plan stops at staging. Recommended: Tim (or the session, on his word) runs the workflow with `publish=true` once the staged release has been looked at.
- **CI-2: the Acorn PCIe release policy.** `publish_release.py`'s docstring says a release "is made from the build tree that was actually flashed, not from a fresh build", because the images carry a build timestamp and a rebuild never reproduces them. A CI-made release reverses the order: it is published first and flashed afterwards, so what is on the fleet is still exactly what is in the release, but nothing has run on a board at publish time. Recommended: accept that for CI releases, and keep the fleet's pin (`packaging/acorn-pcie/release.toml`) as the statement of what was tested on hardware.
- **CI-3: pull request #14 (`vivado-xilinx-flows`).** It has its own Vivado work: three flows per design (`vivado-vivado`, `yosys-vivado`, `yosys-nextpnr`), per-flow build directories, `scripts/publish_vivado_bitstreams.py` (builds and publishes locally), `docs/toolchains/vivado.md`, and the `pcie-enumeration` fix. It is 266 commits behind `main`. This plan does not depend on it. Recommended: keep this plan independent; afterwards rebase #14 down to what is still wanted (the `pcie-enumeration` Vivado fix, then that design's rows in the matrix) and drop its publish script in favour of `scripts/vivado_release.py`.
- **CI-4: the Arty A7-100T.** The 2026-04 release had it; no openXC7 job builds it and this matrix leaves it out. Adding it is one string in `VARIANTS` and one entry in `PARTS` (`7a100tcsg324`, not yet read from a real file).
- **CI-5: the full matrix on every pull request push.** 39 jobs. Measured on desktop.buddy (12 threads): the UART SoC 3.5 minutes, the Acorn PCIe SoC 8.5 minutes (golden 5.5), a bare PMOD design about 1.5; peak memory 2.8 to 3.3 GB. That is roughly 2.5 hours of build time in all, so of the order of 40 minutes per push on 4 slots, plus VM boot and `uv sync` per job. Pull request 2's exit check measures it. If it is too slow, the cheap options are a second matrix output for pull requests (one variant per board) or path filters.
- **CI-6: Vivado timing.** The openXC7 and iCE40 builds now fail when timing is missed (`require_timing`); under Vivado LiteX reports timing and does not fail. The measured UART build met timing. Failing a Vivado job on `sqrl_acorn_timing.rpt` is a small addition to `vivado_build.py`, left out here because it could turn builds red that were shipped as they are.

## Self-review

- **Spec coverage.** "Vivado jobs beside the openXC7 ones" → Tasks 2 to 5 (as one workflow: departure 1). Runner labels, the fork guard, `contents: read`, `timeout-minutes: 90` → Task 4's workflow. The `Vivado:` prefix and the bundle's independence → Task 4 Steps 2 and 3, test `test_job_names_cannot_match_the_bundle_job_patterns`. The `.bit` header must say 2025.2 → Task 3 `check_bit`. "Releases ... on `ubuntu-latest` ... `contents: write` ... `publish_release.py`" → Tasks 7 to 9. "The all-designs release ... Phase 5 adds one" → Task 8 (see departure 3). Documentation → Tasks 6 and 9. Rollout Phase 3 exit check "full Vivado matrix green" → pull request 2; Phase 5 "a `vivado-bitstreams-*` release made by CI with matching SHA-256s" → staged and verified by pull request 3, published under CI-1. Not in this plan, by scope: the sandbox acceptance workflow (Plan 2).
- **Placeholders.** None in the code: every code step has its code, every command its expected output. The `...` in the pull request bodies' "Checked" lists and the `<id>`, `<sha>` in commands are values a run produces (run ids, commit shas, durations), to be filled in from the exit checks.
- **Type consistency.** `Entry.id`, `.slug`, `.name`, `.part`, `.command()`, `.keep`, `.required`, `.build_dir`, `.bit` are defined in Task 2 and used with those names in Tasks 3, 5 and 8. `build-info.json`'s keys (`id`, `source_commit`, `vivado_version`, `files[].path|size_bytes|sha256`) are written in Task 3 and read in Task 8. The artifact name `vivado-<id>` is set in Task 4 and read as `vivado-{entry.id}` in Task 8. The workflow file name `build-vivado.yml` is `BUILD_WORKFLOW` in Task 8. `--source-evidence` is added in Task 7 and passed in Task 8.
