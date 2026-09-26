# Acorn LitePCIe Part A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** CI generates the LitePCIe driver for the Acorn SoC, proves it fits every image of the pinned release,
patches it, and builds the `-common`, `-dkms` and `-utils` (armhf, arm64) debs plus a fleet-kernel module
artifact; `fpgas-acorn-verify` and `fpgas-acorn-flash` refuse to touch a board whose BAR0 a driver holds.

**Architecture:** Everything lives in the new `packaging/acorn-litepcie/` directory. Host-side Python
(stdlib only, like `packaging/acorn-pcie/build_debs.py`) generates and patches the driver, cross-checks its
CSRs, computes the version and writes the nfpm configs. A second stdlib script, `container.py`, runs inside
`debian:bookworm` containers (arm64 and armhf) to compile the tools, the fleet-kernel modules and the DKMS
test. A new workflow, `.github/workflows/acorn-litepcie.yml`, wires them together.

**Tech Stack:** Python 3.12 (host, via uv) and 3.11 (bookworm's python3, in containers), pytest, nfpm 2.47.0,
Docker on `ubuntu-24.04-arm`, LiteX/litepcie at the `uv.lock` pins, the Raspberry Pi apt archive, DKMS.

**Spec:** `docs/plans/2026-09-25-acorn-litepcie-packages-design.md` (§2, §3). Read it first; section
numbers below are the spec's.

## Global Constraints

- Package names: `fpgas-online-acorn-litepcie-common`, `fpgas-online-acorn-litepcie-dkms`,
  `fpgas-online-acorn-litepcie-utils`; virtual `fpgas-online-acorn-litepcie-module`,
  `fpgas-online-acorn-litepcie-prebuilt`.
- `-common` ships `/etc/modprobe.d/fpgas-online-acorn-litepcie.conf` containing `blacklist litepcie`.
- `-dkms`: source under `/usr/src/fpgas-online-acorn-litepcie-<version>/`, `dkms.conf` exactly as §3.6,
  Depends `dkms` and `-common`, Provides `-module`, Conflicts `-prebuilt`, no headers dependency.
- `-utils`: `/usr/bin/litepcie_util`, `/usr/bin/litepcie_test`, armhf and arm64, built in `debian:bookworm`,
  Recommends `fpgas-online-acorn-litepcie-module`.
- Versions: `X.Y.postN` from `git describe --tags --long --match 'v[0-9]*.[0-9]*'` of
  `git log -1 --first-parent --format=%H -- <inputs>`; inputs are `packaging/acorn-litepcie/`,
  `designs/acorn-pcie/gateware/acorn_pcie_soc.py`, `designs/_shared/`, `uv.lock`,
  `.github/workflows/acorn-litepcie.yml`. Never dates.
- Generation: `uv run --extra build python designs/acorn-pcie/gateware/acorn_pcie_soc.py --variant cle-215+
  --driver --no-compile-software`.
- Three patches, each failing when its fix is already upstream: `.compat_ioctl = compat_ptr_ioctl`,
  `MODULE_ALIAS("platform:liteuart")`, `dma_set_mask_and_coherent()`.
- CSR cross-check: every `CSR_*` and `soc.h` name the sources reference (including `#ifdef`-only ones) agrees
  in presence and value between the generated headers and all six `csr.json` of the release pinned in
  `packaging/acorn-pcie/release.toml`, fetched and verified against `manifest_sha256` and the manifest.
- Fleet kernel: `6.12.109+rpt-rpi-v8`, bookworm; module vermagic must start with `<kver> `.
- `driver-bound` ranks between `pass` and `degraded` in `SEVERITY`, reason
  `litepcie.ko is bound: not checked`, exit status non-zero; `fpgas-acorn-flash` refuses with the same
  message.
- Apache-2.0 for new files; no host-specific names; Python rather than shell for anything with more than two
  commands; never redirect stderr to `/dev/null`.

## Review Focus

1. **A generated header whose value is an expression** (`(CSR_BASE + 0x800L)`, `0xf0000000L`) must be
   evaluated, not string-compared, or every address "differs". Test: `test_header_expressions_are_evaluated`.
2. **A referenced name that none of the known suffixes maps** (`CSR_FOO_OFFSET`, a field macro) must fail the
   check loudly instead of being skipped. Test: `test_an_unmappable_csr_name_is_an_error`.
3. **A patch whose anchor text appears twice** must be refused, not applied to the first match. Test:
   `test_a_patch_anchor_that_is_not_unique_is_refused`.
4. **A shallow clone** gives a wrong, low `postN`. The version function must fail rather than guess. Test:
   `test_the_version_refuses_a_repository_without_a_series_tag`.
5. **A PCI device bound to some other driver** (vfio-pci, a future in-tree driver) also owns BAR0; the tools
   must refuse it too, naming that driver. Test: `test_any_bound_driver_is_refused_and_named`.

---

## File Structure

| File | Responsibility |
|---|---|
| `packaging/acorn-litepcie/kernels.toml` | `fleet_kernel`, `fleet_suite`, `min_kernel` |
| `packaging/acorn-litepcie/prepare_driver.py` | generate the driver tree, copy it out, apply `PATCHES` |
| `packaging/acorn-litepcie/csr_check.py` | the §3.2 cross-check against the pinned release |
| `packaging/acorn-litepcie/build_debs.py` | `driver_version()`, nfpm configs, `dkms.conf`, CLI |
| `packaging/acorn-litepcie/fpgas-online-acorn-litepcie.conf` | the modprobe.d blacklist |
| `packaging/acorn-litepcie/dkms-postinst`, `dkms-prerm` | the DKMS maintainer scripts (dh_dkms shape) |
| `packaging/acorn-litepcie/struct_layout.c` | the §3.3 `_Static_assert`s |
| `packaging/acorn-litepcie/container.py` | in-container steps: `utils`, `module`, `dkms-test` |
| `.github/workflows/acorn-litepcie.yml` | CI |
| `designs/acorn-pcie/host/spi_flash.py` | `bound_driver()`, refusal in `main()` |
| `designs/acorn-pcie/host/acorn_verify.py` | `driver-bound` result |
| `tests/test_acorn_litepcie.py` | unit tests for everything under `packaging/acorn-litepcie/` |
| `tests/test_acorn_verify.py`, `tests/test_spi_flash.py` | driver-bound tests |

---

### Task 1: fpgas-acorn-verify and fpgas-acorn-flash refuse a driver-bound board (§3.7)

**Files:** Modify `designs/acorn-pcie/host/spi_flash.py`, `designs/acorn-pcie/host/acorn_verify.py`; Test
`tests/test_spi_flash.py`, `tests/test_acorn_verify.py`.

**Interfaces:**
- Produces: `spi_flash.SYSFS_PCI = "/sys/bus/pci/devices"`, `spi_flash.bound_driver(bdf, sysfs=None) -> str |
  None` (the basename of the `driver` symlink's target), `spi_flash.driver_bound_reason(name) -> str`
  (`"litepcie.ko is bound: not checked"` for litepcie, `"the <name> driver is bound: not checked"` otherwise).
- `acorn_verify.SEVERITY = ("none", "pass", "driver-bound", "degraded", "unconverted", "fail", "error")`.

- [ ] **Step 1: failing tests.** In `tests/test_acorn_verify.py`, extend `_sysfs()` to accept an optional
  driver name per device (make `devices` entries optionally 6-tuples, the sixth being a driver name that
  becomes `d/"driver"` as a symlink to `root/../drivers/<name>`), then:

```python
BOUND = (*OURS, "litepcie")

def test_a_board_with_litepcie_bound_is_driver_bound_and_its_bar_is_never_opened(tmp_path, images):
    def refuse(bdf):
        raise AssertionError("BAR0 is litepcie.ko's while it is bound")
    report = av.verify(av.scan_pci(_sysfs(tmp_path, BOUND)), images, open_bar=refuse)
    (board,) = report["boards"]
    assert report["result"] == board["result"] == "driver-bound"
    assert board["reason"] == "litepcie.ko is bound: not checked"
    assert board["driver"] == "litepcie"
    assert av.exit_code(report) == 1

def test_driver_bound_ranks_between_pass_and_degraded():
    s = av.SEVERITY
    assert s.index("pass") < s.index("driver-bound") < s.index("degraded")

def test_any_bound_driver_is_refused_and_named(tmp_path, images): ...  # vfio-pci -> reason names vfio-pci

def test_identify_also_leaves_a_driver_bound_board_alone(tmp_path, images): ...
```

  In `tests/test_spi_flash.py`: `bound_driver()` returns `None` with no `driver` link and `"litepcie"` with one;
  `main()` with `--bdf` of a bound device prints `error: litepcie.ko is bound: not checked`, `RESULT: FAIL`,
  returns 1, and never constructs `Bar0Bus` (monkeypatch `sf.Bar0Bus` to raise). `main()` must accept `argv`.

- [ ] **Step 2: run** `uv run --no-project --python 3.12 --with pytest pytest tests/test_acorn_verify.py
  tests/test_spi_flash.py` — the new tests fail.
- [ ] **Step 3: implement.** `scan_pci()` records `"driver": bound_driver(d.name, root)` for each device.
  `_tier1()` stays first (an unconverted board is unconverted whatever is bound); then a new
  `_not_driver_bound(dev)` raises `Problem("driver-bound", driver_bound_reason(dev["driver"]))` in both
  `_check_board` and `_identify_board`, before `open_bar`. `spi_flash.main(argv=None)` checks
  `bound_driver(args.bdf)` when not `--uart`, before `Bar0Bus`. `_summary`/fleet event need no change.
- [ ] **Step 4: run the tests** — pass. `ruff check` and `ruff format --check` on the touched files.
- [ ] **Step 5: commit** `acorn-verify, acorn-flash: leave a board alone while a driver holds its BAR0`.

### Task 2: `kernels.toml` and the driver version (§3.8)

**Files:** Create `packaging/acorn-litepcie/kernels.toml`, `packaging/acorn-litepcie/build_debs.py`; Test
`tests/test_acorn_litepcie.py`.

**Interfaces:**
- `build_debs.VERSION_INPUTS` (tuple of the five paths), `build_debs.driver_version(repo=REPO) -> str`,
  `build_debs.read_kernels(path=KERNELS) -> dict`, `build_debs.kernel_release_key(kver) -> tuple[int, ...]`.

- [ ] **Step 1: failing tests** using a throwaway git repo in `tmp_path` (helper `_git(repo, *args)`):
  - at tag `v0.0` with inputs committed → `"0.0"`; two more commits touching an input → `"0.0.post2"`;
  - a commit touching only `README` does not change the version;
  - first-parent: branch `side` commits an input change *before* main commits two unrelated changes, then main
    merges `side` with `--no-ff`; version is `describe` of the merge commit (`post4`), not of the side commit
    (`post1`);
  - no `vX.Y` tag → `BuildError` naming "shallow"/"tag" (`test_the_version_refuses_a_repository_without_a_series_tag`);
  - `kernels.toml`: `fleet_kernel == "6.12.109+rpt-rpi-v8"`, `fleet_suite == "bookworm"`, and
    `kernel_release_key(fleet_kernel) >= kernel_release_key(min_kernel)` (the §4.3 guard, cheap to have now).
- [ ] **Step 2: run** — fail (module missing).
- [ ] **Step 3: implement** `driver_version()`:

```python
def driver_version(repo=REPO):
    commit = _git(repo, "log", "-1", "--first-parent", "--format=%H", "--", *VERSION_INPUTS)
    if not commit:
        raise BuildError(f"no commit touches {VERSION_INPUTS}")
    out = _git(repo, "describe", "--tags", "--long", "--match", "v[0-9]*.[0-9]*", commit)
    m = re.fullmatch(r"v(\d+)\.(\d+)-(\d+)-g[0-9a-f]+", out)
    ...  # same X.Y / X.Y.postN rule as packaging/acorn-pcie/build_debs.py git_version()
```

  `kernels.toml`:

```toml
fleet_kernel = "6.12.109+rpt-rpi-v8"
fleet_suite = "bookworm"
min_kernel = "6.12"
```

- [ ] **Step 4: run** — pass. **Step 5: commit** `acorn-litepcie: the driver version, from its inputs' last first-parent commit`.

### Task 3: generate and patch the driver (§3.1, §3.3–§3.5)

**Files:** Create `packaging/acorn-litepcie/prepare_driver.py`; Test `tests/test_acorn_litepcie.py`.

**Interfaces:**
- `prepare_driver.Patch(path, old, new, why)` (a dataclass), `prepare_driver.PATCHES` (three entries,
  paths relative to the driver tree: `kernel/main.c`, `kernel/liteuart.c`, `kernel/main.c`),
  `prepare_driver.apply_patches(driver_dir, patches=PATCHES) -> None` raising `PatchError`,
  `prepare_driver.generate(out_dir, repo=REPO, python=("uv", "run", "--extra", "build", "python")) -> Path`
  (runs the SoC script, copies `designs/acorn-pcie/build/acorn-cle-215+/driver/{kernel,user}` to
  `out_dir/{kernel,user}`, dropping `__init__.py`/`__pycache__`, and returns `out_dir`).
- CLI: `prepare_driver.py --out DIR [--from-dir GENERATED]` (generate, or take an already generated tree),
  then patch.

The patches:

```python
PATCHES = (
    Patch("kernel/main.c", "\t.unlocked_ioctl = litepcie_ioctl,\n",
          "\t.unlocked_ioctl = litepcie_ioctl,\n\t.compat_ioctl = compat_ptr_ioctl,\n",
          "armhf tools on an arm64 kernel get ENOTTY without it"),
    Patch("kernel/liteuart.c", 'MODULE_ALIAS("platform: liteuart");', 'MODULE_ALIAS("platform:liteuart");',
          "the stray space stops udev matching the platform:liteuart modalias"),
    Patch("kernel/main.c", "\tret = dma_set_mask(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));\n",
          "\tret = dma_set_mask_and_coherent(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));\n",
          "the 32-bit coherent mask fails every dmam_alloc_coherent on a Pi 5"),
)
```

`apply_patches` refuses when `old` occurs other than exactly once, or when the file already contains the
fixed text (`compat_ioctl`, `platform:liteuart`, `dma_set_mask_and_coherent`): that means upstream fixed it
and the patch must be dropped. Each `Patch` therefore also carries `already`, the marker whose presence
means "fixed upstream".

- [ ] **Step 1: failing tests** on fixture copies of the three upstream snippets: each patch applies; applying
  twice fails with "already"; an anchor missing fails; an anchor present twice fails
  (`test_a_patch_anchor_that_is_not_unique_is_refused`); `generate()` with a fake `python` command (a small
  script that writes the tree `acorn_pcie_soc.py` would) copies `kernel/` and `user/` and the argv includes
  `--variant cle-215+ --driver --no-compile-software`.
- [ ] **Step 2–4:** run (fail), implement, run (pass).
- [ ] **Step 5: prove on the real tree.** Run `prepare_driver.py --out <tmp> --from-dir` on the tree generated
  from HEAD (on this host it takes over 15 min; start it in the background early), check the three diffs
  with `diff -u` against the unpatched copy.
- [ ] **Step 6: commit** `acorn-litepcie: generate the driver at HEAD and apply its three patches`.

### Task 4: the CSR cross-check (§3.2)

**Files:** Create `packaging/acorn-litepcie/csr_check.py`; Test `tests/test_acorn_litepcie.py`.

**Interfaces:**
- `csr_check.parse_defines(text) -> dict[str, str]`, `csr_check.evaluate(defines) -> dict[str, int | str |
  None]` (resolves `(CSR_BASE + 0x800L)` and `L` suffixes; a bare `#define X` is `None`),
  `csr_check.referenced_names(driver_dir) -> set[str]` (identifiers in every `.c`/`.h` under `kernel/` and
  `user/` except the generated `csr.h`, `soc.h`, `mem.h`),
  `csr_check.json_value(csr, name, soc_constants) -> (present: bool, value)`,
  `csr_check.check(driver_dir, csr_jsons: dict[str, dict]) -> list[str]` (problems; empty means agreement),
  `csr_check.fetch_release_csrs(pin=RELEASE_TOML, fetch=None) -> dict[str, dict]` (reusing
  `packaging/acorn-pcie/build_debs.py`'s `read_pin`, `release_fetcher`, `local_fetcher` via importlib, the
  manifest checked against `manifest_sha256`, each `csr.json` against its manifest size and sha256, and
  exactly six of them).
- CLI: `csr_check.py DRIVER_DIR [--from-dir STAGED_RELEASE]`; prints each checked name and its value, exits
  1 with the problems listed.

Mapping (spec table): `CSR_BASE` → `memories.csr.base`; `CSR_<N>_ADDR` → `csr_registers[n].addr`;
`CSR_<N>_BASE` → `csr_bases[n]`; `CSR_<N>_SIZE` → `csr_registers[n].size`; a SoC constant is any referenced
identifier defined in `soc.h` or present (upper-cased) in any `csr.json`'s `constants`. Any other referenced
`CSR_*` name is a problem ("cannot map").

- [ ] **Step 1: failing tests** with a fixture driver tree (a `main.c` referencing `CSR_BASE`,
  `CSR_PCIE_MSI_ENABLE_ADDR`, `CSR_PCIE_DMA0_BASE`, `#ifdef CSR_PCIE_DMA1_BASE`, `#ifdef CSR_PCIE_MSI_PBA_ADDR`,
  `DMA_CHANNELS`, `PCIE_DMA1_READER_INTERRUPT`, `DMA_BUFFER_COUNT`) and six matching `csr.json` dicts:
  - agreement → `[]`;
  - one image with a different `pcie_msi_enable` address → a problem naming that image and both values;
  - `CSR_PCIE_DMA1_BASE` absent from the headers but `pcie_dma1` in one `csr.json` → presence problem;
  - `CSR_PCIE_MSI_ENABLE_ADDR` in the headers but missing from the golden `csr.json` → presence problem;
  - `DMA_CHANNELS` 1 in `soc.h`, 2 in one `csr.json` → problem; `DMA_BUFFER_COUNT` (config.h only) ignored;
  - `test_header_expressions_are_evaluated`, `test_an_unmappable_csr_name_is_an_error`;
  - `fetch_release_csrs` refuses a manifest whose hash is not the pin's, and a `csr.json` that does not match
    its entry (reuse a staged-release fixture built like `tests/test_acorn_packaging.py`'s).
- [ ] **Step 2–4:** run (fail), implement, run (pass).
- [ ] **Step 5: prove on the real tree and release**: `csr_check.py <generated tree>` against the pinned
  release passes and lists the names checked.
- [ ] **Step 6: commit** `acorn-litepcie: cross-check the driver's CSRs against all six release images`.

### Task 5: the struct-layout asserts (§3.3)

**Files:** Create `packaging/acorn-litepcie/struct_layout.c`.

`_Static_assert` on `sizeof` and `offsetof` for every row of the §3.3 table, compiled with
`gcc -fsyntax-only -I<driver>/kernel`. Test: compile it in the arm64 and armhf bookworm containers here
(`container.py utils` runs it first; Task 7), and once with a deliberately wrong size to see it fail.
Commit `acorn-litepcie: assert the ioctl structs have one layout on armhf and arm64`.

### Task 6: the debs: `-common`, `-dkms`, `-utils` (§2, §3.6)

**Files:** Create `packaging/acorn-litepcie/fpgas-online-acorn-litepcie.conf`, `dkms-postinst`, `dkms-prerm`;
Modify `packaging/acorn-litepcie/build_debs.py`; Test `tests/test_acorn_litepcie.py`.

**Interfaces:**
- `build_debs.dkms_conf(version) -> str` (exactly §3.6's text with the version),
  `build_debs.common_nfpm(version)`, `build_debs.dkms_nfpm(version, driver_dir, staging)`,
  `build_debs.utils_nfpm(version, arch, bin_dir)` (reads `bin_dir/utils.json` `{"glibc": "2.34"}` written by
  `container.py utils`), `run_nfpm` shared in shape with `packaging/acorn-pcie/build_debs.py`.
- CLI: `build_debs.py --out DIR --driver DIR --only {common,dkms,utils} [--arch A --bin-dir D] [--nfpm P]`.

- [ ] **Step 1: failing tests:** `dkms_conf("0.0.post7")` equals the spec block; `-dkms` config: arch `all`,
  depends `dkms` and `fpgas-online-acorn-litepcie-common`, provides `fpgas-online-acorn-litepcie-module`,
  conflicts `fpgas-online-acorn-litepcie-prebuilt`, no `linux-headers` anywhere, every source file of
  `kernel/` under `/usr/src/fpgas-online-acorn-litepcie-0.0.post7/`, `dkms.conf` there, postinst/prerm scripts
  set; `-common`: one file, `/etc/modprobe.d/fpgas-online-acorn-litepcie.conf`, content `blacklist litepcie`,
  type `config`; `-utils`: arch `armhf`/`arm64`, the two binaries at `/usr/bin` mode 0755, depends
  `libc6 (>= <glibc>)`, recommends the virtual module; every config has `version_schema: none`.
- [ ] **Step 2–4:** run (fail), implement, run (pass). Build all three locally with nfpm (arm64 nfpm) and
  inspect with `dpkg-deb -f` / `-c`.
- [ ] **Step 5: commit** `acorn-litepcie: -common, -dkms and -utils debs`.

### Task 7: in-container builds: tools, fleet module, DKMS test (§3.6, §3.9)

**Files:** Create `packaging/acorn-litepcie/container.py`; Test `tests/test_acorn_litepcie.py` (argument
parsing and the vermagic/glibc parsers only; the rest is exercised by running it).

**Interfaces:**
- `container.py utils --driver D --out O`: `apt-get install gcc make libc6-dev binutils`, compile
  `struct_layout.c`, `make -C D/user litepcie_util litepcie_test`, strip, copy to `O`, write `O/utils.json`
  with the highest `GLIBC_x.y` either binary needs (`objdump -T`).
- `container.py module --driver D --out O [--kver K]`: default `K` from `kernels.toml`; add the RPi archive,
  install `linux-headers-K`, `make -C /usr/src/linux-headers-K M=<copy of D/kernel> modules`, check
  `modinfo -F vermagic` starts with `K `, copy the two `.ko` to `O`.
- `container.py dkms-test --debs DIR`: add the RPi archive, install `dkms` and `linux-headers-rpi-v8` (the
  meta package names the newest v8 kernel), install the debs through apt, `dkms install -k K`, then
  `modinfo -k K litepcie liteuart` and the blacklist file.
- `container.py install-test --debs DIR`: install `-common` and `-utils`, `litepcie_util` prints its usage.
- Pure helpers with unit tests: `max_glibc(objdump_text) -> str`, `vermagic_ok(vermagic, kver) -> bool`,
  `newest_headers(depends_text) -> str`.

- [ ] Tests first for the helpers; implement; run all four subcommands locally with
  `sudo -n docker run --rm --network host --platform linux/arm64|linux/arm/v7 -v <worktree>:/w -w /w
  debian:bookworm sh -ec 'apt-get update -qq && apt-get install -y -qq python3 >/dev/null; python3 ...'`;
  the fleet module's vermagic must read `6.12.109+rpt-rpi-v8 SMP preempt mod_unload modversions aarch64`.
- [ ] Commit `acorn-litepcie: in-container builds of the tools, the fleet module and a DKMS test`.

### Task 8: the workflow (§3.6)

**Files:** Create `.github/workflows/acorn-litepcie.yml`.

Triggers: `pull_request`, `push` to main, `schedule` daily, `workflow_dispatch`; the concurrency block of
`acorn-debs.yml`; `permissions: contents: read`. Jobs:

1. `test` (ubuntu-latest): ruff check/format on the new and touched Python; pytest
   `tests/test_acorn_litepcie.py tests/test_acorn_verify.py tests/test_spi_flash.py tests/test_acorn_packaging.py`.
2. `driver` (ubuntu-latest, fetch-depth 0): `uv sync --python 3.12 --extra build`, `prepare_driver.py --out
   dist/driver`, `csr_check.py dist/driver`, version, nfpm (x86_64, sha256-pinned), `-common` and `-dkms`;
   artifacts `acorn-litepcie-driver` and `acorn-litepcie-debs-all`.
3. `utils` (ubuntu-24.04-arm, matrix arm64/armhf): download the driver, `container.py utils` in
   `debian:bookworm` under the arch's platform, nfpm (arm64, sha256-pinned) `-utils`, then
   `container.py install-test` in the same platform; artifact `acorn-litepcie-debs-<arch>`.
4. `fleet-module` (ubuntu-24.04-arm): `container.py module`; artifact
   `acorn-litepcie-modules-<fleet_kernel>` (the `.ko` files, for §3.9's hardware steps).
5. `dkms` (ubuntu-24.04-arm): `container.py dkms-test` with the `-common` and `-dkms` debs.
6. `publish` (main pushes, schedule and dispatch on main only; `contents: write`): the debs to the series
   release, as `acorn-debs.yml` does.

- [ ] Push, watch every job, iterate until green. Commit `ci: acorn-litepcie workflow`.

### Task 9: spec status and review

- [ ] Update the spec's Status line to say Part A is implemented by this branch, and record anything that
  differs from the spec in the PR description.
- [ ] Independent code review of the whole diff (superpowers:requesting-code-review); fix findings with
  superpowers:receiving-code-review; CI green again; open the PR.
