# fpgas-verify: how it is used in fpgas.online

You run fpgas.online's fleet and want to know how the check is installed and run there, what it sends the
site, how a deploy reaches it and how to collect every Pi's result.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

| What | How |
|---|---|
| Install | every netbooted Pi at a site shares one read-only NFS root, built with `fpgas-online-all-boards` (infra `roles/onpi/tasks/fpga_verify.yml`) |
| Publishing | the root carries `/etc/fpgas-verify/fleet.ini` with `[verify]` and `publish = on` (infra `roles/onpi`); without it the check sends nothing and the site never lists the board |
| When | `fpgas-verify.service` runs it once per boot, and only then: to check a Pi again, reboot it. It starts after `fpgas-fleet-agent.service` and before `fpgas-tt.service` (ordering only); time limit 30 minutes |
| State | `/var/lib` is on the root's tmpfs overlay, so every boot is a first run and `changed` never fires |
| No board | Orange Pis, or a Pi whose board is off, report `missing`, a fail; the Pi still boots and takes ssh |
| Result | anything but `pass` leaves the unit failed; the summary is in `journalctl -b -u fpgas-verify` |
| Site | the fleet app ([site](https://github.com/fpgas-online/fpgas.online-site) `fleet/src/fleet/services.py`) keeps each Pi's state for **this boot**: `verifying` from `fpga-verifying` until `fpga-verified`, then its result. `/fleet/` lists them |
| Gate | with `FPGAS_REQUIRE_VERIFIED = True` (infra `site_require_fpga_verified`, on for Welland), `/fpgas/` offers only Pis whose state is `pass` |

## Events

The check tells the site what it is doing as it goes. `fleet-event` (from
[setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi)) sends each over MQTT to
`fpgas/<site>/pi/<serial>/event`. The names and details are `EVENTS` in
[`runner.py`](../../verify/src/fpgas_online_verify/runner.py):

| Event | When | Details |
|---|---|---|
| `fpga-verifying` | the check starts | `started_at` |
| `fpga-board-found` | for each board found | `board`, `variant` (`-` for a Tiny Tapeout board, which says what it is later), `where` (PCI slot, USB path or JTAG IDCODE) |
| `fpga-no-board` | no board was found | `reason` |
| `fpga-board-identified` | exactly once for each board found: an Acorn once PCIe and JTAG have said who it is, any other board before its tests; a board whose check stops first, or that is not checked (`--test` naming none of its tests), from what finding it showed | `schema` (`fpga-identity/1`) and the board's [identity](../identity.md) |
| `fpga-test-started` | each test starts | `board`, `test` |
| `fpga-test-finished` | each test ends | `board`, `test`, `result`, `reason` |
| `fpga-verified` | the check is done | the report, flattened: `result`, `mode`, `reason`; per board `board0` (`netv2 a7-35 fail`), `board0_reason`, `board0_tests` (`uart=pass ddr=fail spiflash=pass`), `board0_not_run` (the names in `not_run`, when there are any), `board0_left_running` (the design's name) or `board0_warnings`, `board0_bitstreams`, `board0_state_*`, `board0_identity_*` |

* `board` is the board's name, or `name@where` when there are two of a kind.
* `fpga-verifying` and the progress events each wait at most 15 s, so a broker that is down does not hold up
  the check; `fpga-verified` waits at most 60 s.
* If an event before `fpga-verified` cannot be sent, no more progress events are tried that run, but
  `fpga-verified` still is.
* A failure to send is reported on stderr and does not change the result; the report stays in
  `/run/fpgas-online/verify.json`.
* Nothing is sent without `publish = on` (above). With it, `--test` runs and `--no-publish` still send nothing.

The progress events of an Acorn passing every test, in order, with their details (the check run against the
tests' fake Acorn, [`tests/acorn_fakes.py`](../../tests/acorn_fakes.py); the last 12 are cut):

```text
fpga-board-found {"board": "acorn", "variant": "cle-215+", "where": "0001:01:00.0"}
fpga-test-started {"board": "acorn", "test": "pcie-link"}
fpga-test-finished {"board": "acorn", "test": "pcie-link", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "pcie-bar0"}
fpga-test-finished {"board": "acorn", "test": "pcie-bar0", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "rp1-pio"}
fpga-test-finished {"board": "acorn", "test": "rp1-pio", "result": "pass", "reason": ""}
fpga-test-started {"board": "acorn", "test": "jtag"}
fpga-test-finished {"board": "acorn", "test": "jtag", "result": "pass", "reason": ""}
fpga-board-identified {"board": "acorn", "kind": "acorn", "variant": "cle-215+", "bdf": "0001:01:00.0", "soc_model": "cle-215+", "identifier": "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-21 14:23:32", "build": "operational", "dna": "0x0054b48664b04854", "idcode": "0x13636093", "idcode_version": "1", "idcode_part_number": "0x3636", "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A200T", "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180", "flash": "S25FL256S", "flash_size_bytes": "33554432", "flash_status": "0x00", "flash_config": "0x02", "flash_quad": "true", "flash_uid": "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf", "flash_uid_bits": "128", "flash_uid_state": "read", "flash_uid_opcode": "0x4b", "flash_sfdp": "none", "flash_source": "pcie", "schema": "fpga-identity/1"}
```

They come between `fpga-verifying` and `fpga-verified`.

## How a deploy picks up new packages

1. A commit lands on `main`. When CI is green, [`collect-bitstreams.yml`](../../.github/workflows/collect-bitstreams.yml)
   uploads the packages to that build's own release, `build-<version>` (for example `build-0.0.post795`).
2. [fpgas-online/apt](https://github.com/fpgas-online/apt) pulls them into <https://apt.fpgas.online> within 15 minutes.
3. Infra CI (`nfsroot-build.yml`) builds the NFS root image with the latest packages, as
   `ghcr.io/fpgas-online/nfsroot:ci-<run>`; on infra `main` it moves `bookworm-armhf` once a virtual Pi has
   netbooted it.
4. An operator runs infra `site.yml --limit fpgas.online` (optionally `-e img_nfsroot_image=…:ci-<run>`), which
   unpacks the image on tweed.
5. Each Pi's `nfsroot-watchdog` reboots it in its own slot, 20 s apart (a two-switch site takes about 33 minutes).
6. Each Pi runs the new `fpgas-verify` at boot and publishes the result; the gate follows.

## Collecting every Pi's result

[`scripts/collect_verify_status.py`](../../scripts/collect_verify_status.py) reads every Pi's report, unit state,
installed version and (with no report) journal over SSH. It only reads, so it is safe while boards are in use.

```bash
uv run --no-project python scripts/collect_verify_status.py \
    --ssh-config ../fpgas.online-infra/ansible/ssh.cfg            # every port on both Welland switches
uv run --no-project python scripts/collect_verify_status.py --host 10.21.2.47 --json tmp/verify.json
```

* It goes through tweed (`ansible@10.99.21.2`) as `root` to `10.21.<switch>.<port>`: switch 1 ports 1-40 and
  switch 2 ports 1-48, except sw2 p30 (not on the fpgas root). See `--help` for `--jump`, `--ports`, `--host`, ….
* Exit: 2 if the jump host is unreachable; 1 if no Pi, or some Pi, could not be read; else 0.
* The Pis share one host key, kept as `fpgas-netboot-pi` in `~/.config/fpgas-online/netboot_known_hosts`
  (learnt on first use). After a deliberate rekey:
  `ssh-keygen -R fpgas-netboot-pi -f ~/.config/fpgas-online/netboot_known_hosts`.
* The site's `/fleet/` page shows the same overall result per Pi, but not the tests.
