# Acorn PCIe Phase 0 (harness): `verify_hardware.py` transport + Acorn pin-ID gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `verify_hardware.py` able to reach, program, power-cycle and test the six Welland Acorn hosts under the post-2026-08-30 network, and prove it end to end by running the Acorn pin-ID wiring check on `welland-sw2-p46`.

**Architecture:** The orchestrator keeps its `HOSTS × DESIGNS` model. Transport changes from a nested `ssh gateway "ssh root@ip cmd"` to a single `ssh -o ProxyJump=<gateway> <user>@<ip> cmd`, with an explicit per-host user and a `sudo -n sh -c` wrapper for hosts whose login user is not root. PoE reset moves from the vanished `poe.sh` to SNMP `pethPsePortAdminEnable` writes to the S3300, executed on tweed. The Acorn `program_cmd` encodes the Pi 5 rules from `docs/hardware/acorn-pinmap.md` (detach the PCIe endpoint, `gpiochip15` symlink, libgpiod cable, rescan). The pin-ID host decoder from PR #9 is cherry-picked and its expected map corrected to the canonical crossover wiring.

**Tech Stack:** Python 3.12 (`uv run`), pytest (`--extra dev`), OpenSSH ProxyJump, Net-SNMP on tweed, openFPGALoader 0.10.0 (libgpiod cable) on the Pis, Vivado 2025.2 locally for the gate bitstream.

**Spec:** `docs/plans/2026-09-03-acorn-pcie-design.md` §2.2, §3.3, Phase 0 (this plan covers Phase 0 steps 3-partial and 5; the `vivado-xilinx-flows` PR and the PR #9 rebase are separate plans).

**Branch / worktree:** `acorn-pcie/00-prereqs` in `.worktrees/acorn-pcie-00-prereqs` (already created from `origin/main` at `7268b4e`).

**Facts this plan relies on (verified 2026-09-03):**
- `ssh tim@10.21.0.1` reaches tweed over `wg-desktop`; `ssh -o ProxyJump=tim@10.21.0.1 pi@10.21.2.29` works with pubkey auth; `sudo -n true` succeeds for `pi`; `root@` is refused.
- On the Pis: `openFPGALoader v0.10.0` (no `rp1pio` cable, opens `/dev/gpiochip0`; the header is `/dev/gpiochip15`), `/dev/ttyAMA0` exists, console is `ttyAMA10`, root is `overlayroot=tmpfs`, no kernel headers.
- From tweed: `snmpget -v2c -c public 10.1.5.11 1.3.6.1.2.1.105.1.1.1.3.1.29` returns `INTEGER: 1` (pethPsePortAdminEnable, port 29 enabled). `snmpset` is installed. The write community is not in this repo.
- PR #9's `identify_pmod_pins.py --board acorn` expects `GPIO14→K2, GPIO15→J2`; PR #11 established the canonical wiring is `GPIO15←K2, GPIO14→J2, GPIO3↔J5, GPIO4↔H5`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `verify_hardware.py` | Orchestrator. Changes: `GATEWAYS`, `HOSTS` (user/poe fields, six Acorn hosts), `_build_ssh_cmd` (ProxyJump + sudo wrapper), `remote_home`, `poe_reset` (SNMP), `PROGRAM_CMD["acorn"]`, `pin-id` design entry, `--repeat`, `--dry-run` |
| `tests/test_verify_hardware.py` | New. Pure-function tests for ssh command construction, remote paths, sudo wrapping, PoE OID/command construction, and test generation for the Acorn hosts |
| `tests/__init__.py` | New, empty (pytest discovery) |
| `designs/pmod-pin-id/host/identify_pmod_pins.py` | Cherry-picked from PR #9 then corrected: `BOARDS["acorn"]` canonical map |
| `designs/pmod-pin-id/host/test_identify_pmod_pins.py` | Cherry-picked from PR #9 then corrected to the canonical map |
| `docs/verify-hardware.md` | Transport, sudo, PoE, Acorn programming sequence documented |
| `pyproject.toml` | `[tool.pytest.ini_options] testpaths` so `uv run --extra dev pytest` finds both test locations |

Everything else (other boards' host entries) is left as it is; PR #11 flagged them as not re-probed and they are out of scope here.

---

### Task 0: Environment for the worktree

**Files:** none

- [ ] **Step 1: Install the dev extras in the worktree**

Run from `.worktrees/acorn-pcie-00-prereqs`:
```bash
uv sync --extra dev
```
Expected: ends with `Installed N packages` (ruff and pytest present).

- [ ] **Step 2: Baseline lint**

Run: `uv run --extra dev ruff check designs/ verify_hardware.py`
Expected: `All checks passed!`

---

### Task 1: Cherry-pick the pin-ID pieces from PR #9

**Files:**
- Modify (via cherry-pick): `designs/pmod-pin-id/host/identify_pmod_pins.py`
- Create (via cherry-pick): `designs/pmod-pin-id/host/test_identify_pmod_pins.py`
- Modify (via cherry-pick): `verify_hardware.py` (adds the `pin-id` design entry)

- [ ] **Step 1: Cherry-pick the two commits**

```bash
git cherry-pick -x 8ef1bf3 9eec4d9
```
Expected: two commits applied cleanly (both touch files unchanged since May on `main`). If `verify_hardware.py` conflicts, resolve by keeping both the existing `pcie` entry and the new `pin-id` entry.

- [ ] **Step 2: Run the cherry-picked tests to establish the baseline**

Run: `uv run --extra dev pytest designs/pmod-pin-id/host/test_identify_pmod_pins.py -v`
Expected: 6 passed.

---

### Task 2: Correct the Acorn expected wiring map (TDD)

**Files:**
- Modify: `designs/pmod-pin-id/host/test_identify_pmod_pins.py`
- Modify: `designs/pmod-pin-id/host/identify_pmod_pins.py` (`BOARDS["acorn"]`)

- [ ] **Step 1: Change the map test to the canonical crossover**

Replace `test_acorn_board_map_matches_p2_header` with:
```python
def test_acorn_board_map_matches_p2_header():
    # Canonical fleet wiring (docs/hardware/acorn-pinmap.md, revised 2026-09-03):
    # FPGA TX K2 -> Pi RXD0 (GPIO15), FPGA RX J2 <- Pi TXD0 (GPIO14),
    # J5 -> GPIO3, H5 -> GPIO4.
    pins = {gpio: ball for gpio, ball, _label in ident.BOARDS["acorn"]["pins"]}
    assert pins == {15: "K2", 14: "J2", 3: "J5", 4: "H5"}
```
and update `test_evaluate_all_correct_passes`, `test_evaluate_one_miswired_fails`, `test_evaluate_missing_signal_fails`, `test_evaluate_garbled_decode_fails` so that the "correct" decode is `{15: "K2", 14: "J2", 3: "J5", 4: "H5"}` and the "swapped" decode is `{15: "J2", 14: "K2", 3: "J5", 4: "H5"}` (the pi-sw2-p47 case). Add one more test:
```python
def test_evaluate_p47_reversed_connector_fails_all_four():
    # pi-sw2-p47 on 2026-08-31: both pairs transposed.
    decoded = {14: "K2", 15: "J2", 3: "H5", 4: "J5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    assert {r["gpio"] for r in rows if not r["ok"]} == {3, 4, 14, 15}
```

- [ ] **Step 2: Run the tests, expect the map test and the p47 test to fail**

Run: `uv run --extra dev pytest designs/pmod-pin-id/host/test_identify_pmod_pins.py -v`
Expected: 6 FAILED, 1 passed. Only `test_evaluate_unprogrammed_board_all_none_fails` passes; every test that encodes the canonical decode fails against the old map (the map test, the p47 test, and the four `evaluate_*` tests whose "correct" decode is now `{15: "K2", 14: "J2", ...}`).

- [ ] **Step 3: Fix the map**

In `identify_pmod_pins.py`, replace the `"acorn"` entry's `pins` with:
```python
        "pins": [
            (15, "K2", "P2.1 Serial TX -> Pi RXD0"),
            (14, "J2", "P2.2 Serial RX <- Pi TXD0"),
            (3, "J5", "P2.3 Spare GPIO 0"),
            (4, "H5", "P2.4 Spare GPIO 1"),
        ],
```
and change the comment above `BOARDS` to cite `docs/hardware/acorn-pinmap.md` "Measured P2 wiring (Welland, 2026-08-31)".

- [ ] **Step 4: Run the tests, expect all green**

Run: `uv run --extra dev pytest designs/pmod-pin-id/host/test_identify_pmod_pins.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check designs/pmod-pin-id/
git add designs/pmod-pin-id/host/identify_pmod_pins.py designs/pmod-pin-id/host/test_identify_pmod_pins.py
git commit -m "pmod-pin-id(acorn): expected wiring is the K2->GPIO15 / J2->GPIO14 crossover"
```

---

### Task 3: pytest discovery for the repo

**Files:**
- Create: `tests/__init__.py` (empty)
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest config**

Append to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
# Only the pure host-side unit tests. The other designs/*/host/test_*.py are
# hardware test *scripts* (they import gpiod, take CLI args, define
# fixture-less test_* functions) and must not be collected.
testpaths = ["tests", "designs/pmod-pin-id/host"]
python_files = ["test_*.py"]
```

- [ ] **Step 2: Verify discovery picks up the pin-id tests from the repo root**

Run: `uv run --extra dev pytest -q`
Expected: `7 passed`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml tests/__init__.py
git commit -m "build: pytest discovers tests/ and designs/*/host tests"
```

---

### Task 4: Transport — ProxyJump, per-host user, sudo wrapper (TDD)

**Files:**
- Create: `tests/test_verify_hardware.py`
- Modify: `verify_hardware.py` (`GATEWAYS`, `_build_ssh_cmd`, new `remote_home`, `ssh_run`, `ssh_upload`)

- [ ] **Step 1: Write the failing tests**

`tests/test_verify_hardware.py`:
```python
"""Pure-function tests for verify_hardware.py (no network)."""

import importlib.util
import pathlib

_MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "verify_hardware.py"
_spec = importlib.util.spec_from_file_location("verify_hardware", _MOD_PATH)
vh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vh)


def test_gateway_host_uses_proxyjump_and_login_user():
    cmd = vh._build_ssh_cmd("welland-sw2-p29", "echo ok", as_root=False)
    assert cmd == [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "ProxyJump=tim@10.21.0.1",
        "pi@10.21.2.29", "echo ok",
    ]


def test_gateway_host_wraps_root_commands_in_sudo():
    cmd = vh._build_ssh_cmd("welland-sw2-p29", "rmmod spidev; echo done", as_root=True)
    assert cmd[-2] == "pi@10.21.2.29"
    assert cmd[-1] == "sudo -n sh -c 'rmmod spidev; echo done'"


def test_root_login_host_is_not_wrapped():
    cmd = vh._build_ssh_cmd("welland-pi3", "echo ok", as_root=True)
    assert cmd[-2] == "root@10.21.0.103"
    assert cmd[-1] == "echo ok"


def test_direct_host_has_no_proxyjump():
    cmd = vh._build_ssh_cmd("rpi5-netv2", "echo ok", as_root=False)
    assert "-o" in cmd and not any(a.startswith("ProxyJump=") for a in cmd)
    assert cmd[-2:] == ["tim@rpi5-netv2.iot.welland.mithis.com", "echo ok"]


def test_remote_home_follows_login_user():
    assert vh.remote_home("welland-sw2-p29") == "/home/pi"
    assert vh.remote_home("welland-pi3") == "/root"
    assert vh.remote_home("rpi5-netv2") == "/home/tim"
```

- [ ] **Step 2: Run, expect failures**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v`
Expected: all 5 FAIL (`KeyError: 'welland-sw2-p29'` / `TypeError: unexpected keyword 'as_root'` / `AttributeError: remote_home`).

- [ ] **Step 3: Implement**

In `verify_hardware.py`:

Replace `GATEWAYS` with:
```python
# Jump hosts. Welland's tweed was reinstalled 2026-08-30; the old restricted
# `pi@tweed.welland.mithis.com` account is gone and the public name now resolves
# to a reverse proxy. tweed's eth-local address is reachable over WireGuard
# (wg-desktop) and accepts the operator's own key. PS1 is unchanged (unverified
# since 2026-03).
GATEWAYS = {
    "welland": "tim@10.21.0.1",
    "ps1": "pi@ps1.fpgas.online",
}
SSH_BASE_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
```

Add the six Acorn hosts to `HOSTS`, replacing the `welland-pi2` entry:
```python
    # Sqrl Acorn CLE-215+ on RPi 5 (VLAN-per-port names since 2026-08-23, see
    # docs/hardware/site-welland.md). Login is the `pi` user with passwordless
    # sudo; root login is refused. PoE port = switch port = host suffix.
    **{
        f"welland-sw2-p{port}": {
            "ssh_type": "gateway", "gateway": "welland",
            "target": f"10.21.2.{port}", "user": "pi",
            "board": "acorn", "variant": "cle-215+",
            "poe": {"switch": "sw2", "port": port},
        }
        for port in (29, 43, 44, 46, 47, 48)
    },
```
(Delete the old `welland-pi2` entry; leave the other legacy entries untouched with a one-line comment above them: `# Legacy 10.21.0.1NN addresses from the 2026-03 survey — not re-probed since the VLAN-per-port move; see docs/hardware/site-welland.md.`)

Replace `_build_ssh_cmd` and add `remote_home`:
```python
def host_user(host_name):
    """Login user on the target. Gateway hosts default to root (legacy);
    direct hosts carry the user in `target`."""
    host = HOSTS[host_name]
    if host["ssh_type"] == "direct":
        return host["target"].split("@", 1)[0]
    return host.get("user", "root")


def remote_home(host_name):
    user = host_user(host_name)
    return "/root" if user == "root" else f"/home/{user}"


def _build_ssh_cmd(host_name, remote_cmd, as_root=True):
    """Build the ssh argv for *remote_cmd* on *host_name*.

    Gateway hosts go through OpenSSH ProxyJump (one hop, no nested quoting).
    When the login user is not root and *as_root* is set, the command is run
    under `sudo -n sh -c` so rmmod, PCI sysfs writes and openFPGALoader work.
    """
    host = HOSTS[host_name]
    user = host_user(host_name)
    if as_root and user != "root":
        remote_cmd = f"sudo -n sh -c {shlex.quote(remote_cmd)}"
    cmd = ["ssh", *SSH_BASE_OPTS]
    if host["ssh_type"] == "gateway":
        cmd += ["-o", f"ProxyJump={GATEWAYS[host['gateway']]}"]
        cmd += [f"{user}@{host['target']}", remote_cmd]
    else:
        cmd += [host["target"], remote_cmd]
    return cmd
```

Update `ssh_run(host_name, cmd, timeout=180, as_root=True)` to pass `as_root` through, and `ssh_upload` to call `_build_ssh_cmd(host_name, write_cmd, as_root=False)` (uploads land in the login user's home; programs then read them with sudo, which is fine because the path is absolute — see Task 6).

`ssh_check_connectivity` calls `ssh_run(..., as_root=False)`.

- [ ] **Step 4: Run tests, expect green**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check verify_hardware.py tests/
git add verify_hardware.py tests/test_verify_hardware.py
git commit -m "verify_hardware: ProxyJump transport, per-host login user, sudo wrapper; six Welland Acorn hosts"
```

---

### Task 5: PoE reset over SNMP (TDD)

**Files:**
- Modify: `tests/test_verify_hardware.py`
- Modify: `verify_hardware.py` (`POE_SWITCHES`, `poe_snmp_cmd`, `poe_reset`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verify_hardware.py`:
```python
def test_poe_snmp_cmd_builds_admin_enable_write():
    off = vh.poe_snmp_cmd("welland-sw2-p29", enable=False, community="secret")
    assert off == [
        "snmpset", "-v2c", "-c", "secret", "10.1.5.11",
        "1.3.6.1.2.1.105.1.1.1.3.1.29", "i", "2",
    ]
    on = vh.poe_snmp_cmd("welland-sw2-p29", enable=True, community="secret")
    assert on[-1] == "1"


def test_poe_snmp_cmd_rejects_host_without_poe_info():
    import pytest
    with pytest.raises(KeyError):
        vh.poe_snmp_cmd("welland-pi3", enable=False, community="secret")
```

- [ ] **Step 2: Run, expect failures**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v -k poe`
Expected: 2 FAIL (`AttributeError: poe_snmp_cmd`).

- [ ] **Step 3: Implement**

Add after `GATEWAYS`:
```python
# PoE switches, keyed by the `switch` field of a host's `poe` entry. The S3300
# at Welland answers SNMP from tweed (read community `public` verified
# 2026-09-03). Port power is POWER-ETHERNET-MIB pethPsePortAdminEnable
# (.1.3.6.1.2.1.105.1.1.1.3.<group>.<port>): 1 = enable, 2 = disable.
POE_SWITCHES = {
    "sw2": {"address": "10.1.5.11", "group": 1},
}
POE_ADMIN_ENABLE_OID = "1.3.6.1.2.1.105.1.1.1.3"
# The SNMP write community is deliberately not in the repo. Export it as
# FPGAS_POE_COMMUNITY (it lives in fpgas.online-infra) before running tests
# that need a power cycle; without it poe_reset() reports and returns False.
POE_COMMUNITY_ENV = "FPGAS_POE_COMMUNITY"


def poe_snmp_cmd(host_name, enable, community):
    """snmpset argv (run on the gateway) that turns a host's PoE port on/off."""
    poe = HOSTS[host_name]["poe"]  # KeyError for hosts without PoE info
    sw = POE_SWITCHES[poe["switch"]]
    oid = f"{POE_ADMIN_ENABLE_OID}.{sw['group']}.{poe['port']}"
    return ["snmpset", "-v2c", "-c", community, sw["address"], oid, "i", "1" if enable else "2"]
```

Replace `poe_reset` with:
```python
def poe_reset(host_name, off_seconds=5, boot_timeout_s=240):
    """Power-cycle a PoE-powered RPi by toggling its switch port over SNMP.

    The snmpset runs on the site gateway (which can reach the switch's
    management address). Needs FPGAS_POE_COMMUNITY in the environment.
    Returns True once the host answers ssh again.
    """
    host = HOSTS[host_name]
    if "poe" not in host or host["ssh_type"] != "gateway":
        print(f"  Cannot PoE-reset {host_name}: no PoE port recorded for this host")
        return False
    community = os.environ.get(POE_COMMUNITY_ENV)
    if not community:
        print(f"  Cannot PoE-reset {host_name}: {POE_COMMUNITY_ENV} is not set — power-cycle by hand")
        return False
    gateway = GATEWAYS[host["gateway"]]

    def on_gateway(argv):
        return subprocess.run(["ssh", *SSH_BASE_OPTS, gateway, shlex.join(argv)],
                              timeout=20, capture_output=True, text=True)

    print(f"  PoE reset: {host['poe']['switch']} port {host['poe']['port']} off...")
    try:
        r = on_gateway(poe_snmp_cmd(host_name, enable=False, community=community))
        if r.returncode != 0:
            print(f"  snmpset failed: {r.stderr.strip()}")
            return False
        for _ in range(off_seconds * 2):
            if not ssh_check_connectivity(host_name, timeout=1):
                break
            time.sleep(0.5)
        r = on_gateway(poe_snmp_cmd(host_name, enable=True, community=community))
        if r.returncode != 0:
            print(f"  snmpset failed: {r.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  PoE reset failed: {e}")
        return False
    print(f"  Waiting for {host_name} to boot (a Pi 5 needs > 90 s)...")
    deadline = time.monotonic() + boot_timeout_s
    while time.monotonic() < deadline:
        if ssh_check_connectivity(host_name, timeout=10):
            print(f"  {host_name} is back online")
            return True
    print(f"  {host_name} did not come back after PoE reset")
    return False
```

- [ ] **Step 4: Run tests, expect green**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check verify_hardware.py tests/
git add verify_hardware.py tests/test_verify_hardware.py
git commit -m "verify_hardware: PoE reset via SNMP pethPsePortAdminEnable on the S3300 (poe.sh is gone)"
```

---

### Task 6: Acorn programming sequence and absolute remote paths (TDD)

**Files:**
- Modify: `tests/test_verify_hardware.py`
- Modify: `verify_hardware.py` (`PROGRAM_CMD["acorn"]`, `generate_tests` remote paths, `pin-id` entry)

- [ ] **Step 1: Write the failing tests**

Append:
```python
def _pin_id_test_for(host):
    tests = [t for t in vh.generate_tests() if t["host"] == host and t["test_type"] == "pin-id"]
    assert len(tests) == 1
    return tests[0]


def test_acorn_pin_id_test_uses_absolute_paths_in_login_home():
    t = _pin_id_test_for("welland-sw2-p46")
    assert t["remote_bitstream"] == "/home/pi/pin-id_acorn.bit"
    assert t["remote_script"] == "/home/pi/test_pin-id.py"
    assert t["test_cmd"] == "python3 /home/pi/test_pin-id.py --board acorn"


def test_acorn_program_cmd_detaches_pcie_and_uses_libgpiod():
    t = _pin_id_test_for("welland-sw2-p46")
    cmd = t["program_cmd"]
    assert cmd.index("0001:01:00.0/remove") < cmd.index("openFPGALoader")
    assert "ln -sfn /dev/gpiochip15 /dev/gpiochip0" in cmd
    assert "--cable libgpiod --pins 10:9:11:8 /home/pi/pin-id_acorn.bit" in cmd
    assert cmd.rstrip().endswith("/sys/bus/pci/rescan")
    assert "rp1pio" not in cmd


def test_acorn_pin_id_artifact_matches_ci_upload_name():
    # pmod_pin_id_acorn.py calls platform.build() directly, so LiteX names the
    # output build/acorn/top.bit, and the CI job uploads build/acorn/*.bit.
    t = _pin_id_test_for("welland-sw2-p46")
    assert t["artifact"] == "pmod-pin-id-acorn-cle-215plus/top.bit"
```

- [ ] **Step 2: Run, expect failures**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v -k acorn`
Expected: 3 FAIL (paths start with `~`, program_cmd uses `rp1pio`, artifact still says `sqrl_acorn.bit`).

- [ ] **Step 3: Implement**

Replace the `"acorn"` line in `PROGRAM_CMD` with:
```python
    # Acorn on RPi 5 (docs/hardware/acorn-pinmap.md, "Pi 5" notes):
    #  1. detach the PCIe endpoint — reconfiguring an enumerated endpoint
    #     crashes the Pi 5 (2026-08-31, pi-sw2-p47);
    #  2. openFPGALoader 0.10.0 opens /dev/gpiochip0 but the header is
    #     gpiochip15 (devtmpfs symlink, lost at reboot);
    #  3. libgpiod bit-bang JTAG, pin order TDI:TDO:TCK:TMS (~16 s);
    #  4. rescan so the flash-resident endpoint (or the new design's) is back.
    "acorn": (
        "if [ -e /sys/bus/pci/devices/0001:01:00.0 ]; then"
        " echo 1 > /sys/bus/pci/devices/0001:01:00.0/remove; fi;"
        " ln -sfn /dev/gpiochip15 /dev/gpiochip0;"
        " openFPGALoader --cable libgpiod --pins 10:9:11:8 {bitstream};"
        " echo 1 > /sys/bus/pci/rescan"
    ),
```

In `generate_tests`, replace the remote path lines with:
```python
            home = remote_home(host_name)
            ext = os.path.splitext(artifact)[1]
            remote_bitstream = f"{home}/{design_name}_{board}{ext}"
            remote_script = f"{home}/test_{design_name}.py"
```
and simplify the `HOST_PROGRAM_CMD` branch to `prog_cmd = prog_template.format(bitstream=remote_bitstream, bitstream_abs=remote_bitstream)` (the `~`-resolution special case is gone; `home_dir` logic deleted).

In the `pin-id` design's `acorn` entry, change `"artifact"` to
`"pmod-pin-id-acorn-cle-215plus/top.bit"` (the name CI actually uploads —
the cherry-picked `sqrl_acorn.bit` never matched) and replace `pre_test` with:
```python
                # Stop the login console so the host script can read GPIO14/15,
                # and make sure GPIO14 is a plain input: with pin-ID loaded
                # every P2 ball is an FPGA *output*, so the Pi must not drive it.
                "pre_test": (
                    "systemctl stop serial-getty@ttyAMA0 2>&1;"
                    " pinctrl set 14 ip pn; pinctrl set 15 ip pn;"
                    " true"
                ),
```

- [ ] **Step 4: Run all tests**

Run: `uv run --extra dev pytest -q`
Expected: `17 passed` (7 pin-id + 10 verify_hardware).

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check verify_hardware.py tests/
git add verify_hardware.py tests/test_verify_hardware.py
git commit -m "verify_hardware(acorn): detach PCIe, gpiochip15 symlink, libgpiod JTAG; absolute remote paths"
```

---

### Task 7: `--repeat` and `--dry-run`

**Files:**
- Modify: `tests/test_verify_hardware.py`
- Modify: `verify_hardware.py` (`main`)

- [ ] **Step 1: Write the failing test**

```python
def test_cli_repeat_and_dry_run_flags_exist():
    import argparse
    parser = vh.build_arg_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    args = parser.parse_args(["--repeat", "3", "--dry-run", "--host", "welland-sw2-p46"])
    assert args.repeat == 3 and args.dry_run is True
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --extra dev pytest tests/test_verify_hardware.py -v -k cli`
Expected: FAIL (`AttributeError: build_arg_parser`).

- [ ] **Step 3: Implement**

Extract the parser into `build_arg_parser()` and add:
```python
    parser.add_argument("--repeat", type=int, default=1,
                        help="Run the selected tests N times in a row; stop at the first failing run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the ssh/program/test commands for each test without running them")
```
In `main`, after filtering: if `args.dry_run`, print for each test the `_build_ssh_cmd` argv for the pre-test, program and test commands, rendered with `shlex.join(argv)` so each line is a copy-pasteable shell command, and return 0. Otherwise loop `for run in range(1, args.repeat + 1)`, printing `=== Run {run}/{args.repeat} ===`, collecting results per run, and breaking out (exit 1) on the first run with any failure. The summary prints the number of complete clean runs.

- [ ] **Step 4: Run tests and a dry run**

Run: `uv run --extra dev pytest -q` → `18 passed`.
Run: `uv run python verify_hardware.py --dry-run --host welland-sw2-p46 --test pin-id`
Expected output contains a line starting `ssh -o BatchMode=yes -o ConnectTimeout=15 -o ProxyJump=tim@10.21.0.1 pi@10.21.2.46 'sudo -n sh -c '"'"'` and containing `openFPGALoader --cable libgpiod --pins 10:9:11:8 /home/pi/pin-id_acorn.bit` (the nested quoting is `shlex.join` rendering the sudo wrapper; it is correct shell).

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check verify_hardware.py tests/
git add verify_hardware.py tests/test_verify_hardware.py
git commit -m "verify_hardware: --repeat N and --dry-run"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/verify-hardware.md`

- [ ] **Step 1: Rewrite the "Network Topology" and "PoE Reset" sections**

Network Topology: replace the double-hop description with the ProxyJump one (`ssh -o ProxyJump=tim@10.21.0.1 pi@10.21.2.<port>`), the `user` field and the `sudo -n sh -c` wrapper, and note that only the six Welland Acorn hosts have been migrated to VLAN names (link to `docs/hardware/site-welland.md`). PoE Reset: SNMP `pethPsePortAdminEnable`, the `poe` host field, `FPGAS_POE_COMMUNITY`, and that a Pi 5 needs more than 90 s to return. FPGA Programming: replace the Acorn line with the four-step sequence from Task 6 and the reason for each step.

- [ ] **Step 2: Commit**

```bash
git add docs/verify-hardware.md
git commit -m "docs(verify-hardware): ProxyJump transport, sudo, SNMP PoE reset, Acorn programming sequence"
```

---

### Task 9: Code review checkpoint

- [ ] Dispatch `feature-dev:code-reviewer` on `git diff origin/main...HEAD` with this plan and the spec's §3.3 as context. Fix findings in follow-up commits (one per finding) or record why not in the PR description.

---

### Task 10: Build the gate bitstream with Vivado

**Files:** none committed (`artifacts/` is gitignored)

- [ ] **Step 1: Install build extras and build the Acorn pin-ID design with Vivado**

```bash
uv sync --extra build
. /opt/Xilinx/2025.2/Vivado/settings64.sh && \
uv run python designs/pmod-pin-id/gateware/pmod_pin_id_acorn.py --variant cle-215+ --toolchain vivado --build
```
Expected: `designs/pmod-pin-id/build/acorn/top.bit` exists (the script calls `platform.build()` directly, so LiteX's default `build_name` is `top` and there is no `gateware/` subdirectory; the header reads `7a200tfbg484`; the Vivado log shows no critical warnings about the `clk200` IBUFDS/PLL path).

- [ ] **Step 2: Stage it where `verify_hardware.py` looks**

```bash
mkdir -p artifacts/pmod-pin-id-acorn-cle-215plus
cp designs/pmod-pin-id/build/acorn/top.bit artifacts/pmod-pin-id-acorn-cle-215plus/top.bit
```

---

### Task 11: The gate — run pin-ID on hardware

- [ ] **Step 1: Listing and read-only preflight on p46**

```bash
uv run python verify_hardware.py --list --board acorn
ssh -o ProxyJump=tim@10.21.0.1 pi@10.21.2.46 'lspci -nn -s 0001:01:00.0; sudo -n ln -sfn /dev/gpiochip15 /dev/gpiochip0; sudo -n openFPGALoader --cable libgpiod --pins 10:9:11:8 --detect'
```
Expected: the listing shows six `welland-sw2-p*` hosts for every Acorn design; Sqrl `1e24:021f` enumerated; `--detect` reports idcode `0x3636093`.

- [ ] **Step 2: Run the test on p46**

```bash
uv run python verify_hardware.py --host welland-sw2-p46 --test pin-id
```
Expected: `RESULT: PASS` with the table showing GPIO15→K2, GPIO14→J2, GPIO3→J5, GPIO4→H5. If the JTAG load completes but the table is empty, the Pi is fine and the bitstream/decoder is wrong — check the gateware built after PR #10 (clock) and that `pinctrl get 14 15` shows inputs before scanning.

- [ ] **Step 3: Repeat three times, then survey the other boards**

```bash
uv run python verify_hardware.py --host welland-sw2-p46 --test pin-id --repeat 3
for h in welland-sw2-p48 welland-sw2-p29 welland-sw2-p47 welland-sw2-p43 welland-sw2-p44; do
  uv run python verify_hardware.py --host $h --test pin-id
done
```
Expected per the 2026-08-31 survey: p48 PASS; p29 FAIL on GPIO3 only (J5 open); p47 FAIL on all four (reversed); p43/p44 FAIL at programming (`found 0 devices`). Each of those FAILs is a wiring fault already in `docs/hardware/acorn-pinmap.md`, not a harness bug; anything *different* from that table is a finding to investigate before opening the PR.

- [ ] **Step 4: Record the run in the PR**

Paste the p46 ×3 output and the one-line verdict per other board into the PR description.

---

### Task 12: Open the PR

- [ ] **Step 1: Push and open**

```bash
git push -u origin acorn-pcie/00-prereqs
gh pr create --base main --title "verify_hardware: reach the Welland Acorns again (ProxyJump, sudo, SNMP PoE) + pin-ID gate" --body "<summary of tasks, the hardware results table, link to the design doc>"
```
No force-pushes; if a rebase is needed, use `git safe-force-push acorn-pcie/00-prereqs` only after the operator has been asked.
