# Vivado Runners 1: Runner Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `fpgas-online/fpgas.online-vivado-runners`: the controller that runs one throwaway KVM VM per GitHub Actions job, the scripts that build the VM image and the Vivado disk, the host proxy and firewall configuration, and a Debian package of all of it.

**Architecture:** A Python service keeps a fixed number of slots. Each slot asks GitHub for a single-job (JIT) runner config, boots a transient libvirt VM from a copy-on-write overlay, waits for it to power off, and deletes everything. GitHub and libvirt sit behind small interfaces so the slot logic is tested with fakes. Host-side network policy (libvirt network, nftables table, squid allowlist) ships as static files in the package.

**Tech Stack:** Python 3.13 (Debian 13), stdlib + PyJWT/cryptography, `virsh`, `qemu-img`, `xorriso`, `virt-install`, squid, nftables, pytest, ruff, uv, debhelper/pybuild, `mithro/apt-repo-action`.

**Spec:** `docs/superpowers/specs/2026-09-25-vivado-runners-design.md` (moves into the new repo in Task 1).

**This is plan 1 of 3.** Plan 2 deploys this to big-storage and proves the sandbox. Plan 3 adds the Vivado jobs to test-designs.

## Global Constraints

- Repository: `fpgas-online/fpgas.online-vivado-runners`, Apache-2.0, default branch `main`.
- Python package `vivado_runners`, console script `vivado-runners`, Debian package `vivado-runners`, system user `vivado-runners`.
- Target OS: Debian 13 (trixie) only. Python floor 3.11 (`tomllib`).
- Runtime Python dependencies: stdlib, `PyJWT`, `cryptography`. Nothing else.
- All Python commands run through `uv` (`uv run pytest`, `uv run ruff`). Never plain `python` or `pip`.
- No shell with loops, conditionals or more than two commands: write Python.
- Dates are ISO 8601 (`2026-10-02`). Never month-first.
- Never write to `/tmp`; never redirect stderr to `/dev/null`; never `ssh-keyscan -H`.
- Runner subnet is `192.168.76.0/24`, bridge `vrbr0`, libvirt network `vivado-runners`, host/proxy address `192.168.76.1:3128`. Slot `i` (0-based, at most 8 slots) has MAC `52:54:00:76:00:<i as 2 hex digits>` and IP `192.168.76.<10+i>`.
- VM domain name `vr-<host>-<i>`. Runner name `<host>-slot<i>-<8 hex>`.
- Runner labels: `self-hosted`, `linux`, `x64`, `vivado-2025.2`. Runner group: `vivado`.
- State directory `/var/lib/vivado-runners`; images in `/var/lib/vivado-runners/images`; config in `/etc/vivado-runners/config.toml`; GitHub App key `/etc/vivado-runners/app.pem`.
- Image names: `runner-base-<YYYY-MM-DD>.<n>.qcow2`, `vivado-<version>-<YYYY-MM-DD>.squashfs`; symlinks `runner-base-current`, `vivado-current`. Nothing deletes an image automatically.
- No credential other than the JIT config ever enters a VM. The host never mounts or parses a disk a job VM has written to.
- Nothing containing Vivado is ever uploaded anywhere (AMD's EULA forbids redistribution).
- One PR per task group (listed under "Pull requests"); CI green before the next; merge with `gh pr merge --merge`, never squash.
- Every commit message ends with these two lines:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
  ```

## Differences from the spec (apply to the spec in Task 1)

1. **No `_diag` copy.** The spec has the controller loop-mount the scratch disk to read the runner's diagnostic log. That makes the host parse a filesystem a hostile job controls. The controller logs the runner name instead; GitHub's jobs API reports the same name as `runner_name`, which ties a log line to a run.
2. **Threads, not asyncio.** Every hypervisor call is a blocking subprocess, so each slot is a thread.
3. **Seed is a read-only virtio disk holding an ISO 9660 image**, found in the guest by its serial (`vr-seed`).
4. **`--disableupdate` is a `config.sh` flag and JIT runners never run `config.sh`.** Whether a JIT runner self-updates is checked in Plan 2 by decoding a JIT config. Either way GitHub stops sending jobs to a runner more than 30 days behind the latest release, so the base image is rebuilt at least monthly (Plan 2 adds the reminder).
5. **Phase 1's exit check "image boots under the controller locally" moves to Plan 2.** desktop.buddy has no libvirt; the first boot happens on big-storage.
6. **Packages publish through `mithro/apt-repo-action`** (signed apt repo on GitHub Pages), as nfsroot-watchdog does, not through a `debs` release.

## File Structure

```
pyproject.toml                    package metadata, ruff + pytest config
src/vivado_runners/
  __init__.py
  config.py                       TOML -> frozen dataclasses; slot MAC/IP/name rules
  images.py                       versioned images and the *-current symlinks
  github.py                       GitHub App auth; JIT config; list/delete runners
  domain_xml.py                   libvirt domain XML for one slot
  hypervisor.py                   virsh / qemu-img / xorriso behind one class
  slot.py                         one slot's lifecycle and failure policy
  controller.py                   startup cleanup; threads; signals
  cli.py                          vivado-runners run | status | cleanup | images
tests/
  test_config.py test_images.py test_github.py test_domain_xml.py
  test_hypervisor.py test_slot.py test_controller.py test_cli.py
  fakes.py                        FakeGitHub, FakeHypervisor, FakeClock
host/
  network.xml                     libvirt network `vivado-runners`
  vivado-runners.nft              nftables table inet vivado_runners
  squid.conf                      dedicated squid instance
  allowed-hosts                   GitHub hostnames (squid dstdomain)
  allowed-blob-regex              GitHub's Azure blob accounts (squid dstdom_regex)
image/
  versions.toml                   pinned runner, uv, Python versions and checksums
  build_image.py                  host: build runner-base-<date>.<n>.qcow2
  provision.py                    guest, at build time: install everything
  guest/vivado-runner-boot        guest, every boot: mount, run one job
  guest/vivado-runner.service
  build_vivado_disk.py            host: squashfs of /opt/Xilinx/<version>
tools/
  allowlist_proxy.py              logging CONNECT proxy for experiments
debian/                           control, rules, install, units, postinst
.github/workflows/ci.yml          lint, tests, config syntax checks
.github/workflows/deb.yml         build + publish the package
.github/apt-packaging.toml
docs/measurements.md              Phase 0 numbers
docs/superpowers/{specs,plans}/   moved from test-designs
README.md  LICENSE  .gitignore
```

## Pull requests

| PR | Tasks | Exit check |
|---|---|---|
| A | 1 | CI workflow runs and is green on an empty test suite |
| B | 2-9 | `uv run pytest` green; `vivado-runners --help` works |
| C | 10 | `squid -k parse`, `nft -c`, `virt-xml-validate` green in CI |
| D | 11-12 | unit tests green; scripts not yet run against a hypervisor (said so in the PR) |
| E | 13 | deb builds and installs in a clean `debian:trixie` container |
| F | 14 | `docs/measurements.md` holds measured numbers; config defaults updated |

---

### Task 1: Repository, skeleton and CI

**Files:**
- Create: `pyproject.toml`, `src/vivado_runners/__init__.py`, `tests/test_smoke.py`, `.gitignore`, `LICENSE`, `README.md`, `.github/workflows/ci.yml`
- Create: `docs/superpowers/specs/2026-09-25-vivado-runners-design.md` and the three plans (copied from test-designs PR #93)

**Interfaces:**
- Produces: importable package `vivado_runners` with `__version__: str`.

- [ ] **Step 1: Ask Tim before creating the repository**

Creating a public repo is outward-facing. Ask: "Create `fpgas-online/fpgas.online-vivado-runners` (public, Apache-2.0) now?" Proceed only on yes.

- [ ] **Step 2: Create and configure the repository**

Invoke the `github-repo-setup:github-setup` skill and apply its checklist to:

```bash
gh repo create fpgas-online/fpgas.online-vivado-runners --public --license apache-2.0 \
  --description "Sandboxed per-job KVM GitHub Actions runners with Vivado, for fpgas.online"
gh repo clone fpgas-online/fpgas.online-vivado-runners ~/github/fpgas-online/fpgas.online-vivado-runners
```

Branch protection and LFS-in-archives need Tim (the skill cannot set them). Say so when reporting.

- [ ] **Step 3: Create a worktree for PR A**

Use the `superpowers:using-git-worktrees` skill; branch `skeleton`, path `.worktrees/skeleton`. Add `.worktrees/` to `.gitignore` in the first commit.

- [ ] **Step 4: Write the package skeleton**

`pyproject.toml`:

```toml
[project]
name = "vivado-runners"
version = "0.1.0"
description = "Sandboxed per-job KVM GitHub Actions runners with Vivado"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = ["PyJWT>=2.6", "cryptography>=41"]

[project.scripts]
vivado-runners = "vivado_runners.cli:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vivado_runners"]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`src/vivado_runners/__init__.py`:

```python
"""Sandboxed per-job KVM GitHub Actions runners with Vivado."""

__version__ = "0.1.0"
```

`tests/test_smoke.py`:

```python
import vivado_runners


def test_version_is_a_string():
    assert isinstance(vivado_runners.__version__, str)
```

`.gitignore`:

```
.worktrees/
.venv/
__pycache__/
*.egg-info/
dist/
built-debs/
debian/changelog
tmp/
```

- [ ] **Step 5: Run the test**

Run: `uv run pytest -v`
Expected: `1 passed`. (`pythonpath = ["."]` in the pytest config is what lets later tests import `tests.fakes`.)

- [ ] **Step 6: Add CI**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.event.pull_request.number || github.sha }}
  cancel-in-progress: true

jobs:
  test:
    name: Lint and unit tests
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Lint
        run: uv run ruff check . && uv run ruff format --check .
      - name: Tests
        run: uv run pytest -v
```

- [ ] **Step 7: Copy the spec and plans, and apply the six spec differences**

Copy the spec and the three plan files from test-designs branch `docs/vivado-runners-spec` into `docs/superpowers/specs/` and `docs/superpowers/plans/`. In the spec:

- "Slot loop" step 6: delete the sentence about copying `_diag`; under "Observability" replace "GitHub run/job id (from `_diag`)" with "runner name (GitHub's jobs API reports it as `runner_name`)".
- "Slot loop" intro: "One asyncio task per slot" becomes "One thread per slot".
- "Golden runner image": replace the `--disableupdate` bullet with: "`actions/runner` at a pinned version, started with `--jitconfig`. GitHub stops sending jobs to runners more than 30 days behind the latest release, so the image is rebuilt at least monthly."
- "Rollout" Phase 1 exit check becomes "Unit tests green; package builds"; Phase 2 work gains "first image build and first boot".
- "Repositories and ownership": "through the secretless `debs` Release model used by nfsroot-watchdog" becomes "as a signed apt repository on GitHub Pages via `mithro/apt-repo-action`, as nfsroot-watchdog does".
- D-2 becomes "Decided 2026-10-02: `fpgas-online/fpgas.online-vivado-runners`."

- [ ] **Step 8: Write the README**

`README.md` (complete content):

```markdown
# fpgas.online Vivado runners

Self-hosted GitHub Actions runners that build FPGA bitstreams with AMD Vivado.
Every job runs in a fresh KVM virtual machine that is destroyed afterwards. A
VM can reach GitHub and nothing else.

- Design: [docs/superpowers/specs/2026-09-25-vivado-runners-design.md](docs/superpowers/specs/2026-09-25-vivado-runners-design.md)
- Measured numbers: [docs/measurements.md](docs/measurements.md)

## Layout

| Path | What |
|---|---|
| `src/vivado_runners/` | The controller service and its CLI |
| `host/` | libvirt network, nftables table and squid allowlist |
| `image/` | Scripts that build the VM image and the Vivado disk |
| `tools/` | Helpers for measurements |

## Development

    uv run pytest
    uv run ruff check .

Vivado and any image containing it stay on the runner hosts. Never upload them:
AMD's licence allows installing Vivado, not redistributing it.
```

- [ ] **Step 9: Commit, push, open PR A**

```bash
git add -A
git commit -m "Skeleton: package, CI, design spec and plans"
git push -u origin skeleton
gh pr create --title "Skeleton: package, CI, design spec and plans" --body "Empty package with lint and test CI, plus the design spec and implementation plans moved from fpgas.online-test-designs#93."
```

Expected: the `CI` workflow passes. Then close test-designs PR #93 with a comment linking the new repo (ask Tim first: it is his PR to close).

---

### Task 2: Configuration

**Files:**
- Create: `src/vivado_runners/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load(path: Path) -> Config`; `ConfigError`; `MAX_SLOTS = 8`; `SUBNET = "192.168.76"`.
  `Config` fields: `host: str`, `state_dir: Path`, `min_free_gib: int`, `network: str`, `proxy: str`, `github: GithubConfig`, `slots: SlotsConfig`; properties/methods `images_dir`, `status_dir`, `console_dir`, `runner_prefix`, `slot_dir(i)`, `slot_mac(i)`, `slot_ip(i)`, `domain_name(i)`, `domain_prefix`.
  `GithubConfig`: `org`, `app_id: int`, `installation_id: int`, `key_file: Path`, `runner_group`.
  `SlotsConfig`: `count`, `vcpus`, `memory_gib`, `scratch_gib`, `wall_limit_minutes`, `register_timeout_minutes`, `labels: tuple[str, ...]`, `numa_nodes: tuple[int, ...]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from vivado_runners import config

GOOD = """
host = "big-storage"

[github]
org = "fpgas-online"
app_id = 123
installation_id = 456
key_file = "/etc/vivado-runners/app.pem"
runner_group = "vivado"

[slots]
count = 4
vcpus = 8
memory_gib = 24
scratch_gib = 60
wall_limit_minutes = 120
labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]
numa_nodes = [0, 0, 1, 1]
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_loads_a_complete_file(tmp_path):
    cfg = config.load(write(tmp_path, GOOD))
    assert cfg.host == "big-storage"
    assert cfg.github.app_id == 123
    assert cfg.slots.labels == ("self-hosted", "linux", "x64", "vivado-2025.2")
    assert cfg.slots.numa_nodes == (0, 0, 1, 1)
    assert cfg.slots.register_timeout_minutes == 5
    assert cfg.state_dir == Path("/var/lib/vivado-runners")
    assert cfg.proxy == "http://192.168.76.1:3128"
    assert cfg.network == "vivado-runners"
    assert cfg.min_free_gib == 100


def test_slot_addressing(tmp_path):
    cfg = config.load(write(tmp_path, GOOD))
    assert cfg.slot_mac(0) == "52:54:00:76:00:00"
    assert cfg.slot_mac(3) == "52:54:00:76:00:03"
    assert cfg.slot_ip(3) == "192.168.76.13"
    assert cfg.domain_name(3) == "vr-big-storage-3"
    assert cfg.domain_prefix == "vr-big-storage-"
    assert cfg.runner_prefix == "big-storage-slot"
    assert cfg.slot_dir(3) == Path("/var/lib/vivado-runners/slot-3")
    assert cfg.images_dir == Path("/var/lib/vivado-runners/images")


def test_host_defaults_to_short_hostname(tmp_path, monkeypatch):
    monkeypatch.setattr(config.socket, "gethostname", lambda: "buddy.mithis.com")
    cfg = config.load(write(tmp_path, GOOD.replace('host = "big-storage"\n', "")))
    assert cfg.host == "buddy"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("count = 4", "count = 9", "slots.count must be 1..8"),
        ("count = 4", "count = 0", "slots.count must be 1..8"),
        ("numa_nodes = [0, 0, 1, 1]", "numa_nodes = [0, 1]", "numa_nodes must have one entry per slot"),
        ('labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]', "labels = []", "slots.labels must not be empty"),
        ("app_id = 123", "", "missing github.app_id"),
    ],
)
def test_rejects_bad_values(tmp_path, old, new, message):
    assert old in GOOD
    with pytest.raises(config.ConfigError, match=message):
        config.load(write(tmp_path, GOOD.replace(old, new)))
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `cannot import name 'config'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/config.py`:

```python
"""Controller configuration, loaded from TOML."""

from __future__ import annotations

import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path

SUBNET = "192.168.76"
MAX_SLOTS = 8


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GithubConfig:
    org: str
    app_id: int
    installation_id: int
    key_file: Path
    runner_group: str


@dataclass(frozen=True)
class SlotsConfig:
    count: int
    vcpus: int
    memory_gib: int
    scratch_gib: int
    wall_limit_minutes: int
    labels: tuple[str, ...]
    numa_nodes: tuple[int, ...] = ()
    register_timeout_minutes: int = 5


@dataclass(frozen=True)
class Config:
    host: str
    state_dir: Path
    min_free_gib: int
    network: str
    proxy: str
    github: GithubConfig
    slots: SlotsConfig

    @property
    def images_dir(self) -> Path:
        return self.state_dir / "images"

    @property
    def status_dir(self) -> Path:
        return self.state_dir / "status"

    @property
    def console_dir(self) -> Path:
        return self.state_dir / "console"

    @property
    def runner_prefix(self) -> str:
        return f"{self.host}-slot"

    @property
    def domain_prefix(self) -> str:
        return f"vr-{self.host}-"

    def slot_dir(self, index: int) -> Path:
        return self.state_dir / f"slot-{index}"

    def slot_mac(self, index: int) -> str:
        return f"52:54:00:76:00:{index:02x}"

    def slot_ip(self, index: int) -> str:
        return f"{SUBNET}.{10 + index}"

    def domain_name(self, index: int) -> str:
        return f"{self.domain_prefix}{index}"


def _need(table: dict, section: str, key: str):
    if key not in table:
        raise ConfigError(f"missing {section}.{key}")
    return table[key]


def load(path: Path) -> Config:
    raw = tomllib.loads(Path(path).read_text())
    gh = raw.get("github", {})
    sl = raw.get("slots", {})

    github = GithubConfig(
        org=_need(gh, "github", "org"),
        app_id=int(_need(gh, "github", "app_id")),
        installation_id=int(_need(gh, "github", "installation_id")),
        key_file=Path(_need(gh, "github", "key_file")),
        runner_group=_need(gh, "github", "runner_group"),
    )
    slots = SlotsConfig(
        count=int(_need(sl, "slots", "count")),
        vcpus=int(_need(sl, "slots", "vcpus")),
        memory_gib=int(_need(sl, "slots", "memory_gib")),
        scratch_gib=int(_need(sl, "slots", "scratch_gib")),
        wall_limit_minutes=int(_need(sl, "slots", "wall_limit_minutes")),
        labels=tuple(_need(sl, "slots", "labels")),
        numa_nodes=tuple(sl.get("numa_nodes", ())),
        register_timeout_minutes=int(sl.get("register_timeout_minutes", 5)),
    )
    if not 1 <= slots.count <= MAX_SLOTS:
        raise ConfigError(f"slots.count must be 1..{MAX_SLOTS}")
    if not slots.labels:
        raise ConfigError("slots.labels must not be empty")
    if slots.numa_nodes and len(slots.numa_nodes) != slots.count:
        raise ConfigError("slots.numa_nodes must have one entry per slot")

    return Config(
        host=raw.get("host") or socket.gethostname().split(".")[0],
        state_dir=Path(raw.get("state_dir", "/var/lib/vivado-runners")),
        min_free_gib=int(raw.get("min_free_gib", 100)),
        network=raw.get("network", "vivado-runners"),
        proxy=raw.get("proxy", f"http://{SUBNET}.1:3128"),
        github=github,
        slots=slots,
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/config.py tests/test_config.py
git commit -m "config: TOML loader and the slot addressing rules"
```

---

### Task 3: Versioned images

**Files:**
- Create: `src/vivado_runners/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Produces: `ImageVersions(base: Path, vivado: Path)`; `ImageError`; `resolve(images_dir) -> ImageVersions`; `list_versions(images_dir, kind) -> list[Path]`; `current(images_dir, kind) -> Path | None`; `activate(images_dir, kind, name) -> None`; `next_base_name(images_dir, date: str) -> str`. `kind` is `"base"` or `"vivado"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_images.py`:

```python
import pytest

from vivado_runners import images


def make(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    return tmp_path


def test_resolve_follows_both_symlinks(tmp_path):
    d = make(tmp_path, "runner-base-2026-10-02.1.qcow2", "vivado-2025.2-2026-10-02.squashfs")
    (d / "runner-base-current").symlink_to("runner-base-2026-10-02.1.qcow2")
    (d / "vivado-current").symlink_to("vivado-2025.2-2026-10-02.squashfs")
    v = images.resolve(d)
    assert v.base == d / "runner-base-2026-10-02.1.qcow2"
    assert v.vivado == d / "vivado-2025.2-2026-10-02.squashfs"


def test_resolve_rejects_missing_dangling_and_escaping_links(tmp_path):
    d = make(tmp_path, "vivado-2025.2-2026-10-02.squashfs")
    (d / "vivado-current").symlink_to("vivado-2025.2-2026-10-02.squashfs")
    with pytest.raises(images.ImageError, match="runner-base-current is not a symlink"):
        images.resolve(d)
    (d / "runner-base-current").symlink_to("runner-base-gone.qcow2")
    with pytest.raises(images.ImageError, match="does not exist"):
        images.resolve(d)
    (d / "runner-base-current").unlink()
    outside = tmp_path.parent / "elsewhere.qcow2"
    outside.write_bytes(b"x")
    (d / "runner-base-current").symlink_to(outside)
    with pytest.raises(images.ImageError, match="outside"):
        images.resolve(d)


def test_activate_repoints_atomically_and_rolls_back(tmp_path):
    d = make(tmp_path, "runner-base-2026-09-25.1.qcow2", "runner-base-2026-10-02.1.qcow2")
    images.activate(d, "base", "runner-base-2026-10-02.1.qcow2")
    assert images.current(d, "base") == d / "runner-base-2026-10-02.1.qcow2"
    images.activate(d, "base", "runner-base-2026-09-25.1.qcow2")
    assert images.current(d, "base") == d / "runner-base-2026-09-25.1.qcow2"
    assert sorted(p.name for p in d.iterdir() if p.name.startswith(".")) == []


def test_activate_refuses_unknown_or_wrong_kind(tmp_path):
    d = make(tmp_path, "vivado-2025.2-2026-10-02.squashfs")
    with pytest.raises(images.ImageError, match="no such base image"):
        images.activate(d, "base", "runner-base-2026-01-01.1.qcow2")
    with pytest.raises(images.ImageError, match="no such base image"):
        images.activate(d, "base", "vivado-2025.2-2026-10-02.squashfs")


def test_list_versions_is_sorted_and_skips_the_symlink(tmp_path):
    d = make(tmp_path, "runner-base-2026-10-02.1.qcow2", "runner-base-2026-09-25.1.qcow2")
    (d / "runner-base-current").symlink_to("runner-base-2026-10-02.1.qcow2")
    assert [p.name for p in images.list_versions(d, "base")] == [
        "runner-base-2026-09-25.1.qcow2",
        "runner-base-2026-10-02.1.qcow2",
    ]


def test_current_is_none_without_a_link(tmp_path):
    assert images.current(tmp_path, "base") is None


def test_next_base_name_counts_builds_per_day(tmp_path):
    assert images.next_base_name(tmp_path, "2026-10-02") == "runner-base-2026-10-02.1.qcow2"
    make(tmp_path, "runner-base-2026-10-02.1.qcow2", "runner-base-2026-10-02.2.qcow2")
    assert images.next_base_name(tmp_path, "2026-10-02") == "runner-base-2026-10-02.3.qcow2"
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL, `cannot import name 'images'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/images.py`:

```python
"""Versioned images and the *-current symlinks that select one.

Every image is kept under its version. Rolling back is repointing a symlink at
an earlier version; nothing here ever deletes an image.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

LINKS = {"base": "runner-base-current", "vivado": "vivado-current"}
PATTERNS = {"base": "runner-base-*.qcow2", "vivado": "vivado-*.squashfs"}


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageVersions:
    base: Path
    vivado: Path


def _resolve_one(images_dir: Path, kind: str) -> Path:
    link = images_dir / LINKS[kind]
    if not link.is_symlink():
        raise ImageError(f"{link.name} is not a symlink in {images_dir}")
    target = link.resolve()
    if target.parent != images_dir.resolve():
        raise ImageError(f"{link.name} points outside {images_dir}: {target}")
    if not target.is_file():
        raise ImageError(f"{link.name} points at {target.name}, which does not exist")
    return images_dir / target.name


def resolve(images_dir: Path) -> ImageVersions:
    return ImageVersions(base=_resolve_one(images_dir, "base"), vivado=_resolve_one(images_dir, "vivado"))


def list_versions(images_dir: Path, kind: str) -> list[Path]:
    return sorted(p for p in images_dir.glob(PATTERNS[kind]) if not p.is_symlink())


def current(images_dir: Path, kind: str) -> Path | None:
    try:
        return _resolve_one(images_dir, kind)
    except ImageError:
        return None


def activate(images_dir: Path, kind: str, name: str) -> None:
    if images_dir / name not in list_versions(images_dir, kind):
        raise ImageError(f"no such {kind} image: {name}")
    tmp = images_dir / f".{LINKS[kind]}.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(name)
    os.replace(tmp, images_dir / LINKS[kind])


def next_base_name(images_dir: Path, date: str) -> str:
    pattern = re.compile(rf"^runner-base-{re.escape(date)}\.(\d+)\.qcow2$")
    builds = [int(m.group(1)) for p in images_dir.iterdir() if (m := pattern.match(p.name))]
    return f"runner-base-{date}.{max(builds, default=0) + 1}.qcow2"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_images.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/images.py tests/test_images.py
git commit -m "images: versioned images selected by a current symlink"
```

---

### Task 4: GitHub client

**Files:**
- Create: `src/vivado_runners/github.py`
- Test: `tests/test_github.py`

**Interfaces:**
- Produces:
  - `Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]` (method, url, headers, body) -> (status, body)
  - `GitHubError(status: int, body: str)`
  - `Runner(id: int, name: str, status: str, busy: bool)`
  - `JitRunner(id: int, encoded_jit_config: str)`
  - `GitHubClient(org, app_id, installation_id, key_pem, transport=urllib_transport, now=time.time)` with `runner_group_id(name) -> int`, `create_jit(name, group_id, labels) -> JitRunner`, `list_runners() -> list[Runner]`, `delete_runner(runner_id) -> None`.

API facts (docs.github.com REST "Self-hosted runners", checked 2026-10-02):
`POST /orgs/{org}/actions/runners/generate-jitconfig` takes `name`, `runner_group_id`, `labels` (1-100), optional `work_folder`, and returns 201 with `{"runner": {"id": ...}, "encoded_jit_config": "..."}`. `GET /orgs/{org}/actions/runners` returns 200 `{"total_count", "runners": [{"id","name","status","busy"}]}`. `DELETE /orgs/{org}/actions/runners/{runner_id}` returns 204. Runner groups: `GET /orgs/{org}/actions/runner-groups` returns `{"runner_groups": [{"id","name"}]}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_github.py`:

```python
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from vivado_runners.github import GitHubClient, GitHubError, JitRunner, Runner

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUBLIC_PEM = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


class Recorder:
    """A Transport that answers from a script and records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode() if payload is not None else b""


TOKEN = (201, {"token": "ghs_abc", "expires_at": "2026-10-02T01:00:00Z"})
NOW = 1790900400.0  # 2026-10-02T00:20:00Z


def client(rec, now=NOW):
    return GitHubClient("fpgas-online", 123, 456, KEY_PEM, transport=rec, now=lambda: now)


def test_app_jwt_is_rs256_signed_and_short_lived():
    rec = Recorder(TOKEN, (200, {"total_count": 0, "runners": []}))
    client(rec).list_runners()
    method, url, headers, _ = rec.calls[0]
    assert (method, url) == ("POST", "https://api.github.com/app/installations/456/access_tokens")
    claims = jwt.decode(
        headers["Authorization"].removeprefix("Bearer "),
        PUBLIC_PEM,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {"iat": int(NOW) - 60, "exp": int(NOW) + 540, "iss": "123"}


def test_installation_token_is_reused_until_near_expiry():
    rec = Recorder(TOKEN, (200, {"runners": []}), (200, {"runners": []}))
    c = client(rec)
    c.list_runners()
    c.list_runners()
    assert [u for _, u, _, _ in rec.calls].count("https://api.github.com/app/installations/456/access_tokens") == 1
    assert rec.calls[1][2]["Authorization"] == "Bearer ghs_abc"


def test_installation_token_is_refreshed_five_minutes_before_expiry():
    clock = {"t": NOW}
    rec = Recorder(TOKEN, (200, {"runners": []}), TOKEN, (200, {"runners": []}))
    c = GitHubClient("fpgas-online", 123, 456, KEY_PEM, transport=rec, now=lambda: clock["t"])
    c.list_runners()
    clock["t"] = NOW + 36 * 60  # 00:56, four minutes before expiry
    c.list_runners()
    assert [u for _, u, _, _ in rec.calls].count("https://api.github.com/app/installations/456/access_tokens") == 2


def test_create_jit_posts_the_documented_body():
    rec = Recorder(TOKEN, (201, {"runner": {"id": 23}, "encoded_jit_config": "abc=="}))
    jit = client(rec).create_jit("big-storage-slot0-deadbeef", 7, ["self-hosted", "vivado-2025.2"])
    assert jit == JitRunner(id=23, encoded_jit_config="abc==")
    method, url, _, body = rec.calls[1]
    assert (method, url) == ("POST", "https://api.github.com/orgs/fpgas-online/actions/runners/generate-jitconfig")
    assert json.loads(body) == {
        "name": "big-storage-slot0-deadbeef",
        "runner_group_id": 7,
        "labels": ["self-hosted", "vivado-2025.2"],
    }


def test_runner_group_id_finds_by_name_and_fails_when_absent():
    groups = {"runner_groups": [{"id": 1, "name": "Default"}, {"id": 7, "name": "vivado"}]}
    assert client(Recorder(TOKEN, (200, groups))).runner_group_id("vivado") == 7
    with pytest.raises(GitHubError, match="runner group 'nope' not found"):
        client(Recorder(TOKEN, (200, groups))).runner_group_id("nope")


def test_list_runners_follows_pages():
    page1 = {"runners": [{"id": i, "name": f"r{i}", "status": "online", "busy": False} for i in range(100)]}
    page2 = {"runners": [{"id": 100, "name": "r100", "status": "offline", "busy": True}]}
    rec = Recorder(TOKEN, (200, page1), (200, page2))
    runners = client(rec).list_runners()
    assert len(runners) == 101
    assert runners[-1] == Runner(id=100, name="r100", status="offline", busy=True)
    assert rec.calls[1][1].endswith("/actions/runners?per_page=100&page=1")
    assert rec.calls[2][1].endswith("/actions/runners?per_page=100&page=2")


def test_delete_runner_accepts_204_and_404_and_raises_otherwise():
    client(Recorder(TOKEN, (204, None))).delete_runner(23)
    client(Recorder(TOKEN, (404, {"message": "Not Found"}))).delete_runner(23)
    with pytest.raises(GitHubError) as e:
        client(Recorder(TOKEN, (422, {"message": "busy"}))).delete_runner(23)
    assert e.value.status == 422


def test_errors_carry_status_and_body():
    with pytest.raises(GitHubError) as e:
        client(Recorder((401, {"message": "Bad credentials"}))).list_runners()
    assert e.value.status == 401
    assert "Bad credentials" in str(e.value)
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_github.py -v`
Expected: FAIL, `cannot import name 'GitHubClient'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/github.py`:

```python
"""The four GitHub API calls the controller makes, authenticated as a GitHub App."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import jwt

API = "https://api.github.com"
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class GitHubError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"GitHub API {status}: {body}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Runner:
    id: int
    name: str
    status: str
    busy: bool


@dataclass(frozen=True)
class JitRunner:
    id: int
    encoded_jit_config: str


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class GitHubClient:
    def __init__(
        self,
        org: str,
        app_id: int,
        installation_id: int,
        key_pem: str,
        transport: Transport = urllib_transport,
        now: Callable[[], float] = time.time,
    ):
        self._org = org
        self._app_id = app_id
        self._installation_id = installation_id
        self._key_pem = key_pem
        self._transport = transport
        self._now = now
        self._token: str | None = None
        self._token_expiry = 0.0

    def _headers(self, bearer: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "vivado-runners",
        }

    def _installation_token(self) -> str:
        if self._token and self._now() < self._token_expiry - 300:
            return self._token
        now = int(self._now())
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(self._app_id)}, self._key_pem, algorithm="RS256"
        )
        url = f"{API}/app/installations/{self._installation_id}/access_tokens"
        status, body = self._transport("POST", url, self._headers(app_jwt), b"")
        if status != 201:
            raise GitHubError(status, body.decode(errors="replace"))
        data = json.loads(body)
        self._token = data["token"]
        self._token_expiry = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        return self._token

    def _call(self, method: str, path: str, payload: dict | None = None, ok: tuple[int, ...] = (200,)):
        body = json.dumps(payload).encode() if payload is not None else None
        status, raw = self._transport(method, f"{API}{path}", self._headers(self._installation_token()), body)
        if status not in ok:
            raise GitHubError(status, raw.decode(errors="replace"))
        return json.loads(raw) if raw else None

    def runner_group_id(self, name: str) -> int:
        groups = self._call("GET", f"/orgs/{self._org}/actions/runner-groups?per_page=100")["runner_groups"]
        for group in groups:
            if group["name"] == name:
                return group["id"]
        raise GitHubError(404, f"runner group {name!r} not found in {self._org}")

    def create_jit(self, name: str, group_id: int, labels: list[str]) -> JitRunner:
        data = self._call(
            "POST",
            f"/orgs/{self._org}/actions/runners/generate-jitconfig",
            {"name": name, "runner_group_id": group_id, "labels": labels},
            ok=(201,),
        )
        return JitRunner(id=data["runner"]["id"], encoded_jit_config=data["encoded_jit_config"])

    def list_runners(self) -> list[Runner]:
        runners: list[Runner] = []
        page = 1
        while True:
            batch = self._call("GET", f"/orgs/{self._org}/actions/runners?per_page=100&page={page}")["runners"]
            runners += [Runner(id=r["id"], name=r["name"], status=r["status"], busy=r["busy"]) for r in batch]
            if len(batch) < 100:
                return runners
            page += 1

    def delete_runner(self, runner_id: int) -> None:
        self._call("DELETE", f"/orgs/{self._org}/actions/runners/{runner_id}", ok=(204, 404))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_github.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/github.py tests/test_github.py
git commit -m "github: App auth, JIT runner configs, list and delete runners"
```

---

### Task 5: Domain XML

**Files:**
- Create: `src/vivado_runners/domain_xml.py`
- Test: `tests/test_domain_xml.py`

**Interfaces:**
- Produces: `DomainSpec` (frozen dataclass) with fields `name: str`, `vcpus: int`, `memory_gib: int`, `mac: str`, `ip: str`, `network: str`, `overlay: Path`, `vivado: Path`, `seed: Path`, `scratch: Path`, `console_log: Path`, `cpuset: str | None = None`, `numa_node: int | None = None`; and `render(spec: DomainSpec) -> str`.
- Guest-visible disk serials (the guest boot script in Task 11 relies on them): `vr-vivado`, `vr-seed`, `vr-scratch`.

- [ ] **Step 1: Write the failing tests**

`tests/test_domain_xml.py`:

```python
import xml.etree.ElementTree as ET
from pathlib import Path

from vivado_runners.domain_xml import DomainSpec, render

SPEC = DomainSpec(
    name="vr-big-storage-2",
    vcpus=8,
    memory_gib=24,
    mac="52:54:00:76:00:02",
    ip="192.168.76.12",
    network="vivado-runners",
    overlay=Path("/var/lib/vivado-runners/slot-2/overlay.qcow2"),
    vivado=Path("/var/lib/vivado-runners/images/vivado-2025.2-2026-10-02.squashfs"),
    seed=Path("/var/lib/vivado-runners/slot-2/seed.iso"),
    scratch=Path("/var/lib/vivado-runners/slot-2/scratch.qcow2"),
    console_log=Path("/var/lib/vivado-runners/console/slot-2.log"),
)


def root(spec=SPEC):
    return ET.fromstring(render(spec))


def disks(r):
    return {d.findtext("serial"): d for d in r.findall("devices/disk")}


def test_basics():
    r = root()
    assert r.get("type") == "kvm"
    assert r.findtext("name") == "vr-big-storage-2"
    assert (r.find("memory").get("unit"), r.findtext("memory")) == ("GiB", "24")
    assert r.findtext("vcpu") == "8"
    assert r.find("vcpu").get("cpuset") is None
    assert r.find("numatune") is None


def test_every_guest_exit_destroys_the_domain():
    r = root()
    assert [r.findtext(t) for t in ("on_poweroff", "on_reboot", "on_crash")] == ["destroy"] * 3


def test_disks_have_serials_and_read_only_where_required():
    d = disks(root())
    assert set(d) == {None, "vr-vivado", "vr-seed", "vr-scratch"}
    overlay = d[None]
    assert overlay.find("source").get("file").endswith("slot-2/overlay.qcow2")
    assert overlay.find("driver").get("type") == "qcow2"
    assert overlay.find("readonly") is None
    assert d["vr-vivado"].find("readonly") is not None
    assert d["vr-vivado"].find("driver").get("type") == "raw"
    assert d["vr-seed"].find("readonly") is not None
    assert d["vr-scratch"].find("readonly") is None
    assert [x.find("target").get("dev") for x in root().findall("devices/disk")] == ["vda", "vdb", "vdc", "vdd"]


def test_nic_is_isolated_filtered_and_on_the_runner_network():
    nic = root().find("devices/interface")
    assert nic.get("type") == "network"
    assert nic.find("source").get("network") == "vivado-runners"
    assert nic.find("mac").get("address") == "52:54:00:76:00:02"
    assert nic.find("port").get("isolated") == "yes"
    ref = nic.find("filterref")
    assert ref.get("filter") == "clean-traffic"
    assert (ref.find("parameter").get("name"), ref.find("parameter").get("value")) == ("IP", "192.168.76.12")


def test_no_graphics_usb_balloon_or_host_devices():
    r = root()
    assert r.find("devices/graphics") is None
    assert r.find("devices/hostdev") is None
    assert r.find("devices/filesystem") is None
    assert r.find("devices/memballoon").get("model") == "none"
    usb = [c for c in r.findall("devices/controller") if c.get("type") == "usb"]
    assert [c.get("model") for c in usb] == ["none"]


def test_console_goes_to_a_log_file():
    serial = root().find("devices/serial")
    assert serial.get("type") == "pty"
    assert serial.find("log").get("file") == "/var/lib/vivado-runners/console/slot-2.log"
    assert serial.find("log").get("append") == "off"


def test_numa_pinning_when_configured():
    from dataclasses import replace

    r = root(replace(SPEC, cpuset="0-21,44-65", numa_node=0))
    assert r.find("vcpu").get("cpuset") == "0-21,44-65"
    mem = r.find("numatune/memory")
    assert (mem.get("mode"), mem.get("nodeset")) == ("strict", "0")
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_domain_xml.py -v`
Expected: FAIL, `No module named 'vivado_runners.domain_xml'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/domain_xml.py`:

```python
"""libvirt domain XML for one slot's VM.

The VM gets four virtio disks (root overlay, Vivado, seed, scratch), one NIC on
the isolated runner network, a serial console and nothing else. Any way the
guest stops (poweroff, reboot, crash) destroys the domain, so a VM never runs a
second job.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainSpec:
    name: str
    vcpus: int
    memory_gib: int
    mac: str
    ip: str
    network: str
    overlay: Path
    vivado: Path
    seed: Path
    scratch: Path
    console_log: Path
    cpuset: str | None = None
    numa_node: int | None = None


def _disk(devices: ET.Element, path: Path, fmt: str, dev: str, serial: str | None, readonly: bool) -> None:
    disk = ET.SubElement(devices, "disk", type="file", device="disk")
    ET.SubElement(disk, "driver", name="qemu", type=fmt, discard="unmap")
    ET.SubElement(disk, "source", file=str(path))
    ET.SubElement(disk, "target", dev=dev, bus="virtio")
    if serial:
        ET.SubElement(disk, "serial").text = serial
    if readonly:
        ET.SubElement(disk, "readonly")


def render(spec: DomainSpec) -> str:
    domain = ET.Element("domain", type="kvm")
    ET.SubElement(domain, "name").text = spec.name
    ET.SubElement(domain, "memory", unit="GiB").text = str(spec.memory_gib)
    vcpu = ET.SubElement(domain, "vcpu", placement="static")
    vcpu.text = str(spec.vcpus)
    if spec.cpuset:
        vcpu.set("cpuset", spec.cpuset)
    if spec.numa_node is not None:
        numatune = ET.SubElement(domain, "numatune")
        ET.SubElement(numatune, "memory", mode="strict", nodeset=str(spec.numa_node))

    os_ = ET.SubElement(domain, "os")
    ET.SubElement(os_, "type", arch="x86_64", machine="q35").text = "hvm"
    ET.SubElement(os_, "boot", dev="hd")
    features = ET.SubElement(domain, "features")
    ET.SubElement(features, "acpi")
    ET.SubElement(features, "apic")
    ET.SubElement(domain, "cpu", mode="host-passthrough")
    for event in ("on_poweroff", "on_reboot", "on_crash"):
        ET.SubElement(domain, event).text = "destroy"

    devices = ET.SubElement(domain, "devices")
    _disk(devices, spec.overlay, "qcow2", "vda", None, readonly=False)
    _disk(devices, spec.vivado, "raw", "vdb", "vr-vivado", readonly=True)
    _disk(devices, spec.seed, "raw", "vdc", "vr-seed", readonly=True)
    _disk(devices, spec.scratch, "qcow2", "vdd", "vr-scratch", readonly=False)

    nic = ET.SubElement(devices, "interface", type="network")
    ET.SubElement(nic, "source", network=spec.network)
    ET.SubElement(nic, "mac", address=spec.mac)
    ET.SubElement(nic, "model", type="virtio")
    ET.SubElement(nic, "port", isolated="yes")
    ref = ET.SubElement(nic, "filterref", filter="clean-traffic")
    ET.SubElement(ref, "parameter", name="IP", value=spec.ip)

    serial = ET.SubElement(devices, "serial", type="pty")
    ET.SubElement(serial, "log", file=str(spec.console_log), append="off")
    ET.SubElement(serial, "target", port="0")
    console = ET.SubElement(devices, "console", type="pty")
    ET.SubElement(console, "target", type="serial", port="0")

    ET.SubElement(devices, "controller", type="usb", model="none")
    ET.SubElement(devices, "memballoon", model="none")
    rng = ET.SubElement(devices, "rng", model="virtio")
    ET.SubElement(rng, "backend", model="random").text = "/dev/urandom"

    ET.indent(domain)
    return ET.tostring(domain, encoding="unicode")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_domain_xml.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/domain_xml.py tests/test_domain_xml.py
git commit -m "domain_xml: one-job VM with four disks and an isolated NIC"
```

---

### Task 6: Hypervisor

**Files:**
- Create: `src/vivado_runners/hypervisor.py`
- Test: `tests/test_hypervisor.py`

**Interfaces:**
- Produces:
  - `SlotDisks(overlay: Path, scratch: Path, seed: Path)`
  - `Run = Callable[..., subprocess.CompletedProcess]` called as `run(cmd: list[str], check: bool = True)`
  - `VirshHypervisor(run=_run)` with:
    - `list_domains(prefix: str) -> list[str]`
    - `prepare(slot_dir: Path, base: Path, scratch_gib: int, seed_files: dict[str, str]) -> SlotDisks`
    - `start(name: str, xml: str, slot_dir: Path) -> None`
    - `is_running(name: str) -> bool`
    - `destroy(name: str) -> None` (no error if the domain is already gone)
    - `wipe(slot_dir: Path) -> None`
    - `free_gib(path: Path) -> float`
    - `node_cpulist(node: int) -> str`
- The same method set is the contract `tests/fakes.py::FakeHypervisor` implements in Task 7.

- [ ] **Step 1: Write the failing tests**

`tests/test_hypervisor.py`:

```python
import subprocess
from pathlib import Path

from vivado_runners.hypervisor import SlotDisks, VirshHypervisor


class Shell:
    """Records commands; answers from `outputs`, keyed by the first two words."""

    def __init__(self, outputs=None, fail=()):
        self.cmds = []
        self.outputs = outputs or {}
        self.fail = set(fail)

    def __call__(self, cmd, check=True):
        self.cmds.append(cmd)
        key = " ".join(cmd[:4])
        code = 1 if any(f in key for f in self.fail) else 0
        if code and check:
            raise subprocess.CalledProcessError(code, cmd)
        out = next((v for k, v in self.outputs.items() if k in " ".join(cmd)), "")
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="")


def test_list_domains_filters_by_prefix():
    sh = Shell({"list --all --name": "vr-big-storage-0\nvr-big-storage-1\ndocker\n\n"})
    assert VirshHypervisor(sh).list_domains("vr-big-storage-") == ["vr-big-storage-0", "vr-big-storage-1"]
    assert sh.cmds == [["virsh", "-c", "qemu:///system", "list", "--all", "--name"]]


def test_prepare_creates_overlay_scratch_and_seed(tmp_path):
    sh = Shell()
    slot = tmp_path / "slot-0"
    base = Path("/images/runner-base-2026-10-02.1.qcow2")
    disks = VirshHypervisor(sh).prepare(slot, base, 60, {"jitconfig": "abc==", "proxy": "http://192.168.76.1:3128"})
    assert disks == SlotDisks(overlay=slot / "overlay.qcow2", scratch=slot / "scratch.qcow2", seed=slot / "seed.iso")
    assert sh.cmds[0] == ["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(disks.overlay)]
    assert sh.cmds[1] == ["qemu-img", "create", "-q", "-f", "qcow2", str(disks.scratch), "60G"]
    assert sh.cmds[2][:2] == ["xorriso", "-as"]
    assert sh.cmds[2][-1] == str(slot / "seed")
    assert sh.cmds[2][sh.cmds[2].index("-V") : sh.cmds[2].index("-V") + 2] == ["-V", "VRSEED"]
    assert not (slot / "seed").exists(), "the plaintext seed directory is removed once the ISO exists"
    assert oct(slot.stat().st_mode & 0o777) == "0o700"


def test_prepare_writes_seed_files_before_building_the_iso(tmp_path):
    seen = {}

    def sh(cmd, check=True):
        if cmd[0] == "xorriso":
            seed = Path(cmd[-1])
            seen.update({p.name: p.read_text() for p in seed.iterdir()})
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    VirshHypervisor(sh).prepare(tmp_path / "slot-0", Path("/b.qcow2"), 1, {"jitconfig": "abc==", "proxy": "p"})
    assert seen == {"jitconfig": "abc==", "proxy": "p"}


def test_prepare_starts_from_an_empty_slot_dir(tmp_path):
    slot = tmp_path / "slot-0"
    slot.mkdir()
    (slot / "leftover").write_text("x")
    VirshHypervisor(Shell()).prepare(slot, Path("/b.qcow2"), 1, {})
    assert not (slot / "leftover").exists()


def test_start_writes_the_xml_and_creates_a_transient_domain(tmp_path):
    sh = Shell()
    slot = tmp_path / "slot-0"
    slot.mkdir()
    VirshHypervisor(sh).start("vr-h-0", "<domain/>", slot)
    assert (slot / "domain.xml").read_text() == "<domain/>"
    assert sh.cmds == [["virsh", "-c", "qemu:///system", "create", str(slot / "domain.xml")]]


def test_is_running_reads_domstate_and_treats_a_missing_domain_as_stopped():
    assert VirshHypervisor(Shell({"domstate": "running\n"})).is_running("vr-h-0") is True
    assert VirshHypervisor(Shell({"domstate": "paused\n"})).is_running("vr-h-0") is True
    assert VirshHypervisor(Shell({"domstate": "shut off\n"})).is_running("vr-h-0") is False
    assert VirshHypervisor(Shell(fail=["domstate"])).is_running("vr-h-0") is False


def test_destroy_ignores_a_domain_that_is_already_gone():
    sh = Shell(fail=["destroy"])
    VirshHypervisor(sh).destroy("vr-h-0")
    assert sh.cmds == [["virsh", "-c", "qemu:///system", "destroy", "vr-h-0"]]


def test_wipe_removes_the_directory_and_tolerates_its_absence(tmp_path):
    slot = tmp_path / "slot-0"
    slot.mkdir()
    (slot / "overlay.qcow2").write_text("x")
    hv = VirshHypervisor(Shell())
    hv.wipe(slot)
    hv.wipe(slot)
    assert not slot.exists()


def test_free_gib_reports_the_filesystem(tmp_path):
    assert VirshHypervisor(Shell()).free_gib(tmp_path) > 0
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_hypervisor.py -v`
Expected: FAIL, `No module named 'vivado_runners.hypervisor'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/hypervisor.py`:

```python
"""Everything the controller asks of the host: virsh, qemu-img, xorriso, disk space.

The controller never opens a disk image a job VM has written to. Overlays and
scratch disks are created empty, handed to the VM, and unlinked.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Run = Callable[..., subprocess.CompletedProcess]
VIRSH = ["virsh", "-c", "qemu:///system"]


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


@dataclass(frozen=True)
class SlotDisks:
    overlay: Path
    scratch: Path
    seed: Path


class VirshHypervisor:
    def __init__(self, run: Run = _run):
        self._run = run

    def list_domains(self, prefix: str) -> list[str]:
        out = self._run([*VIRSH, "list", "--all", "--name"]).stdout
        return [name for name in out.split() if name.startswith(prefix)]

    def prepare(self, slot_dir: Path, base: Path, scratch_gib: int, seed_files: dict[str, str]) -> SlotDisks:
        self.wipe(slot_dir)
        slot_dir.mkdir(parents=True, mode=0o700)
        slot_dir.chmod(0o700)
        disks = SlotDisks(
            overlay=slot_dir / "overlay.qcow2", scratch=slot_dir / "scratch.qcow2", seed=slot_dir / "seed.iso"
        )
        self._run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(disks.overlay)])
        self._run(["qemu-img", "create", "-q", "-f", "qcow2", str(disks.scratch), f"{scratch_gib}G"])
        seed_dir = slot_dir / "seed"
        seed_dir.mkdir(mode=0o700)
        for name, content in seed_files.items():
            (seed_dir / name).write_text(content)
        try:
            self._run(
                ["xorriso", "-as", "mkisofs", "-quiet", "-r", "-V", "VRSEED", "-o", str(disks.seed), str(seed_dir)]
            )
        finally:
            shutil.rmtree(seed_dir)
        return disks

    def start(self, name: str, xml: str, slot_dir: Path) -> None:
        path = slot_dir / "domain.xml"
        path.write_text(xml)
        self._run([*VIRSH, "create", str(path)])

    def is_running(self, name: str) -> bool:
        result = self._run([*VIRSH, "domstate", name], check=False)
        return result.returncode == 0 and result.stdout.strip() not in ("", "shut off", "crashed")

    def destroy(self, name: str) -> None:
        self._run([*VIRSH, "destroy", name], check=False)

    def wipe(self, slot_dir: Path) -> None:
        if slot_dir.exists():
            shutil.rmtree(slot_dir)

    def free_gib(self, path: Path) -> float:
        return shutil.disk_usage(path).free / 2**30

    def node_cpulist(self, node: int) -> str:
        return Path(f"/sys/devices/system/node/node{node}/cpulist").read_text().strip()
```

Note for the reviewer: `slot_dir` is mode 0700 and owned by the controller's user, so other host users cannot read the seed ISO. libvirt reaches the files because qemu's user is given access by libvirt's DAC driver when the domain starts (it chowns each disk to `libvirt-qemu`) and because Plan 2 puts `libvirt-qemu` in a group that can traverse the directory. If Plan 2's first boot shows qemu cannot open the disks, the fix belongs there (directory group and mode), not here.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_hypervisor.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/hypervisor.py tests/test_hypervisor.py
git commit -m "hypervisor: virsh, qemu-img and xorriso behind one class"
```

---

### Task 7: Slot lifecycle

**Files:**
- Create: `src/vivado_runners/slot.py`, `tests/fakes.py`
- Test: `tests/test_slot.py`

**Interfaces:**
- Consumes: `Config` (Task 2), `images.resolve` (Task 3), `GitHubClient` methods (Task 4), `DomainSpec`/`render` (Task 5), `VirshHypervisor` method set (Task 6).
- Produces:
  - `Outcome(reason: str, seconds: float, runner: str | None, base: str | None, vivado: str | None)`. `reason` is one of `finished`, `no-job`, `register-timeout`, `wall-limit`, `start-error`, `jit-error`, `low-disk`, `stopped`.
  - `FAILURES = frozenset({"no-job", "register-timeout", "start-error"})`
  - `Slot(index, cfg, github, hv, group_id, stop, clock=time.monotonic, sleep=None, new_id=None, poll_seconds=5.0)` with `run_once() -> Outcome` and `run_forever() -> str` (returns `"stopped"` or `"halted"`).
  - `tests/fakes.py`: `FakeClock`, `FakeGitHub`, `FakeHypervisor`.

How each outcome is decided:

| Reason | When |
|---|---|
| `finished` | The VM powered off and GitHub no longer lists the runner (an ephemeral runner is removed once it has run its job) |
| `no-job` | The VM powered off but GitHub still lists the runner: it never ran a job. The runner is deleted |
| `register-timeout` | The runner was not `online` in GitHub within `register_timeout_minutes` of boot |
| `wall-limit` | The VM was still running after `wall_limit_minutes` |
| `start-error` | Preparing disks or starting the domain raised |
| `jit-error` | GitHub refused or could not be reached for a JIT config |
| `low-disk` | Free space under `min_free_gib`; nothing was started |
| `stopped` | The controller is shutting down |

Three `FAILURES` in a row halt the slot. `jit-error` backs off 30 s doubling to 600 s. `low-disk` retries after 60 s.

- [ ] **Step 1: Write the fakes**

`tests/fakes.py`:

```python
"""Test doubles for GitHub, the hypervisor and time."""

from __future__ import annotations

from pathlib import Path

from vivado_runners.github import GitHubError, JitRunner, Runner
from vivado_runners.hypervisor import SlotDisks


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeStop:
    def __init__(self):
        self.flag = False

    def is_set(self) -> bool:
        return self.flag


class FakeGitHub:
    def __init__(self):
        self.runners: dict[int, Runner] = {}
        self.next_id = 100
        self.jit_errors = 0  # how many create_jit calls fail before one succeeds
        self.online_after: float | None = 0.0  # None: the runner never comes online
        self.clock = None
        self.created: list[str] = []
        self.deleted: list[int] = []
        self._born: dict[int, float] = {}

    def create_jit(self, name, group_id, labels):
        if self.jit_errors:
            self.jit_errors -= 1
            raise GitHubError(503, "unavailable")
        runner_id = self.next_id
        self.next_id += 1
        self.runners[runner_id] = Runner(id=runner_id, name=name, status="offline", busy=False)
        self._born[runner_id] = self.clock() if self.clock else 0.0
        self.created.append(name)
        return JitRunner(id=runner_id, encoded_jit_config=f"jit-{runner_id}")

    def list_runners(self):
        now = self.clock() if self.clock else 0.0
        out = []
        for r in self.runners.values():
            online = self.online_after is not None and now - self._born[r.id] >= self.online_after
            out.append(Runner(id=r.id, name=r.name, status="online" if online else "offline", busy=False))
        return out

    def delete_runner(self, runner_id):
        self.deleted.append(runner_id)
        self.runners.pop(runner_id, None)

    def job_done(self, runner_id):
        """GitHub removes an ephemeral runner once it has run its job."""
        self.runners.pop(runner_id, None)


class FakeHypervisor:
    def __init__(self, clock: FakeClock, github: FakeGitHub):
        self.clock = clock
        self.github = github
        self.run_seconds: float | None = 600.0  # None: the VM never powers off
        self.runs_job = True
        self.free = 1000.0
        self.start_error: Exception | None = None
        self.domains: dict[str, float] = {}  # name -> start time
        self.events: list[tuple] = []

    def list_domains(self, prefix):
        return [n for n in self.domains if n.startswith(prefix)]

    def prepare(self, slot_dir, base, scratch_gib, seed_files):
        self.events.append(("prepare", slot_dir.name, base.name, scratch_gib, dict(seed_files)))
        return SlotDisks(slot_dir / "overlay.qcow2", slot_dir / "scratch.qcow2", slot_dir / "seed.iso")

    def start(self, name, xml, slot_dir):
        if self.start_error:
            raise self.start_error
        self.events.append(("start", name))
        self.domains[name] = self.clock()
        self.last_xml = xml

    def is_running(self, name):
        if name not in self.domains:
            return False
        if self.run_seconds is not None and self.clock() - self.domains[name] >= self.run_seconds:
            del self.domains[name]
            if self.runs_job:
                newest = max(self.github.runners, default=None)
                if newest is not None:
                    self.github.job_done(newest)
            return False
        return True

    def destroy(self, name):
        self.events.append(("destroy", name))
        self.domains.pop(name, None)

    def wipe(self, slot_dir: Path):
        self.events.append(("wipe", slot_dir.name))

    def free_gib(self, path):
        return self.free

    def node_cpulist(self, node):
        return {0: "0-21,44-65", 1: "22-43,66-87"}[node]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_slot.py`:

```python
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.fakes import FakeClock, FakeGitHub, FakeHypervisor, FakeStop
from vivado_runners import slot as slot_mod
from vivado_runners.config import Config, GithubConfig, SlotsConfig
from vivado_runners.slot import Slot


@pytest.fixture
def env(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "runner-base-2026-10-02.1.qcow2").write_bytes(b"x")
    (images / "vivado-2025.2-2026-10-02.squashfs").write_bytes(b"x")
    (images / "runner-base-current").symlink_to("runner-base-2026-10-02.1.qcow2")
    (images / "vivado-current").symlink_to("vivado-2025.2-2026-10-02.squashfs")
    cfg = Config(
        host="big-storage",
        state_dir=tmp_path,
        min_free_gib=100,
        network="vivado-runners",
        proxy="http://192.168.76.1:3128",
        github=GithubConfig("fpgas-online", 1, 2, Path("/k"), "vivado"),
        slots=SlotsConfig(
            count=2, vcpus=8, memory_gib=24, scratch_gib=60, wall_limit_minutes=120, labels=("self-hosted", "x")
        ),
    )
    clock = FakeClock()
    gh = FakeGitHub()
    gh.clock = clock
    hv = FakeHypervisor(clock, gh)
    stop = FakeStop()

    def make(index=0, cfg=cfg):
        return Slot(
            index, cfg, gh, hv, group_id=7, stop=stop, clock=clock, sleep=clock.sleep, new_id=lambda: "deadbeef"
        )

    return type("Env", (), {"cfg": cfg, "clock": clock, "gh": gh, "hv": hv, "stop": stop, "make": staticmethod(make)})


def test_a_normal_job(env):
    out = env.make().run_once()
    assert out.reason == "finished"
    assert out.runner == "big-storage-slot0-deadbeef"
    assert (out.base, out.vivado) == ("runner-base-2026-10-02.1.qcow2", "vivado-2025.2-2026-10-02.squashfs")
    assert 600 <= out.seconds < 610
    assert env.gh.deleted == [], "GitHub already removed the runner; nothing to delete"
    kinds = [e[0] for e in env.hv.events]
    assert kinds == ["prepare", "start", "destroy", "wipe"]
    assert env.hv.events[0] == (
        "prepare",
        "slot-0",
        "runner-base-2026-10-02.1.qcow2",
        60,
        {"jitconfig": "jit-100", "proxy": "http://192.168.76.1:3128"},
    )


def test_the_domain_xml_uses_the_slot_addressing(env):
    env.make(index=1).run_once()
    assert "<name>vr-big-storage-1</name>" in env.hv.last_xml
    assert 'address="52:54:00:76:00:01"' in env.hv.last_xml
    assert 'value="192.168.76.11"' in env.hv.last_xml
    assert "cpuset" not in env.hv.last_xml


def test_numa_pinning_comes_from_the_host(env):
    cfg = replace(env.cfg, slots=replace(env.cfg.slots, numa_nodes=(0, 1)))
    env.make(index=1, cfg=cfg).run_once()
    assert 'cpuset="22-43,66-87"' in env.hv.last_xml
    assert 'nodeset="1"' in env.hv.last_xml


def test_vm_that_powers_off_without_running_a_job(env):
    env.hv.runs_job = False
    env.hv.run_seconds = 40.0
    out = env.make().run_once()
    assert out.reason == "no-job"
    assert env.gh.deleted == [100]


def test_runner_never_registers(env):
    env.gh.online_after = None
    env.hv.run_seconds = None
    out = env.make().run_once()
    assert out.reason == "register-timeout"
    assert 300 < out.seconds < 340
    assert ("destroy", "vr-big-storage-0") in env.hv.events
    assert env.gh.deleted == [100]


def test_wall_limit_kills_a_job_that_never_ends(env):
    env.hv.run_seconds = None
    out = env.make().run_once()
    assert out.reason == "wall-limit"
    assert 7200 < out.seconds < 7210
    assert ("destroy", "vr-big-storage-0") in env.hv.events


def test_registration_is_not_polled_once_seen(env):
    calls = []
    original = env.gh.list_runners
    env.gh.list_runners = lambda: calls.append(env.clock()) or original()
    env.make().run_once()
    assert len(calls) == 2, "once while waiting to register, once after the VM stopped"


def test_start_failure_still_cleans_up(env):
    env.hv.start_error = RuntimeError("virsh create failed")
    out = env.make().run_once()
    assert out.reason == "start-error"
    assert [e[0] for e in env.hv.events] == ["prepare", "destroy", "wipe"]
    assert env.gh.deleted == [100]


def test_jit_failure_starts_nothing(env):
    env.gh.jit_errors = 1
    out = env.make().run_once()
    assert out.reason == "jit-error"
    assert env.hv.events == []


def test_low_disk_starts_nothing_and_asks_github_for_nothing(env):
    env.hv.free = 50.0
    out = env.make().run_once()
    assert out.reason == "low-disk"
    assert env.gh.created == []
    assert env.hv.events == []


def test_stop_destroys_the_running_vm(env):
    env.hv.run_seconds = None
    original = env.clock.sleep

    def sleep(seconds):
        original(seconds)
        if env.clock.now > 60:
            env.stop.flag = True

    s = Slot(0, env.cfg, env.gh, env.hv, group_id=7, stop=env.stop, clock=env.clock, sleep=sleep, new_id=lambda: "ab")
    out = s.run_once()
    assert out.reason == "stopped"
    assert ("destroy", "vr-big-storage-0") in env.hv.events


def test_status_file_tracks_the_slot(env):
    env.make().run_once()
    status = json.loads((env.cfg.status_dir / "slot-0.json").read_text())
    assert status["state"] == "idle"
    assert status["last_reason"] == "finished"
    assert status["last_runner"] == "big-storage-slot0-deadbeef"


def test_run_forever_halts_after_three_failures_in_a_row(env):
    env.hv.runs_job = False
    env.hv.run_seconds = 40.0
    assert env.make().run_forever() == "halted"
    assert len(env.gh.created) == 3
    assert json.loads((env.cfg.status_dir / "slot-0.json").read_text())["state"] == "halted"


def test_a_success_resets_the_failure_count(env):
    outcomes = iter(["no-job", "no-job", "finished", "no-job", "no-job", "no-job"])
    s = env.make()
    s.run_once = lambda: slot_mod.Outcome(next(outcomes), 1.0, "r", "b", "v")
    assert s.run_forever() == "halted"
    assert list(outcomes) == []


def test_jit_errors_back_off_and_do_not_halt_the_slot(env):
    outcomes = iter(["jit-error"] * 6 + ["finished"])

    def once():
        reason = next(outcomes)
        if reason == "finished":
            env.stop.flag = True
        return slot_mod.Outcome(reason, 0.0, None, None, None)

    s = env.make()
    s.run_once = once
    assert s.run_forever() == "stopped"
    assert env.clock.sleeps == [30, 60, 120, 240, 480, 600]


def test_low_disk_retries_after_a_minute(env):
    outcomes = iter(["low-disk", "low-disk", "finished"])

    def once():
        reason = next(outcomes)
        if reason == "finished":
            env.stop.flag = True
        return slot_mod.Outcome(reason, 0.0, None, None, None)

    s = env.make()
    s.run_once = once
    s.run_forever()
    assert env.clock.sleeps == [60, 60]
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/test_slot.py -v`
Expected: FAIL, `cannot import name 'slot'`.

- [ ] **Step 4: Implement**

`src/vivado_runners/slot.py`:

```python
"""One slot: boot a VM for one job, wait for it to end, remove every trace."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from . import images
from .config import Config
from .domain_xml import DomainSpec, render

log = logging.getLogger("vivado_runners.slot")

FAILURES = frozenset({"no-job", "register-timeout", "start-error"})
HALT_AFTER = 3
JIT_BACKOFF_START = 30
JIT_BACKOFF_MAX = 600
LOW_DISK_RETRY = 60
REGISTRATION_POLL = 30


@dataclass(frozen=True)
class Outcome:
    reason: str
    seconds: float
    runner: str | None
    base: str | None
    vivado: str | None


class Slot:
    def __init__(
        self,
        index: int,
        cfg: Config,
        github,
        hv,
        group_id: int,
        stop,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        new_id: Callable[[], str] | None = None,
        poll_seconds: float = 5.0,
    ):
        self.index = index
        self.cfg = cfg
        self.github = github
        self.hv = hv
        self.group_id = group_id
        self.stop = stop
        self.clock = clock
        self.sleep = sleep or (lambda seconds: stop.wait(seconds))
        self.new_id = new_id or (lambda: secrets.token_hex(4))
        self.poll_seconds = poll_seconds

    # -- status file, read by `vivado-runners status` --------------------------------

    def _status(self, state: str, **extra) -> None:
        self.cfg.status_dir.mkdir(parents=True, exist_ok=True)
        path = self.cfg.status_dir / f"slot-{self.index}.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        previous.update({"slot": self.index, "state": state, "since": datetime.now(UTC).isoformat(), **extra})
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(previous))
        tmp.replace(path)

    # -- one job ------------------------------------------------------------------

    def run_once(self) -> Outcome:
        cfg = self.cfg
        started = self.clock()

        def done(reason: str, runner: str | None = None, versions: images.ImageVersions | None = None) -> Outcome:
            outcome = Outcome(
                reason=reason,
                seconds=self.clock() - started,
                runner=runner,
                base=versions.base.name if versions else None,
                vivado=versions.vivado.name if versions else None,
            )
            self._status("idle", last_reason=reason, last_runner=runner)
            log.info("job %s", json.dumps({"slot": self.index, "host": cfg.host, **asdict(outcome)}))
            return outcome

        if self.hv.free_gib(cfg.state_dir) < cfg.min_free_gib:
            return done("low-disk")

        versions = images.resolve(cfg.images_dir)
        runner = f"{cfg.runner_prefix}{self.index}-{self.new_id()}"
        try:
            jit = self.github.create_jit(runner, self.group_id, list(cfg.slots.labels))
        except Exception:
            log.exception("slot %d: could not get a JIT runner config", self.index)
            return done("jit-error")

        domain = cfg.domain_name(self.index)
        slot_dir = cfg.slot_dir(self.index)
        reason = "start-error"
        try:
            disks = self.hv.prepare(
                slot_dir,
                versions.base,
                cfg.slots.scratch_gib,
                {"jitconfig": jit.encoded_jit_config, "proxy": cfg.proxy},
            )
            node = cfg.slots.numa_nodes[self.index] if cfg.slots.numa_nodes else None
            cfg.console_dir.mkdir(parents=True, exist_ok=True)
            xml = render(
                DomainSpec(
                    name=domain,
                    vcpus=cfg.slots.vcpus,
                    memory_gib=cfg.slots.memory_gib,
                    mac=cfg.slot_mac(self.index),
                    ip=cfg.slot_ip(self.index),
                    network=cfg.network,
                    overlay=disks.overlay,
                    vivado=versions.vivado,
                    seed=disks.seed,
                    scratch=disks.scratch,
                    console_log=cfg.console_dir / f"slot-{self.index}.log",
                    cpuset=self.hv.node_cpulist(node) if node is not None else None,
                    numa_node=node,
                )
            )
            self.hv.start(domain, xml, slot_dir)
            self._status("running", runner=runner, domain=domain, base=versions.base.name, vivado=versions.vivado.name)
            reason = self._wait(domain, runner, started)
        except Exception:
            log.exception("slot %d: could not start %s", self.index, domain)
        finally:
            self.hv.destroy(domain)
            self.hv.wipe(slot_dir)
            reason = self._reap_runner(jit.id, reason)
        return done(reason, runner, versions)

    def _wait(self, domain: str, runner: str, started: float) -> str:
        wall = self.cfg.slots.wall_limit_minutes * 60
        register_limit = self.cfg.slots.register_timeout_minutes * 60
        registered = False
        next_check = 0.0
        while True:
            if self.stop.is_set():
                return "stopped"
            if not self.hv.is_running(domain):
                return "finished"
            elapsed = self.clock() - started
            if elapsed > wall:
                return "wall-limit"
            if not registered:
                if elapsed >= next_check:
                    next_check = elapsed + REGISTRATION_POLL
                    registered = self._is_online(runner)
                if not registered and elapsed > register_limit:
                    return "register-timeout"
            self.sleep(self.poll_seconds)

    def _is_online(self, runner: str) -> bool:
        try:
            return any(r.name == runner and r.status == "online" for r in self.github.list_runners())
        except Exception:
            log.exception("slot %d: could not list runners", self.index)
            return False

    def _reap_runner(self, runner_id: int, reason: str) -> str:
        """Delete the runner if GitHub still lists it. A VM that powered off while
        its runner is still listed never ran a job."""
        try:
            present = any(r.id == runner_id for r in self.github.list_runners())
            if present:
                self.github.delete_runner(runner_id)
        except Exception:
            log.exception("slot %d: could not remove runner %d", self.index, runner_id)
            return reason
        return "no-job" if present and reason == "finished" else reason

    # -- the loop ------------------------------------------------------------------

    def run_forever(self) -> str:
        failures = 0
        backoff = JIT_BACKOFF_START
        while not self.stop.is_set():
            outcome = self.run_once()
            if outcome.reason == "stopped":
                break
            if outcome.reason == "jit-error":
                self.sleep(backoff)
                backoff = min(backoff * 2, JIT_BACKOFF_MAX)
                continue
            backoff = JIT_BACKOFF_START
            if outcome.reason == "low-disk":
                self.sleep(LOW_DISK_RETRY)
                continue
            if outcome.reason in FAILURES:
                failures += 1
                if failures >= HALT_AFTER:
                    self._status("halted", last_reason=outcome.reason)
                    log.error(
                        "ALERT slot %d halted after %d failures in a row (%s)", self.index, failures, outcome.reason
                    )
                    return "halted"
            else:
                failures = 0
        return "stopped"
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_slot.py -v`
Expected: all pass. If `test_registration_is_not_polled_once_seen` counts differently, read the test's assertion message before changing code: the contract is one poll while waiting plus one after the VM stops.

- [ ] **Step 6: Commit**

```bash
git add src/vivado_runners/slot.py tests/fakes.py tests/test_slot.py
git commit -m "slot: one VM per job, with the failure policy from the spec"
```

---

### Task 8: Controller

**Files:**
- Create: `src/vivado_runners/controller.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Consumes: `Slot` (Task 7), `GitHubClient` (Task 4), `VirshHypervisor` (Task 6), `Config`, `MAX_SLOTS` (Task 2).
- Produces: `startup_cleanup(cfg, github, hv) -> None`; `run(cfg, github=None, hv=None, stop=None, install_signals=False) -> int` (exit code: 0 when stopped, 1 when every slot halted). `install_signals=True` makes SIGTERM and SIGINT set `stop`; only the CLI passes it, so tests never replace pytest's handlers.

- [ ] **Step 1: Write the failing tests**

`tests/test_controller.py`:

```python
import threading
from pathlib import Path

from tests.fakes import FakeClock, FakeGitHub, FakeHypervisor
from vivado_runners import controller
from vivado_runners.config import Config, GithubConfig, SlotsConfig
from vivado_runners.github import GitHubError, Runner


def make_cfg(tmp_path, count=2):
    return Config(
        host="big-storage",
        state_dir=tmp_path,
        min_free_gib=100,
        network="vivado-runners",
        proxy="http://192.168.76.1:3128",
        github=GithubConfig("fpgas-online", 1, 2, Path("/k"), "vivado"),
        slots=SlotsConfig(count=count, vcpus=8, memory_gib=24, scratch_gib=60, wall_limit_minutes=120, labels=("x",)),
    )


def test_startup_cleanup_removes_only_this_hosts_leftovers(tmp_path):
    cfg = make_cfg(tmp_path)
    clock = FakeClock()
    gh = FakeGitHub()
    hv = FakeHypervisor(clock, gh)
    hv.domains = {"vr-big-storage-0": 0.0, "vr-buddy-0": 0.0, "docker": 0.0}
    gh.runners = {
        1: Runner(1, "big-storage-slot0-aaaa", "offline", False),
        2: Runner(2, "buddy-slot0-bbbb", "online", False),
        3: Runner(3, "big-storage-slot1-cccc", "online", True),
    }
    gh._born = {1: 0.0, 2: 0.0, 3: 0.0}
    controller.startup_cleanup(cfg, gh, hv)
    assert ("destroy", "vr-big-storage-0") in hv.events
    assert ("destroy", "vr-buddy-0") not in hv.events
    assert [e for e in hv.events if e[0] == "wipe"] == [("wipe", f"slot-{i}") for i in range(8)]
    assert sorted(gh.deleted) == [1, 3]


def test_startup_cleanup_survives_a_runner_github_will_not_delete(tmp_path):
    cfg = make_cfg(tmp_path)
    gh = FakeGitHub()
    hv = FakeHypervisor(FakeClock(), gh)
    gh.runners = {1: Runner(1, "big-storage-slot0-aaaa", "online", True)}
    gh._born = {1: 0.0}

    def refuse(runner_id):
        raise GitHubError(422, "runner is busy")

    gh.delete_runner = refuse
    controller.startup_cleanup(cfg, gh, hv)


def test_run_returns_1_when_every_slot_halts(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    gh = FakeGitHub()
    gh.runner_group_id = lambda name: 7
    hv = FakeHypervisor(FakeClock(), gh)

    class Halting:
        def __init__(self, index, *args, **kwargs):
            self.index = index

        def run_forever(self):
            return "halted"

    monkeypatch.setattr(controller, "Slot", Halting)
    assert controller.run(cfg, github=gh, hv=hv, stop=threading.Event()) == 1


def test_run_returns_0_when_stopped(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    gh = FakeGitHub()
    gh.runner_group_id = lambda name: 7
    hv = FakeHypervisor(FakeClock(), gh)
    stop = threading.Event()
    started = []

    class Waiting:
        def __init__(self, index, cfg, github, hv, group_id, stop, **kwargs):
            self.stop = stop
            started.append((index, group_id))

        def run_forever(self):
            self.stop.wait(5)
            return "stopped"

    monkeypatch.setattr(controller, "Slot", Waiting)
    threading.Timer(0.2, stop.set).start()
    assert controller.run(cfg, github=gh, hv=hv, stop=stop) == 0
    assert sorted(started) == [(0, 7), (1, 7)]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_controller.py -v`
Expected: FAIL, `cannot import name 'controller'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/controller.py`:

```python
"""Start-up cleanup, one thread per slot, and shutdown on a signal."""

from __future__ import annotations

import logging
import signal
import threading

from .config import MAX_SLOTS, Config
from .github import GitHubClient, GitHubError
from .hypervisor import VirshHypervisor
from .slot import Slot

log = logging.getLogger("vivado_runners.controller")


def startup_cleanup(cfg: Config, github, hv) -> None:
    """Nothing from a previous run survives: its VMs, its disks, its runners."""
    for name in hv.list_domains(cfg.domain_prefix):
        log.warning("destroying leftover domain %s", name)
        hv.destroy(name)
    for index in range(MAX_SLOTS):
        hv.wipe(cfg.slot_dir(index))
    for runner in github.list_runners():
        if not runner.name.startswith(cfg.runner_prefix):
            continue
        log.warning("removing leftover runner %s (%s)", runner.name, runner.status)
        try:
            github.delete_runner(runner.id)
        except GitHubError as error:
            log.warning("could not remove runner %s: %s", runner.name, error)


def run(cfg: Config, github=None, hv=None, stop: threading.Event | None = None, install_signals: bool = False) -> int:
    github = github or GitHubClient(
        cfg.github.org, cfg.github.app_id, cfg.github.installation_id, cfg.github.key_file.read_text()
    )
    hv = hv or VirshHypervisor()
    stop = stop or threading.Event()

    startup_cleanup(cfg, github, hv)
    group_id = github.runner_group_id(cfg.github.runner_group)

    results: dict[int, str] = {}

    def work(index: int) -> None:
        results[index] = Slot(index, cfg, github, hv, group_id, stop).run_forever()

    if install_signals:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())

    threads = [threading.Thread(target=work, args=(i,), name=f"slot-{i}") for i in range(cfg.slots.count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        while thread.is_alive():
            thread.join(timeout=1.0)

    if all(reason == "halted" for reason in results.values()):
        log.error("ALERT every slot halted")
        return 1
    return 0
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_controller.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/vivado_runners/controller.py tests/test_controller.py
git commit -m "controller: clean up leftovers, run the slots, stop on a signal"
```

---

### Task 9: Command line

**Files:**
- Create: `src/vivado_runners/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `config.load`, `controller.run`, `controller.startup_cleanup`, `images.*`.
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands:
  - `run [--config PATH]`
  - `cleanup [--config PATH]`
  - `status [--config PATH]`
  - `images list [--config PATH]`
  - `images activate {base,vivado} NAME [--config PATH]`
  Default config path `/etc/vivado-runners/config.toml`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json

import pytest

from vivado_runners import cli

CONFIG = """
host = "big-storage"
state_dir = "{state}"

[github]
org = "fpgas-online"
app_id = 1
installation_id = 2
key_file = "/k"
runner_group = "vivado"

[slots]
count = 2
vcpus = 8
memory_gib = 24
scratch_gib = 60
wall_limit_minutes = 120
labels = ["x"]
"""


@pytest.fixture
def cfg_path(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for name in (
        "runner-base-2026-09-25.1.qcow2",
        "runner-base-2026-10-02.1.qcow2",
        "vivado-2025.2-2026-10-02.squashfs",
    ):
        (images / name).write_bytes(b"x")
    (images / "runner-base-current").symlink_to("runner-base-2026-10-02.1.qcow2")
    path = tmp_path / "config.toml"
    path.write_text(CONFIG.format(state=tmp_path))
    return path


def test_images_list_marks_the_current_version(cfg_path, capsys):
    assert cli.main(["images", "list", "--config", str(cfg_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "base      runner-base-2026-09-25.1.qcow2",
        "base    * runner-base-2026-10-02.1.qcow2",
        "vivado    vivado-2025.2-2026-10-02.squashfs",
    ]


def test_images_activate_rolls_back(cfg_path, capsys):
    args = ["images", "activate", "base", "runner-base-2026-09-25.1.qcow2", "--config", str(cfg_path)]
    assert cli.main(args) == 0
    assert (cfg_path.parent / "images" / "runner-base-current").readlink().name == "runner-base-2026-09-25.1.qcow2"
    assert "runner-base-current -> runner-base-2026-09-25.1.qcow2" in capsys.readouterr().out


def test_images_activate_reports_an_unknown_version(cfg_path, capsys):
    assert cli.main(["images", "activate", "base", "nope.qcow2", "--config", str(cfg_path)]) == 2
    assert "no such base image: nope.qcow2" in capsys.readouterr().err


def test_status_prints_one_line_per_slot(cfg_path, capsys):
    status = cfg_path.parent / "status"
    status.mkdir()
    (status / "slot-0.json").write_text(
        json.dumps(
            {"slot": 0, "state": "running", "since": "2026-10-02T01:00:00+00:00", "runner": "big-storage-slot0-ab"}
        )
    )
    assert cli.main(["status", "--config", str(cfg_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["SLOT", "STATE", "SINCE", "RUNNER", "LAST"]
    assert out[1].split() == ["0", "running", "2026-10-02T01:00:00+00:00", "big-storage-slot0-ab", "-"]
    assert out[2].split() == ["1", "unknown", "-", "-", "-"]


def test_run_hands_the_config_to_the_controller(cfg_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.controller, "run", lambda cfg, install_signals: seen.setdefault("host", cfg.host) and 0)
    assert cli.main(["run", "--config", str(cfg_path)]) == 0
    assert seen == {"host": "big-storage"}


def test_a_bad_config_is_exit_code_2(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text("[github]\n")
    assert cli.main(["status", "--config", str(path)]) == 2
    assert "missing github.org" in capsys.readouterr().err
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `cannot import name 'cli'`.

- [ ] **Step 3: Implement**

`src/vivado_runners/cli.py`:

```python
"""vivado-runners: run the controller, inspect slots, select images."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import config, controller, images
from .github import GitHubClient
from .hypervisor import VirshHypervisor

DEFAULT_CONFIG = "/etc/vivado-runners/config.toml"


def _status(cfg: config.Config) -> int:
    print(f"{'SLOT':<5}{'STATE':<10}{'SINCE':<34}{'RUNNER':<34}LAST")
    for index in range(cfg.slots.count):
        path = cfg.status_dir / f"slot-{index}.json"
        s = json.loads(path.read_text()) if path.exists() else {}
        runner = s.get("runner") if s.get("state") == "running" else None
        print(
            f"{index:<5}{s.get('state', 'unknown'):<10}{s.get('since', '-'):<34}"
            f"{runner or '-':<34}{s.get('last_reason') or '-'}"
        )
    return 0


def _images_list(cfg: config.Config) -> int:
    for kind in ("base", "vivado"):
        current = images.current(cfg.images_dir, kind)
        for path in images.list_versions(cfg.images_dir, kind):
            print(f"{kind:<7} {'*' if path == current else ' '} {path.name}")
    return 0


def _images_activate(cfg: config.Config, kind: str, name: str) -> int:
    images.activate(cfg.images_dir, kind, name)
    print(f"{images.LINKS[kind]} -> {name} (new VMs use it; running VMs keep theirs)")
    return 0


def _cleanup(cfg: config.Config) -> int:
    github = GitHubClient(
        cfg.github.org, cfg.github.app_id, cfg.github.installation_id, cfg.github.key_file.read_text()
    )
    controller.startup_cleanup(cfg, github, VirshHypervisor())
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=DEFAULT_CONFIG, type=Path)

    parser = argparse.ArgumentParser(prog="vivado-runners", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", parents=[common], help="run the controller (what the systemd unit starts)")
    sub.add_parser("cleanup", parents=[common], help="destroy this host's VMs and deregister its runners")
    sub.add_parser("status", parents=[common], help="show each slot")
    img = sub.add_parser("images", help="list images or select the current one").add_subparsers(
        dest="images_command", required=True
    )
    img.add_parser("list", parents=[common])
    activate = img.add_parser(
        "activate", parents=[common], help="point the current symlink at a version (also rollback)"
    )
    activate.add_argument("kind", choices=["base", "vivado"])
    activate.add_argument("name")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = config.load(args.config)
        if args.command == "run":
            return controller.run(cfg, install_signals=True)
        if args.command == "cleanup":
            return _cleanup(cfg)
        if args.command == "status":
            return _status(cfg)
        if args.images_command == "list":
            return _images_list(cfg)
        return _images_activate(cfg, args.kind, args.name)
    except (config.ConfigError, images.ImageError) as error:
        print(f"vivado-runners: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the whole suite and the linter**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; fix any ruff finding in the file it names.

- [ ] **Step 5: Commit, push, open PR B**

```bash
git add src/vivado_runners/cli.py tests/test_cli.py
git commit -m "cli: run, cleanup, status, images list and activate"
git push -u origin controller
gh pr create --title "Controller: one throwaway VM per job" --body "The controller and its CLI, tested against fake GitHub and hypervisor objects. Not yet run against real libvirt or GitHub: that is Plan 2."
```

---

### Task 10: Host network policy

**Files:**
- Create: `host/network.xml`, `host/vivado-runners.nft`, `host/squid.conf`, `host/allowed-hosts`, `host/allowed-blob-regex`, `packaging/proxy-test.py`
- Modify: `.github/workflows/ci.yml` (add job `host-config`)
- Create: `tools/render_sample_domain.py`

**Interfaces:**
- Produces: the five files above, installed by Task 13 to `/usr/share/vivado-runners/host/` (network.xml, vivado-runners.nft) and `/etc/vivado-runners/` (squid.conf, allowed-hosts, allowed-blob-regex).
- Consumes: `domain_xml.render` (Task 5) for the schema check.

Why each rule exists:

- **libvirt network without `<forward>`** is an isolated network: libvirt adds no NAT and no route out. `<dns enable='no'/>` stops its dnsmasq answering DNS; it still serves DHCP, with one fixed lease per slot MAC and no default gateway. With no IPv6 `<ip>` element libvirt disables IPv6 on the bridge.
- **`<port isolated='yes'/>`** (in the domain XML) stops guests talking to each other at layer 2. **`clean-traffic`** stops a guest using another MAC or IP, so the proxy log's source address identifies the slot.
- **nftables table at priority -10** runs before docker's and libvirt's `filter` chains (priority 0). A `drop` is final whatever later chains say, so those tools cannot open a hole. The table accepts only DHCP and the proxy port from the bridge.
- **squid** allows `CONNECT` to port 443 for names on the allowlist only. IP literals are refused first: squid would otherwise reverse-resolve the address for `dstdomain`, and whoever owns an address controls its PTR record.

- [ ] **Step 1: Write the libvirt network**

`host/network.xml`:

```xml
<network>
  <name>vivado-runners</name>
  <bridge name='vrbr0' stp='off' delay='0'/>
  <dns enable='no'/>
  <ip address='192.168.76.1' netmask='255.255.255.0'>
    <dhcp>
      <host mac='52:54:00:76:00:00' ip='192.168.76.10'/>
      <host mac='52:54:00:76:00:01' ip='192.168.76.11'/>
      <host mac='52:54:00:76:00:02' ip='192.168.76.12'/>
      <host mac='52:54:00:76:00:03' ip='192.168.76.13'/>
      <host mac='52:54:00:76:00:04' ip='192.168.76.14'/>
      <host mac='52:54:00:76:00:05' ip='192.168.76.15'/>
      <host mac='52:54:00:76:00:06' ip='192.168.76.16'/>
      <host mac='52:54:00:76:00:07' ip='192.168.76.17'/>
    </dhcp>
  </ip>
</network>
```

- [ ] **Step 2: Write the nftables table**

`host/vivado-runners.nft`:

```
#!/usr/sbin/nft -f
# Runner VMs may reach DHCP and the egress proxy on this host, and nothing else.
# Loaded by vivado-runners-firewall.service and re-asserted every minute.
# Priority -10 runs before docker's and libvirt's filter chains; a drop is final.

table inet vivado_runners
delete table inet vivado_runners

table inet vivado_runners {
	chain input {
		type filter hook input priority -10; policy accept;
		iifname != "vrbr0" return
		meta nfproto ipv4 udp dport 67 accept
		ip saddr 192.168.76.0/24 ip daddr 192.168.76.1 tcp dport 3128 accept
		limit rate 10/second log prefix "vr-drop-in: "
		counter drop
	}

	chain forward {
		type filter hook forward priority -10; policy accept;
		iifname "vrbr0" limit rate 10/second log prefix "vr-drop-fwd: "
		iifname "vrbr0" counter drop
		oifname "vrbr0" counter drop
	}
}
```

- [ ] **Step 3: Write the squid configuration and allowlists**

`host/squid.conf`:

```
# Egress proxy for runner VMs: HTTPS CONNECT to GitHub and nothing else.
# A dedicated squid instance (vivado-runners-proxy.service), not the system one.

http_port 192.168.76.1:3128
pid_filename /run/vivado-runners-proxy/squid.pid
cache deny all
cache_log /var/log/vivado-runners/proxy-cache.log
logformat vr %tl %>a %Ss/%03>Hs %rm %ru
access_log daemon:/var/log/vivado-runners/proxy-access.log vr
coredump_dir /var/log/vivado-runners
shutdown_lifetime 1 seconds

acl runners src 192.168.76.0/24
acl CONNECT method CONNECT
acl https_port port 443
# An address instead of a name. Refused before any name rule: squid would
# reverse-resolve it, and the address's owner controls that answer.
acl ip_literal url_regex ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(:[0-9]+)?$ ^\[
acl github dstdomain "/etc/vivado-runners/allowed-hosts"
acl github_blob dstdom_regex "/etc/vivado-runners/allowed-blob-regex"

http_access deny !runners
http_access deny !CONNECT
http_access deny !https_port
http_access deny ip_literal
http_access allow github
http_access allow github_blob
http_access deny all
```

`host/allowed-hosts` (a leading dot matches the name and every subdomain; squid rejects a file that lists both a name and its parent with a dot):

```
# GitHub's self-hosted runner requirements (docs.github.com, read 2026-09-24).
github.com
api.github.com
codeload.github.com
.actions.githubusercontent.com
objects.githubusercontent.com
objects-origin.githubusercontent.com
github-releases.githubusercontent.com
release-assets.githubusercontent.com
```

`host/allowed-blob-regex`:

```
# Azure storage accounts GitHub uses for logs, artifacts and caches.
# INITIAL VALUE: every Azure storage account, which is far wider than GitHub.
# Plan 2 Task 6 replaces this line with the account names seen in proxy logs
# (decision D-1 if they cannot be narrowed).
\.blob\.core\.windows\.net$
```

- [ ] **Step 4: Write the sample-domain renderer for the schema check**

`tools/render_sample_domain.py`:

```python
"""Print the domain XML for a sample slot, for `virt-xml-validate` in CI."""

from pathlib import Path

from vivado_runners.domain_xml import DomainSpec, render

print(
    render(
        DomainSpec(
            name="vr-sample-0",
            vcpus=8,
            memory_gib=24,
            mac="52:54:00:76:00:00",
            ip="192.168.76.10",
            network="vivado-runners",
            overlay=Path("/var/lib/vivado-runners/slot-0/overlay.qcow2"),
            vivado=Path("/var/lib/vivado-runners/images/vivado-2025.2-2026-10-02.squashfs"),
            seed=Path("/var/lib/vivado-runners/slot-0/seed.iso"),
            scratch=Path("/var/lib/vivado-runners/slot-0/scratch.qcow2"),
            console_log=Path("/var/lib/vivado-runners/console/slot-0.log"),
            cpuset="0-21,44-65",
            numa_node=0,
        )
    )
)
```

- [ ] **Step 5: Write the proxy behaviour test**

`packaging/proxy-test.py`:

```python
#!/usr/bin/python3
"""Start squid with host/squid.conf and check what it lets through.

Run as root in a clean debian:trixie container with the repository at the
current directory. The only change made to the configuration is the address:
the proxy listens on, and accepts clients from, 127.0.0.1.
"""

import pathlib
import resource
import shutil
import subprocess
import sys
import time

ALLOWED = [
    "https://github.com/",
    "https://api.github.com/zen",
    "https://codeload.github.com/",
    "https://pipelines.actions.githubusercontent.com/",
]
REFUSED = [
    "https://pypi.org/simple/",
    "https://files.pythonhosted.org/",
    "https://example.com/",
    "https://evilgithub.com/",
    "https://github.com.example.com/",
    "https://140.82.112.3/",
    "https://[2606:50c0:8000::154]/",
    "https://github.com:8443/",
    "http://github.com/",
]
PROXY = "http://127.0.0.1:3128"
LOG = pathlib.Path("/var/log/vivado-runners/proxy-access.log")


def status(url: str) -> tuple[str, str]:
    out = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-m", "20", "-w", "%{http_connect} %{http_code}", "-x", PROXY, url],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    return out[0], out[1]


def main() -> int:
    etc = pathlib.Path("/etc/vivado-runners")
    etc.mkdir(parents=True, exist_ok=True)
    for name in ("allowed-hosts", "allowed-blob-regex"):
        shutil.copy2(f"host/{name}", etc / name)
    for directory in ("/var/log/vivado-runners", "/run/vivado-runners-proxy"):
        pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
        shutil.chown(directory, "proxy", "proxy")
    conf = pathlib.Path("host/squid.conf").read_text()
    for old, new in (("http_port 192.168.76.1:3128", "http_port 127.0.0.1:3128"),
                     ("acl runners src 192.168.76.0/24", "acl runners src 127.0.0.1/32")):  # fmt: skip
        if old not in conf:
            sys.exit(f"host/squid.conf no longer contains {old!r}; update this test")
        conf = conf.replace(old, new)
    pathlib.Path("/root/squid-test.conf").write_text(conf)

    # A container's file-descriptor limit can be ~1e9, and squid sizes a table by it.
    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))
    squid = subprocess.Popen(["squid", "--foreground", "-f", "/root/squid-test.conf"])
    time.sleep(5)
    if squid.poll() is not None:
        sys.exit(f"squid exited with {squid.returncode}")

    failed = 0
    try:
        for url in ALLOWED:
            connect, _ = status(url)
            ok = connect == "200"
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} allowed  {url} (CONNECT {connect})")
        for url in REFUSED:
            connect, http = status(url)
            ok = "403" in (connect, http) and "200" not in (connect, http)
            failed += not ok
            print(f"{'ok  ' if ok else 'FAIL'} refused  {url} (CONNECT {connect}, HTTP {http})")
    finally:
        squid.terminate()
        squid.wait(timeout=30)

    log = LOG.read_text()
    print(log)
    for needle in ("TCP_DENIED/403 CONNECT pypi.org:443", "127.0.0.1 TCP_TUNNEL/200 CONNECT github.com:443"):
        ok = needle in log
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} access log has: {needle}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

Run it:

```bash
docker run --rm -v "$PWD:/src:ro" -w /src debian:trixie sh -c \
  'apt-get update && apt-get install -y --no-install-recommends squid curl ca-certificates python3 && python3 packaging/proxy-test.py'
```

Expected: every line starts with `ok`, and the exit status is 0. (This exact script and configuration were run when the plan was written, 2026-10-02: 4 allowed, 9 refused, exit 0.)

- [ ] **Step 6: Add the CI job**

Append to `jobs:` in `.github/workflows/ci.yml`:

```yaml
  host-config:
    name: Host config syntax
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Install squid, nftables and the libvirt schemas
        run: sudo apt-get update && sudo apt-get install -y --no-install-recommends squid nftables libvirt-clients libvirt-daemon-driver-qemu
      - name: nftables table parses
        run: sudo nft -c -f host/vivado-runners.nft
      - name: squid configuration parses
        run: |
          sudo install -D -m 0644 host/allowed-hosts /etc/vivado-runners/allowed-hosts
          sudo install -D -m 0644 host/allowed-blob-regex /etc/vivado-runners/allowed-blob-regex
          sudo install -d -o proxy -g proxy /var/log/vivado-runners /run/vivado-runners-proxy
          sudo squid -k parse -f host/squid.conf
      - name: squid allows GitHub and refuses everything else
        run: >-
          docker run --rm -v "$PWD:/src:ro" -w /src debian:trixie sh -c
          'apt-get update && apt-get install -y --no-install-recommends squid curl ca-certificates python3 && python3 packaging/proxy-test.py'
      - name: libvirt network matches the schema
        run: virt-xml-validate host/network.xml network
      - name: domain XML matches the schema
        run: |
          mkdir -p tmp
          uv run python tools/render_sample_domain.py > tmp/domain.xml
          virt-xml-validate tmp/domain.xml domain
```

`squid -k parse` prints warnings to stderr and still exits 0. Read the job log: a line containing `WARNING` or `ERROR` (for example a name that is a subdomain of another entry) must be fixed in the file, not ignored.

- [ ] **Step 7: Commit, push, open PR C**

```bash
git add host packaging/proxy-test.py tools/render_sample_domain.py .github/workflows/ci.yml
git commit -m "host: isolated libvirt network, nftables table and squid allowlist"
git push -u origin host-config
gh pr create --title "Host network policy: libvirt network, nftables, squid allowlist" --body "Static configuration. CI checks the syntax of all of it and the behaviour of the squid allowlist (what it tunnels and what it refuses). What a real VM can reach through the bridge and the nftables table is proven in Plan 2 by the sandbox acceptance workflow, not here."
```

Expected: `host-config` job green. This proves the configuration parses and the proxy's allowlist behaves; it does not exercise the bridge or the nftables table. Say so in the PR.

---

### Task 11: The runner image

**Files:**
- Create: `image/versions.toml`, `image/build_image.py`, `image/provision.py`, `image/guest/vivado-runner-boot`, `image/guest/vivado-runner.service`
- Test: `tests/test_build_image.py`

**Interfaces:**
- Consumes: `images.next_base_name` (Task 3).
- Produces:
  - `image/build_image.py` CLI: `uv run python image/build_image.py --images-dir DIR --lock UV_LOCK --pyproject PYPROJECT [--work-dir DIR] [--network default]`. Writes `DIR/runner-base-<date>.<n>.qcow2` and prints its name. Does **not** change `runner-base-current`.
  - In the guest: `/etc/vivado-runner-image.json` with keys `built`, `runner_version`, `uv_version`, `python_version`, `lock_sha256`, `debian_image_sha512`.
  - Guest contract (Plan 3's workflows rely on it): user `runner` (no sudo), `uv` on `PATH`, CPython from `versions.toml`, `/opt/Xilinx` mounted read-only, work directory on the scratch disk, `HTTPS_PROXY`/`https_proxy` set, `UV_PYTHON_DOWNLOADS=never`, `UV_LINK_MODE=copy`.

How the build works: the Debian 13 `generic` cloud image (full kernel, so squashfs is available) is copied, grown to 20 GiB and booted once on libvirt's `default` NAT network with a cloud-init seed ISO. cloud-init runs `provision.py`, which installs everything and powers the VM off. The host reads the manifest out of the stopped image with `virt-cat` to confirm provisioning finished, then writes a compressed copy under its version name. This build VM is trusted (it runs our script, no job), so reading its disk is fine.

- [ ] **Step 1: Pin versions**

`image/versions.toml` (checksums read from the release pages on 2026-10-02):

```toml
[runner]
version = "2.337.0"
sha256 = "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"

[uv]
version = "0.12.10"
sha256 = "173d95a0c32d18c896c46ba6fafbf3cf9c14ab74b033f81b76c883ef492a976b"

[python]
version = "3.12"

[debian]
# The checksum is read from SHA512SUMS beside the image at build time and
# recorded in the image manifest.
base_url = "https://cloud.debian.org/images/cloud/trixie/latest"
image = "debian-13-generic-amd64.qcow2"
```

- [ ] **Step 2: Write the guest boot script**

`image/guest/vivado-runner-boot` (mode 0755):

```python
#!/usr/bin/python3
"""Run one GitHub Actions job, then let systemd power the machine off.

Disks are found by the serial the controller gives them:
  vr-vivado   squashfs of the Vivado install, mounted read-only at /opt/Xilinx
  vr-scratch  empty disk for the job's work directory
  vr-seed     ISO with `jitconfig` (single-use runner registration) and `proxy`
"""

import pathlib
import subprocess
import sys

RUNNER = pathlib.Path("/home/runner/actions-runner")
WORK = RUNNER / "_work"
SEED = pathlib.Path("/run/vr-seed")


def disk(serial: str) -> str:
    return f"/dev/disk/by-id/virtio-{serial}"


def sh(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    print(pathlib.Path("/etc/vivado-runner-image.json").read_text(), flush=True)

    sh("mount", "-t", "squashfs", "-o", "ro,nodev,nosuid", disk("vr-vivado"), "/opt/Xilinx")

    sh("mkfs.ext4", "-q", "-F", "-E", "lazy_itable_init=1,lazy_journal_init=1", disk("vr-scratch"))
    WORK.mkdir(exist_ok=True)
    sh("mount", "-o", "nodev,nosuid", disk("vr-scratch"), str(WORK))
    sh("chown", "runner:runner", str(WORK))

    SEED.mkdir(exist_ok=True)
    sh("mount", "-o", "ro", disk("vr-seed"), str(SEED))
    jitconfig = (SEED / "jitconfig").read_text().strip()
    proxy = (SEED / "proxy").read_text().strip()
    sh("umount", str(SEED))

    env = {
        "HOME": "/home/runner",
        "USER": "runner",
        "LOGNAME": "runner",
        "PATH": "/home/runner/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "https_proxy": proxy,
        "http_proxy": proxy,
        "HTTPS_PROXY": proxy,
        "HTTP_PROXY": proxy,
        "UV_LINK_MODE": "copy",
        "UV_PYTHON_DOWNLOADS": "never",
    }
    result = subprocess.run(
        [str(RUNNER / "run.sh"), "--jitconfig", jitconfig],
        cwd=RUNNER,
        env=env,
        user="runner",
        group="runner",
        extra_groups=[],
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
```

`image/guest/vivado-runner.service`:

```ini
[Unit]
Description=Run one GitHub Actions job, then power off
After=network-online.target
Wants=network-online.target
SuccessAction=poweroff
FailureAction=poweroff

[Service]
Type=exec
ExecStart=/usr/local/sbin/vivado-runner-boot
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write the provisioning script**

`image/provision.py`:

```python
#!/usr/bin/python3
"""Provision the runner image. Runs once, as root, inside the build VM.

cloud-init mounts the seed ISO at /mnt/payload and starts this script. It ends
by writing /etc/vivado-runner-image.json; the host treats a missing manifest as
a failed build.
"""

import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request

PAYLOAD = pathlib.Path("/mnt/payload")
VERSIONS = tomllib.loads((PAYLOAD / "versions.toml").read_text())
RUNNER_HOME = pathlib.Path("/home/runner/actions-runner")

APT_PACKAGES = [
    "ca-certificates", "git", "make", "xz-utils", "e2fsprogs",
    "gcc-riscv64-unknown-elf", "picolibc-riscv64-unknown-elf",
    "locales",
    # What Vivado's batch mode links against on a headless Debian 13.
    # Plan 2 Task 4 runs Vivado in the image and adds anything it reports missing.
    "libx11-6", "libxext6", "libxrender1", "libxtst6", "libxi6",
    "libfreetype6", "fontconfig", "libncurses6", "libtinfo6",
]  # fmt: skip


def sh(*cmd: str, **kwargs) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def as_runner(*cmd: str, cwd: str = "/home/runner") -> None:
    env = {
        "HOME": "/home/runner",
        "USER": "runner",
        "PATH": "/home/runner/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "UV_LINK_MODE": "copy",
    }
    print("+ (runner)", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=cwd, env=env, user="runner", group="runner", extra_groups=[])


def fetch(url: str, sha256: str, dest: pathlib.Path) -> None:
    print("+ fetch", url, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != sha256:
        raise SystemExit(f"{url}: sha256 {digest}, expected {sha256}")


def packages() -> None:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    sh("apt-get", "update", env=env)
    sh("apt-get", "install", "-y", "--no-install-recommends", *APT_PACKAGES, env=env)
    pathlib.Path("/etc/locale.gen").write_text("en_US.UTF-8 UTF-8\n")
    sh("locale-gen")


def runner() -> None:
    sh("useradd", "--create-home", "--shell", "/bin/bash", "runner")
    version = VERSIONS["runner"]["version"]
    tarball = pathlib.Path("/root/actions-runner.tar.gz")
    fetch(
        f"https://github.com/actions/runner/releases/download/v{version}/actions-runner-linux-x64-{version}.tar.gz",
        VERSIONS["runner"]["sha256"],
        tarball,
    )
    RUNNER_HOME.mkdir(parents=True)
    with tarfile.open(tarball) as tar:
        tar.extractall(RUNNER_HOME, filter="tar")
    tarball.unlink()
    sh(str(RUNNER_HOME / "bin" / "installdependencies.sh"), env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    sh("chown", "-R", "runner:runner", "/home/runner")


def uv_and_python() -> None:
    version = VERSIONS["uv"]["version"]
    tarball = pathlib.Path("/root/uv.tar.gz")
    fetch(
        f"https://github.com/astral-sh/uv/releases/download/{version}/uv-x86_64-unknown-linux-gnu.tar.gz",
        VERSIONS["uv"]["sha256"],
        tarball,
    )
    with tarfile.open(tarball) as tar:
        tar.extractall("/root/uv-unpack", filter="tar")
    for name in ("uv", "uvx"):
        shutil.copy2(f"/root/uv-unpack/uv-x86_64-unknown-linux-gnu/{name}", f"/usr/local/bin/{name}")
    shutil.rmtree("/root/uv-unpack")
    tarball.unlink()
    as_runner("uv", "python", "install", VERSIONS["python"]["version"])


def warm_uv_cache() -> str:
    """Fill the uv cache from the lock, then prove a sync needs no network."""
    python = VERSIONS["python"]["version"]
    for name in ("warm", "prove"):
        project = pathlib.Path(f"/home/runner/cache-{name}")
        project.mkdir()
        for file in ("pyproject.toml", "uv.lock"):
            shutil.copy2(PAYLOAD / file, project / file)
        sh("chown", "-R", "runner:runner", str(project))
    sync = ["uv", "sync", "--frozen", "--extra", "build", "--no-install-project", "--python", python]
    as_runner(*sync, cwd="/home/runner/cache-warm")
    # A fresh project directory, same cache, no network: fails if any locked
    # distribution or build requirement is missing from the cache.
    as_runner(*sync, "--offline", cwd="/home/runner/cache-prove")
    shutil.rmtree("/home/runner/cache-warm")
    shutil.rmtree("/home/runner/cache-prove")
    return hashlib.sha256((PAYLOAD / "uv.lock").read_bytes()).hexdigest()


def guest_files() -> None:
    shutil.copy2(PAYLOAD / "vivado-runner-boot", "/usr/local/sbin/vivado-runner-boot")
    os.chmod("/usr/local/sbin/vivado-runner-boot", 0o755)
    shutil.copy2(PAYLOAD / "vivado-runner.service", "/etc/systemd/system/vivado-runner.service")
    pathlib.Path("/opt/Xilinx").mkdir(parents=True, exist_ok=True)
    sh("systemctl", "enable", "vivado-runner.service")


def network() -> None:
    """DHCP on whatever NIC the VM has (the MAC differs per slot); no IPv6."""
    for old in pathlib.Path("/etc/netplan").glob("*"):
        old.unlink()
    for old in pathlib.Path("/etc/systemd/network").glob("*"):
        old.unlink()
    pathlib.Path("/etc/systemd/network/10-runner.network").write_text(
        "[Match]\nType=ether\n\n[Network]\nDHCP=ipv4\nIPv6AcceptRA=no\nLinkLocalAddressing=no\n"
    )
    pathlib.Path("/etc/sysctl.d/90-no-ipv6.conf").write_text(
        "net.ipv6.conf.all.disable_ipv6 = 1\nnet.ipv6.conf.default.disable_ipv6 = 1\n"
    )
    sh("systemctl", "enable", "systemd-networkd.service")


def lock_down() -> None:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    sh("apt-get", "purge", "-y", "openssh-server", "sudo", env=env)
    sh("apt-get", "autoremove", "-y", "--purge", env=env)
    sh("apt-get", "clean")
    pathlib.Path("/etc/cloud/cloud-init.disabled").touch()
    sh("passwd", "--lock", "root")


def main() -> None:
    packages()
    runner()
    uv_and_python()
    lock_sha256 = warm_uv_cache()
    guest_files()
    network()
    lock_down()
    manifest = {
        "built": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "runner_version": VERSIONS["runner"]["version"],
        "uv_version": VERSIONS["uv"]["version"],
        "python_version": VERSIONS["python"]["version"],
        "lock_sha256": lock_sha256,
        "debian_image_sha512": (PAYLOAD / "debian-image.sha512").read_text().strip(),
    }
    pathlib.Path("/etc/vivado-runner-image.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the failing tests for the host-side build script**

`tests/test_build_image.py`:

```python
import importlib.util
import pathlib

import pytest

SPEC = importlib.util.spec_from_file_location(
    "build_image", pathlib.Path(__file__).parents[1] / "image" / "build_image.py"
)
build_image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_image)


def test_user_data_runs_provision_from_the_seed_and_powers_off():
    text = build_image.user_data()
    assert text.startswith("#cloud-config\n")
    assert "mount -o ro /dev/disk/by-label/cidata /mnt/payload" in text
    assert "python3 /mnt/payload/provision.py" in text
    assert "mode: poweroff" in text
    assert "condition: true" in text


def test_expected_sha512_reads_the_right_line():
    sums = "aaa  debian-13-genericcloud-amd64.qcow2\nbbb  debian-13-generic-amd64.qcow2\n"
    assert build_image.expected_sha512(sums, "debian-13-generic-amd64.qcow2") == "bbb"
    with pytest.raises(SystemExit, match="not listed"):
        build_image.expected_sha512(sums, "missing.qcow2")


def test_payload_lists_every_file_provision_reads(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("lock")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\n")
    seed = tmp_path / "seed"
    build_image.write_seed(seed, lock, pyproject, "bbb")
    assert sorted(p.name for p in seed.iterdir()) == [
        "debian-image.sha512",
        "meta-data",
        "provision.py",
        "pyproject.toml",
        "user-data",
        "uv.lock",
        "versions.toml",
        "vivado-runner-boot",
        "vivado-runner.service",
    ]
    assert (seed / "debian-image.sha512").read_text() == "bbb\n"
    assert (seed / "uv.lock").read_text() == "lock"
```

Run: `uv run pytest tests/test_build_image.py -v`
Expected: FAIL, `No such file or directory: .../image/build_image.py`.

- [ ] **Step 5: Implement the host-side build script**

`image/build_image.py`:

```python
#!/usr/bin/env python3
"""Build a versioned runner base image.

    uv run python image/build_image.py \\
        --images-dir /var/lib/vivado-runners/images \\
        --lock ~/fpgas.online-test-designs/uv.lock \\
        --pyproject ~/fpgas.online-test-designs/pyproject.toml

Boots Debian's cloud image once on a network WITH internet access (libvirt's
`default`), lets cloud-init run image/provision.py, and stores the result as
runner-base-<date>.<n>.qcow2. It never touches runner-base-current: select the
new image with `vivado-runners images activate base <name>` once it is tested.

Needs: qemu-utils, xorriso, virtinst, libguestfs-tools, a libvirt `default`
network, and membership of the `libvirt` group.
"""

import argparse
import datetime
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tomllib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from vivado_runners import images  # noqa: E402

VERSIONS = tomllib.loads((HERE / "versions.toml").read_text())
MANIFEST = "/etc/vivado-runner-image.json"
DOMAIN = "vr-image-build"


def sh(*cmd: str) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def user_data() -> str:
    return (
        "#cloud-config\n"
        "runcmd:\n"
        "  - mkdir -p /mnt/payload\n"
        "  - mount -o ro /dev/disk/by-label/cidata /mnt/payload\n"
        "  - python3 /mnt/payload/provision.py\n"
        "power_state:\n"
        "  mode: poweroff\n"
        "  condition: true\n"
    )


def expected_sha512(sums: str, name: str) -> str:
    for line in sums.splitlines():
        digest, _, listed = line.partition("  ")
        if listed == name:
            return digest
    raise SystemExit(f"{name} is not listed in SHA512SUMS")


def write_seed(seed: pathlib.Path, lock: pathlib.Path, pyproject: pathlib.Path, image_sha512: str) -> None:
    seed.mkdir(parents=True)
    (seed / "user-data").write_text(user_data())
    (seed / "meta-data").write_text(f"instance-id: {DOMAIN}\nlocal-hostname: vivado-runner\n")
    (seed / "debian-image.sha512").write_text(image_sha512 + "\n")
    shutil.copy2(lock, seed / "uv.lock")
    shutil.copy2(pyproject, seed / "pyproject.toml")
    for name in ("versions.toml", "provision.py"):
        shutil.copy2(HERE / name, seed / name)
    for name in ("vivado-runner-boot", "vivado-runner.service"):
        shutil.copy2(HERE / "guest" / name, seed / name)


def download(work: pathlib.Path) -> tuple[pathlib.Path, str]:
    base_url, name = VERSIONS["debian"]["base_url"], VERSIONS["debian"]["image"]
    with urllib.request.urlopen(f"{base_url}/SHA512SUMS", timeout=60) as response:
        want = expected_sha512(response.read().decode(), name)
    dest = work / name
    print("+ fetch", f"{base_url}/{name}", flush=True)
    with urllib.request.urlopen(f"{base_url}/{name}", timeout=600) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)
    digest = hashlib.sha512()
    with open(dest, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != want:
        raise SystemExit(f"{name}: sha512 {digest.hexdigest()}, expected {want}")
    return dest, want


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images-dir", type=pathlib.Path, required=True)
    parser.add_argument("--lock", type=pathlib.Path, required=True, help="uv.lock of fpgas.online-test-designs main")
    parser.add_argument("--pyproject", type=pathlib.Path, required=True)
    parser.add_argument("--work-dir", type=pathlib.Path, default=None, help="default: <images-dir>/../build")
    parser.add_argument("--network", default="default", help="libvirt network with internet access")
    parser.add_argument("--disk-gib", type=int, default=20)
    args = parser.parse_args()

    work = args.work_dir or args.images_dir.parent / "build"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    cloud_image, image_sha512 = download(work)
    disk = work / "work.qcow2"
    sh("qemu-img", "convert", "-O", "qcow2", str(cloud_image), str(disk))
    sh("qemu-img", "resize", str(disk), f"{args.disk_gib}G")

    write_seed(work / "seed", args.lock, args.pyproject, image_sha512)
    seed_iso = work / "seed.iso"
    sh("xorriso", "-as", "mkisofs", "-quiet", "-r", "-J", "-V", "cidata", "-o", str(seed_iso), str(work / "seed"))

    sh(
        "virt-install", "--connect", "qemu:///system", "--name", DOMAIN, "--transient",
        "--memory", "8192", "--vcpus", "4", "--import", "--osinfo", "debian13",
        "--disk", f"path={disk},format=qcow2,bus=virtio",
        "--disk", f"path={seed_iso},device=cdrom",
        "--network", f"network={args.network},model=virtio",
        "--graphics", "none", "--noautoconsole", "--wait", "60",
    )  # fmt: skip

    manifest = subprocess.run(["virt-cat", "-a", str(disk), MANIFEST], capture_output=True, text=True, check=False)
    if manifest.returncode != 0:
        print(manifest.stderr, file=sys.stderr)
        raise SystemExit(f"provisioning did not finish: {MANIFEST} is missing from the image. Disk kept at {disk}")
    print(manifest.stdout)

    today = datetime.date.today().isoformat()
    name = images.next_base_name(args.images_dir, today)
    final = args.images_dir / name
    sh("qemu-img", "convert", "-c", "-O", "qcow2", str(disk), str(final))
    final.chmod(0o440)
    shutil.rmtree(work)
    print(f"built {name}")
    print(f"select it with: vivado-runners images activate base {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_build_image.py -v && uv run ruff check image tests`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
chmod +x image/guest/vivado-runner-boot
git add image tests/test_build_image.py
git commit -m "image: build script, provisioning and the one-job guest unit"
```

---

### Task 12: The Vivado disk

**Files:**
- Create: `image/build_vivado_disk.py`
- Test: `tests/test_build_vivado_disk.py`

**Interfaces:**
- Produces: `uv run python image/build_vivado_disk.py --source /opt/Xilinx/2025.2 --images-dir DIR [--exclude REL ...]`. Writes `DIR/vivado-<version>-<date>.squashfs` whose root contains one directory, `<version>/`, so mounting it at `/opt/Xilinx` gives `/opt/Xilinx/2025.2/Vivado/settings64.sh`. Does not change `vivado-current`.
- `command(source, dest, excludes) -> list[str]` and `output_name(source, date) -> str` for the tests.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_vivado_disk.py`:

```python
import importlib.util
import pathlib

SPEC = importlib.util.spec_from_file_location(
    "build_vivado_disk", pathlib.Path(__file__).parents[1] / "image" / "build_vivado_disk.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_output_name_carries_version_and_date():
    assert mod.output_name(pathlib.Path("/opt/Xilinx/2025.2"), "2026-10-02") == "vivado-2025.2-2026-10-02.squashfs"


def test_command_keeps_the_version_directory_and_owns_everything_as_root():
    cmd = mod.command(pathlib.Path("/opt/Xilinx/2025.2"), pathlib.Path("/i/out.squashfs"), [])
    assert cmd[:3] == ["mksquashfs", "/opt/Xilinx/2025.2", "/i/out.squashfs"]
    assert "-keep-as-directory" in cmd
    assert "-all-root" in cmd
    assert cmd[cmd.index("-comp") + 1] == "zstd"
    assert "-e" not in cmd


def test_excludes_are_relative_to_the_squashfs_root():
    cmd = mod.command(pathlib.Path("/opt/Xilinx/2025.2"), pathlib.Path("/i/out.squashfs"), ["Vitis", "data/xsim"])
    assert cmd[-3:] == ["-e", "2025.2/Vitis", "2025.2/data/xsim"]
```

Run: `uv run pytest tests/test_build_vivado_disk.py -v`
Expected: FAIL, file not found.

- [ ] **Step 2: Implement**

`image/build_vivado_disk.py`:

```python
#!/usr/bin/env python3
"""Pack a Vivado install into a versioned, read-only squashfs disk.

    uv run python image/build_vivado_disk.py --source /opt/Xilinx/2025.2 \\
        --images-dir /var/lib/vivado-runners/images

The result stays on the runner hosts. Never upload it: AMD's licence allows
installing Vivado, not redistributing it. It never touches vivado-current:
select the new disk with `vivado-runners images activate vivado <name>`.
"""

import argparse
import datetime
import pathlib
import subprocess
import sys


def output_name(source: pathlib.Path, date: str) -> str:
    return f"vivado-{source.name}-{date}.squashfs"


def command(source: pathlib.Path, dest: pathlib.Path, excludes: list[str]) -> list[str]:
    cmd = [
        "mksquashfs", str(source), str(dest),
        "-keep-as-directory", "-all-root", "-no-xattrs", "-noappend",
        "-comp", "zstd", "-Xcompression-level", "15", "-b", "1M",
    ]  # fmt: skip
    if excludes:
        cmd += ["-e", *[f"{source.name}/{rel}" for rel in excludes]]
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=pathlib.Path, required=True, help="e.g. /opt/Xilinx/2025.2")
    parser.add_argument("--images-dir", type=pathlib.Path, required=True)
    parser.add_argument("--exclude", action="append", default=[], help="path relative to --source; repeatable")
    args = parser.parse_args()

    if not (args.source / "Vivado" / "settings64.sh").is_file():
        raise SystemExit(f"{args.source} is not a Vivado install: Vivado/settings64.sh is missing")
    dest = args.images_dir / output_name(args.source, datetime.date.today().isoformat())
    if dest.exists():
        raise SystemExit(f"{dest} already exists; images are never overwritten")

    cmd = command(args.source, dest, args.exclude)
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    dest.chmod(0o440)
    print(f"built {dest.name} ({dest.stat().st_size / 2**30:.1f} GiB)")
    print(f"select it with: vivado-runners images activate vivado {dest.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_build_vivado_disk.py -v`
Expected: all pass.

- [ ] **Step 4: Commit, push, open PR D**

```bash
git add image/build_vivado_disk.py tests/test_build_vivado_disk.py
git commit -m "image: pack a Vivado install into a versioned squashfs disk"
git push -u origin image-build
gh pr create --title "Image build: runner base image and Vivado disk" --body "Build scripts with unit tests for their command construction. Neither script has been run against a hypervisor or a real Vivado install yet: Plan 1 Task 14 runs the Vivado disk build on desktop.buddy, and Plan 2 runs the image build on big-storage."
```

---

### Task 13: Debian package

**Files:**
- Create: `debian/control`, `debian/rules`, `debian/copyright`, `debian/source/format`, `debian/vivado-runners.install`, `debian/vivado-runners.dirs`, `debian/vivado-runners.postinst`, `debian/vivado-runners.vivado-runners.service`, `debian/vivado-runners.vivado-runners-proxy.service`, `debian/vivado-runners.vivado-runners-firewall.service`, `debian/vivado-runners.vivado-runners-firewall.timer`, `debian/config.toml.example`
- Create: `.github/workflows/deb.yml`, `.github/apt-packaging.toml`, `packaging/install-test.py`

**Interfaces:**
- Produces: package `vivado-runners` (Architecture: all). Installed paths:
  - `/usr/bin/vivado-runners`
  - `/usr/share/vivado-runners/host/{network.xml,vivado-runners.nft}`
  - `/usr/share/vivado-runners/image/` (everything under `image/`)
  - `/etc/vivado-runners/{squid.conf,allowed-hosts,allowed-blob-regex}` (conffiles)
  - `/usr/share/doc/vivado-runners/config.toml.example`
  - units `vivado-runners.service`, `vivado-runners-proxy.service`, `vivado-runners-firewall.service`, `vivado-runners-firewall.timer`, all installed **disabled and stopped** (Plan 2 enables them once the config and key exist)
  - user `vivado-runners` in groups `libvirt` and `libvirt-qemu`; directories `/var/lib/vivado-runners/{images,status,console}` and `/var/log/vivado-runners`

- [ ] **Step 1: Write the packaging files**

`debian/source/format`:

```
3.0 (native)
```

`debian/control`:

```
Source: vivado-runners
Section: admin
Priority: optional
Maintainer: Tim 'mithro' Ansell <me@mith.ro>
Build-Depends: debhelper-compat (= 13), dh-python, pybuild-plugin-pyproject,
 python3-all, python3-hatchling
Standards-Version: 4.6.2
Homepage: https://github.com/fpgas-online/fpgas.online-vivado-runners
Vcs-Git: https://github.com/fpgas-online/fpgas.online-vivado-runners.git
Vcs-Browser: https://github.com/fpgas-online/fpgas.online-vivado-runners
Rules-Requires-Root: no

Package: vivado-runners
Architecture: all
Depends: ${python3:Depends}, ${misc:Depends}, python3-jwt, python3-cryptography,
 adduser, libvirt-daemon-system, libvirt-clients, qemu-system-x86, qemu-utils,
 xorriso, squid, nftables
Recommends: virtinst, libguestfs-tools, squashfs-tools
Description: sandboxed per-job KVM GitHub Actions runners with Vivado
 A controller that keeps a fixed number of GitHub Actions runner slots. Each
 job runs in a fresh KVM virtual machine that is destroyed afterwards. The
 machine gets a single-use runner registration and can reach GitHub, through
 an allowlisting proxy on the host, and nothing else.
 .
 The package also carries the host network policy (libvirt network, nftables
 table, squid allowlist) and the scripts that build the VM image and the
 read-only Vivado disk. Vivado itself is not included.
```

`debian/rules`:

```make
#!/usr/bin/make -f

export PYBUILD_NAME=vivado-runners

%:
	dh $@ --with python3 --buildsystem=pybuild

# The unit tests run in CI (ci.yml) with uv; the package build does not repeat them.
override_dh_auto_test:

# Installed disabled and stopped: the controller needs a config file and the
# GitHub App key, and the proxy needs the bridge. Deployment enables them.
# One call per unit name; each also picks up a .timer of the same name.
override_dh_installsystemd:
	dh_installsystemd --name=vivado-runners --no-enable --no-start
	dh_installsystemd --name=vivado-runners-proxy --no-enable --no-start
	dh_installsystemd --name=vivado-runners-firewall --no-enable --no-start
	dh_installsystemd --name=vivado-runners-firewall-assert --no-enable --no-start
```

`debian/copyright`:

```
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: vivado-runners
Source: https://github.com/fpgas-online/fpgas.online-vivado-runners

Files: *
Copyright: 2026 The fpgas.online authors
License: Apache-2.0
 On Debian systems, the full text of the Apache License, Version 2.0 is in
 /usr/share/common-licenses/Apache-2.0.
```

`debian/vivado-runners.install`:

```
host/network.xml           usr/share/vivado-runners/host
host/vivado-runners.nft    usr/share/vivado-runners/host
host/squid.conf            etc/vivado-runners
host/allowed-hosts         etc/vivado-runners
host/allowed-blob-regex    etc/vivado-runners
image/*                    usr/share/vivado-runners/image
debian/config.toml.example usr/share/doc/vivado-runners
```

`debian/vivado-runners.dirs`:

```
var/lib/vivado-runners/images
var/lib/vivado-runners/status
var/lib/vivado-runners/console
var/log/vivado-runners
```

`debian/config.toml.example`:

```toml
# /etc/vivado-runners/config.toml
# host defaults to this machine's short hostname.

[github]
org = "fpgas-online"
app_id = 0
installation_id = 0
key_file = "/etc/vivado-runners/app.pem"
runner_group = "vivado"

[slots]
count = 4
vcpus = 8
memory_gib = 24
scratch_gib = 60
wall_limit_minutes = 120
labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]
# One NUMA node per slot; omit on single-socket hosts.
numa_nodes = [0, 0, 1, 1]
```

`debian/vivado-runners.postinst`:

```sh
#!/bin/sh
set -e

if [ "$1" = configure ]; then
    adduser --system --group --home /var/lib/vivado-runners --no-create-home vivado-runners
    adduser vivado-runners libvirt
    adduser vivado-runners libvirt-qemu
    chown vivado-runners:libvirt-qemu /var/lib/vivado-runners /var/lib/vivado-runners/images
    chown vivado-runners:vivado-runners /var/lib/vivado-runners/status /var/lib/vivado-runners/console
    chmod 0750 /var/lib/vivado-runners/images
    chmod 0755 /var/lib/vivado-runners
    chown proxy:proxy /var/log/vivado-runners
fi

#DEBHELPER#
```

`debian/vivado-runners.vivado-runners.service`:

```ini
[Unit]
Description=Vivado runner controller (one KVM VM per GitHub Actions job)
Documentation=https://github.com/fpgas-online/fpgas.online-vivado-runners
After=network-online.target libvirtd.service vivado-runners-firewall.service vivado-runners-proxy.service
Wants=network-online.target
Requires=vivado-runners-firewall.service vivado-runners-proxy.service
ConditionPathExists=/etc/vivado-runners/config.toml

[Service]
User=vivado-runners
Group=vivado-runners
ExecStart=/usr/bin/vivado-runners run
Restart=on-failure
RestartSec=300
TimeoutStopSec=90
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/vivado-runners
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

`debian/vivado-runners.vivado-runners-proxy.service`:

```ini
[Unit]
Description=Egress proxy for Vivado runner VMs (GitHub only)
After=network-online.target libvirtd.service
Wants=network-online.target

[Service]
Type=exec
RuntimeDirectory=vivado-runners-proxy
RuntimeDirectoryMode=0755
ExecStartPre=/usr/bin/chown proxy:proxy /run/vivado-runners-proxy
ExecStartPre=/usr/sbin/squid -k parse -f /etc/vivado-runners/squid.conf
ExecStart=/usr/sbin/squid --foreground -f /etc/vivado-runners/squid.conf
ExecReload=/usr/sbin/squid -k reconfigure -f /etc/vivado-runners/squid.conf
LimitNOFILE=16384
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`debian/vivado-runners.vivado-runners-firewall.service`:

```ini
[Unit]
Description=nftables table confining Vivado runner VMs
Before=vivado-runners.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /usr/share/vivado-runners/host/vivado-runners.nft
ExecReload=/usr/sbin/nft -f /usr/share/vivado-runners/host/vivado-runners.nft
ExecStop=/usr/sbin/nft delete table inet vivado_runners

[Install]
WantedBy=multi-user.target
```

`debian/vivado-runners.vivado-runners-firewall.timer`:

```ini
[Unit]
Description=Re-assert the Vivado runner nftables table every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=vivado-runners-firewall-assert.service

[Install]
WantedBy=timers.target
```

`debian/vivado-runners.vivado-runners-firewall-assert.service` (what the timer runs; a separate unit because the main one stays "active" after its first run and would not run again):

```ini
[Unit]
Description=Reload the Vivado runner nftables table (another tool may have flushed it)

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /usr/share/vivado-runners/host/vivado-runners.nft
```

The `.nft` file begins by declaring and deleting its own table, so loading it again replaces the table in one transaction.

- [ ] **Step 2: Write the install test**

`packaging/install-test.py`:

```python
#!/usr/bin/python3
"""Install the built deb in a clean container and check what it promises."""

import glob
import grp
import os
import pwd
import stat
import subprocess
import sys

ENV = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}


def sh(*cmd: str) -> str:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, capture_output=True, text=True, env=ENV).stdout


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message, flush=True)
    if not condition:
        sys.exit(1)


sh("apt-get", "update")
sh("apt-get", "install", "-y", "--no-install-recommends", *glob.glob("/debs/vivado-runners_*.deb"))

check("usage: vivado-runners" in sh("vivado-runners", "--help"), "the CLI runs")

user = pwd.getpwnam("vivado-runners")
groups = {g.gr_name for g in grp.getgrall() if "vivado-runners" in g.gr_mem}
check({"libvirt", "libvirt-qemu"} <= groups, f"user is in libvirt and libvirt-qemu (has {sorted(groups)})")

images = os.stat("/var/lib/vivado-runners/images")
check(stat.S_IMODE(images.st_mode) == 0o750, "images directory is 0750")
check(images.st_uid == user.pw_uid, "images directory belongs to the controller")
check(grp.getgrgid(images.st_gid).gr_name == "libvirt-qemu", "images directory group is libvirt-qemu")

for path in (
    "/usr/share/vivado-runners/host/network.xml",
    "/usr/share/vivado-runners/host/vivado-runners.nft",
    "/usr/share/vivado-runners/image/build_image.py",
    "/usr/share/vivado-runners/image/guest/vivado-runner-boot",
    "/etc/vivado-runners/squid.conf",
    "/etc/vivado-runners/allowed-hosts",
    "/etc/vivado-runners/allowed-blob-regex",
):
    check(os.path.isfile(path), f"{path} is installed")

for unit in ("vivado-runners.service", "vivado-runners-proxy.service", "vivado-runners-firewall.service",
             "vivado-runners-firewall.timer", "vivado-runners-firewall-assert.service"):  # fmt: skip
    check(os.path.isfile(f"/usr/lib/systemd/system/{unit}"), f"{unit} is installed")
    enabled = glob.glob(f"/etc/systemd/system/*.wants/{unit}")
    check(not enabled, f"{unit} is not enabled by the package")

sh("squid", "-k", "parse", "-f", "/etc/vivado-runners/squid.conf")
check(True, "the installed squid configuration parses")
print("install test passed")
```

- [ ] **Step 3: Add the package workflow**

`.github/apt-packaging.toml`:

```toml
# How this repository is packaged, and why it differs from the defaults.
# See https://github.com/mithro/apt-repo-action/blob/main/docs/packaging.md

kind = "B"                  # our own code: debian/ at the root of main
architectures = "all"       # Python and configuration only
suites = ["trixie"]         # the runner hosts are Debian 13

[exceptions]
PKG-SUITES = "only the two runner hosts install it, both on trixie"
```

`.github/workflows/deb.yml`:

```yaml
name: Debian package

# Every push to main builds the package and republishes a signed apt repository
# on GitHub Pages. A pull request builds and install-tests, and publishes nothing.
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: deb-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  build-deb:
    name: build-deb (trixie all)
    runs-on: ubuntu-24.04
    steps:
      - name: Check out
        uses: actions/checkout@v5
        with:
          fetch-depth: 0  # the version is git describe's

      - name: Build
        uses: mithro/apt-repo-action/build-deb@main
        with:
          suite: trixie
          arch: all

      - name: Install test
        run: |
          docker run --rm \
            -v "${PWD}/built-debs:/debs:ro" -v "${PWD}/packaging:/packaging:ro" \
            docker.io/library/debian:trixie \
            sh -c 'apt-get update && apt-get install -y --no-install-recommends python3 && python3 /packaging/install-test.py'

      - name: Upload
        uses: actions/upload-artifact@v4
        with:
          name: debs-trixie-all
          path: built-debs/*.deb
          retention-days: 14

  publish-apt:
    if: github.event_name != 'pull_request' && github.ref_name == github.event.repository.default_branch
    needs: build-deb
    permissions:
      contents: read
      pages: write
      id-token: write
    uses: mithro/apt-repo-action/.github/workflows/publish-apt.yml@main
    with:
      suites: "trixie"
      architectures: "all"
      description: "Sandboxed per-job KVM GitHub Actions runners with Vivado"
    secrets:
      gpg-private-key: ${{ secrets.APT_GPG_PRIVATE_KEY }}
```

`publish-apt` needs the `APT_GPG_PRIVATE_KEY` secret and GitHub Pages enabled on the repo. Both are Tim's to set (see `apt-repo-standardisation` in the project notes). Until then the publish job fails on `main` while PR builds stay green; say so in the PR.

- [ ] **Step 4: Build and install-test locally**

Run:

```bash
docker run --rm -v "$PWD:/src" -w /src debian:trixie sh -c \
  'apt-get update && apt-get install -y --no-install-recommends build-essential devscripts equivs git && mk-build-deps -i -t "apt-get -y --no-install-recommends" debian/control && printf "vivado-runners (0.1.0~local) trixie; urgency=medium\n\n  * Local build.\n\n -- Local <local@example.invalid>  Fri, 02 Oct 2026 00:00:00 +0000\n" > debian/changelog && dpkg-buildpackage -us -uc -b && mkdir -p built-debs && mv ../vivado-runners_*.deb built-debs/'
docker run --rm -v "$PWD/built-debs:/debs:ro" -v "$PWD/packaging:/packaging:ro" debian:trixie sh -c \
  'apt-get update && apt-get install -y --no-install-recommends python3 && python3 /packaging/install-test.py'
```

Expected: the first command ends with `dpkg-deb: building package 'vivado-runners'`; the second ends with `install test passed`. Remove `debian/changelog` afterwards (CI generates it; it must not be committed).

- [ ] **Step 5: Commit, push, open PR E**

```bash
rm -f debian/changelog
git add debian packaging .github/workflows/deb.yml .github/apt-packaging.toml
git commit -m "packaging: deb with the controller, host policy and image scripts"
git push -u origin packaging
gh pr create --title "Debian package" --body "Builds and install-tests in a clean debian:trixie container. Units ship disabled. Publishing needs APT_GPG_PRIVATE_KEY and Pages, which Tim has to set."
```

---

### Task 14: Measurements (spec Phase 0)

Run on desktop.buddy (this is where Vivado 2025.2 is installed). No hypervisor is needed.

**Files:**
- Create: `tools/allowlist_proxy.py`, `docs/measurements.md`
- Modify: `debian/config.toml.example` (slot sizes), spec section "Vivado disk" (measured size), `image/provision.py` only if the uv experiment says so

**Interfaces:**
- Produces: `docs/measurements.md` with three filled sections: "Vivado peak memory", "Vivado disk size", "uv without PyPI". Plan 2 reads the slot `memory_gib` from it.

- [ ] **Step 1: Write the logging proxy used by the uv experiment**

`tools/allowlist_proxy.py`:

```python
#!/usr/bin/env python3
"""A logging CONNECT proxy for experiments. NOT the production proxy (that is squid).

    uv run python tools/allowlist_proxy.py --port 8876 --allow github.com \\
        --allow .githubusercontent.com --log tmp/proxy.log

Every CONNECT is logged as `ALLOW host:port` or `DENY host:port`. `--allow .x`
matches x and its subdomains; `--allow-all` allows and logs everything.
"""

import argparse
import select
import socket
import socketserver
import threading


def allowed(host: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.startswith("."):
            if host == rule[1:] or host.endswith(rule):
                return True
        elif host == rule:
            return True
    return False


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline().decode(errors="replace").split()
        while self.rfile.readline() not in (b"\r\n", b"\n", b""):
            pass
        if len(line) < 2 or line[0] != "CONNECT":
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, _, port = line[1].rpartition(":")
        ok = self.server.allow_all or allowed(host, self.server.rules)
        with self.server.lock, open(self.server.log, "a") as log:
            log.write(f"{'ALLOW' if ok else 'DENY'} {host}:{port}\n")
        if not ok:
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((host, int(port)), timeout=30)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        self.wfile.flush()
        pair = {self.connection: upstream, upstream: self.connection}
        with upstream:
            while True:
                ready, _, _ = select.select(list(pair), [], [], 300)
                if not ready:
                    return
                for sock in ready:
                    data = sock.recv(65536)
                    if not data:
                        return
                    pair[sock].sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--allow-all", action="store_true")
    parser.add_argument("--log", required=True)
    args = parser.parse_args()
    server = Server(("127.0.0.1", args.port), Handler)
    server.rules, server.allow_all, server.log, server.lock = args.allow, args.allow_all, args.log, threading.Lock()
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Measure Vivado's peak memory and build time**

In a fresh worktree of fpgas.online-test-designs at `origin/main` (use the `superpowers:using-git-worktrees` skill; branch `measure/vivado-peak`, never pushed):

```bash
uv sync --extra build
bash -c 'source /opt/Xilinx/2025.2/Vivado/settings64.sh && /usr/bin/time -v uv run python designs/acorn-pcie/gateware/acorn_pcie_soc.py --variant cle-215+ --toolchain vivado --build' 2> tmp/time-acorn-pcie.txt
grep -E "Maximum resident set size|Elapsed \(wall clock\)" tmp/time-acorn-pcie.txt
```

`acorn-pcie` on `cle-215+` (xc7a200t) is the largest design in the repo. `Maximum resident set size` is the largest single process (Vivado itself), in kB. Record both numbers and the machine (12 threads, 31 GiB) in `docs/measurements.md`.

Decision rule for the slot size: `memory_gib` = peak RSS in GiB, plus 4 GiB for the guest OS and page cache, rounded up to a multiple of 4, and never under 16. Write the result into `debian/config.toml.example` and into the spec's config block.

- [ ] **Step 3: Measure the Vivado disk**

```bash
mkdir -p tmp/vivado-disk
uv run python image/build_vivado_disk.py --source /opt/Xilinx/2025.2 --images-dir tmp/vivado-disk
uv run python image/build_vivado_disk.py --source /opt/Xilinx/2025.2 --images-dir tmp/vivado-disk-slim --exclude Vitis --exclude data/xsim --exclude data/simmodels
```

(Create `tmp/vivado-disk-slim` first. Each run takes tens of minutes and needs about 30 GiB free under `tmp/`; check with `df -h .` before starting.)

Record both sizes. To learn whether the slim disk still builds a bitstream without a VM, mount it and build against it:

```bash
mkdir -p tmp/mnt
squashfuse tmp/vivado-disk-slim/vivado-2025.2-*.squashfs tmp/mnt
bash -c 'source tmp/mnt/2025.2/Vivado/settings64.sh && uv run python designs/uart/gateware/uart_soc_acorn.py --variant cle-215+ --toolchain vivado --build'
fusermount -u tmp/mnt
```

(`squashfuse` is an unprivileged FUSE mount; if it is not installed, ask Tim to install it or to run `sudo mount -o ro,loop` for you. Run the build from the test-designs worktree with absolute paths to the mount.)

Decision rule: if the UART build produces a `.bit` from the slim disk, the exclusions `Vitis`, `data/xsim`, `data/simmodels` become the documented default in the README's "Building the Vivado disk" section; otherwise the full disk is the default and the README says which exclusion broke the build. Delete both squashfs files from `tmp/` when done: they contain Vivado and must not be left where they could be committed or uploaded.

- [ ] **Step 4: Find out what `uv sync` needs when PyPI is blocked**

In the test-designs worktree, with an empty cache directory under `tmp/`:

```bash
export UV_CACHE_DIR="$PWD/tmp/uv-cache"
uv sync --frozen --extra build --no-install-project          # 1. warm the cache, online
uv run --project ~/github/fpgas-online/fpgas.online-vivado-runners python \
  ~/github/fpgas-online/fpgas.online-vivado-runners/tools/allowlist_proxy.py \
  --port 8876 --allow github.com --allow .github.com --allow .githubusercontent.com --log tmp/proxy.log &
rm -rf .venv
HTTPS_PROXY=http://127.0.0.1:8876 HTTP_PROXY=http://127.0.0.1:8876 \
  uv sync --frozen --extra build                              # 2. same lock, PyPI blocked
grep DENY tmp/proxy.log                                       # expect no output
```

Then simulate a lock bump of one git dependency: remove that dependency's built wheel from the cache and sync again through the proxy.

```bash
uv cache clean litex
rm -rf .venv
HTTPS_PROXY=http://127.0.0.1:8876 HTTP_PROXY=http://127.0.0.1:8876 uv sync --frozen --extra build
grep DENY tmp/proxy.log
```

Stop the proxy (`kill %1`). Record in `docs/measurements.md`: whether run 2 succeeded with no `DENY` lines, and for run 3 the exit status and every denied host.

Decision rule, already agreed with Tim ("only GitHub", accepting image rebuilds on dependency changes):
- Run 2 must succeed with no denials. If it does not, the design's claim that a warm cache is enough is wrong: stop and report to Tim before going further.
- If run 3 is denied (uv asks PyPI for a build backend such as `setuptools`), write this sentence into the README under "When a job fails with a proxy refusal": "A change to `uv.lock`, including a bump of a git dependency, needs a new runner image: build one with `image/build_image.py` and activate it." If run 3 succeeds, write instead that only new or bumped PyPI packages need a new image.

- [ ] **Step 5: Write `docs/measurements.md`**

Use exactly these headings and fill every value from the commands above (no estimates):

```markdown
# Measurements

Taken on desktop.buddy.mithis.com (12 threads, 31 GiB RAM), Vivado 2025.2,
fpgas.online-test-designs at <commit>, on <date>.

## Vivado peak memory

| Design | Part | Peak RSS (GiB) | Wall time |
|---|---|---|---|
| acorn-pcie cle-215+ | xc7a200t | <value> | <value> |

Slot memory: <peak> + 4 GiB, rounded up to a multiple of 4 = **<value> GiB**.

## Vivado disk size

| Contents | Size (GiB) | UART bitstream builds |
|---|---|---|
| Full `/opt/Xilinx/2025.2` | <value> | not tested |
| Without `Vitis`, `data/xsim`, `data/simmodels` | <value> | <yes/no> |

Default: <full / slim>.

## uv without PyPI

| Run | Result | Hosts denied |
|---|---|---|
| Warm cache, same lock, PyPI blocked | <ok / failed> | <list or none> |
| One git dependency's wheel removed | <ok / failed> | <list or none> |

Consequence: <the sentence chosen by the decision rule>.
```

The angle-bracket fields are the measured values; a committed file must have none left.

- [ ] **Step 6: Commit, push, open PR F**

```bash
git add tools/allowlist_proxy.py docs/measurements.md debian/config.toml.example README.md docs/superpowers/specs
git commit -m "Measurements: Vivado memory, Vivado disk size, uv without PyPI"
git push -u origin measurements
gh pr create --title "Measurements: Vivado memory, disk size, uv without PyPI" --body "Phase 0 numbers measured on desktop.buddy, and the slot size and README text that follow from them. The GitHub blob hostnames are measured in Plan 2, where a real runner exists."
```

---

## Self-review checklist (done when writing this plan)

- Spec coverage: controller, slot loop, failure table, observability (`status`, one log line per job, proxy log), images and rollback, network policy, credentials (App key on host, JIT config in VM), Vivado disk, packaging: Tasks 2-13. Phase 0: Task 14, except the blob hostnames and the first boot, which need a real runner (Plan 2). Workflows and releases: Plan 3.
- The spec's `_diag` copy is deliberately dropped (difference 1).
- Names used across tasks: `Config.slot_dir/slot_mac/slot_ip/domain_name/domain_prefix/runner_prefix/images_dir/status_dir/console_dir` (Task 2) are the ones Tasks 7-9 call; `VirshHypervisor` and `FakeHypervisor` share one method set; disk serials `vr-vivado`, `vr-seed`, `vr-scratch` match between Task 5 and Task 11; seed files `jitconfig` and `proxy` match between Task 7 and Task 11.
