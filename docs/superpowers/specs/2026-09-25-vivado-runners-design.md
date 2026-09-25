# Sandboxed self-hosted Vivado runners — design

Date: 2026-09-25
Status: design approved in conversation, awaiting written-spec review

## Goal

Build Xilinx bitstreams for this repository with AMD Vivado in GitHub Actions,
on self-hosted runners at `buddy.mithis.com` and
`big-storage.welland.mithis.com`, without the runners becoming a way into those
hosts, the fpgas.online networks, or the next job.

The openXC7 builds on `ubuntu-latest` stay exactly as they are. Vivado builds
are added beside them.

## Threat model

**Policy:** Vivado jobs run for pushes to `main`, tags, `workflow_dispatch`, and
pull requests whose head branch is in `fpgas-online/fpgas.online-test-designs`.
Fork pull requests never reach the runners.

**Engineering assumption:** the system is built as if *anyone* could run
arbitrary code in a job. The policy gates are one layer. The sandbox has to
hold on its own, so that a mistake in a workflow `if:`, a compromised member
account or a malicious dependency cannot turn into access to anything else.

A hostile job must not be able to:

1. Obtain a credential that outlives its job or grants anything beyond reading
   this repository.
2. Leave anything behind that a later job would see (files, processes, caches,
   modified toolchain).
3. Reach any network destination other than GitHub: not the LAN, not the
   fpgas.online fleet VLANs, not the host (except its egress proxy), not the
   other runner VMs, and not arbitrary internet hosts.
4. Starve the host or other slots of CPU, RAM or disk beyond a fixed quota, or
   run past a fixed wall-clock limit.
5. Tamper with Vivado or the golden image.

Accepted: a hostile job can produce a wrong bitstream in its own artifact, and
can use its CPU quota for its time limit. Anything built from runner output
carries the source commit and a SHA-256 that make it traceable. Nothing
publishes from inside a runner (see "Releases").

## Architecture

```
GitHub (fpgas-online org)
   ▲ outbound HTTPS only (no inbound ports on either host)
   │
┌──┴──────────── host: buddy / big-storage ─────────────────────────┐
│ vivado-runners controller (systemd, Python)  GitHub App key (0400) │
│   • N fixed slots; per slot: overlay → JIT config → boot → reap    │
│ egress proxy (bound only to the runner bridge address)             │
│   • CONNECT allowlist = GitHub hostnames only; denials logged      │
│ nftables: runner bridge → proxy:3128 only; no DNS, LAN, host       │
│                                                                    │
│  ┌── VM (KVM, one job, then destroyed) ──────────────────────┐     │
│  │ overlay qcow2 on runner-base/current      (discarded)     │     │
│  │ /opt/Xilinx ← vivado squashfs, read-only virtio disk      │     │
│  │ seed ISO    ← JIT runner config (single use)              │     │
│  │ scratch     ← fresh disk for _work        (discarded)     │     │
│  └────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────┘
```

### One fresh KVM VM per job

Each job runs in a new libvirt/KVM VM that is destroyed afterwards. It's a
hardware virtualisation boundary with no kernel shared with the host, and no
state survives between jobs. Containers (inside one long-lived VM, or on the
host) were rejected because a kernel escape would persist or reach the host.

### Credentials

* The host holds a **GitHub App** private key, readable only by the controller's
  user. The App's single permission is organisation *Self-hosted runners: read
  and write*. It is never copied into a VM.
* For each slot the controller requests a **JIT runner config**
  (`POST /orgs/fpgas-online/actions/runners/generate-jitconfig`) naming the
  runner, its labels and the runner group. The config registers exactly one
  runner for exactly one job and is spent once used. It reaches the VM on a
  read-only seed ISO.
* Runner group `vivado` is restricted to `fpgas-online/fpgas.online-test-designs`,
  so even a leaked JIT config cannot serve another repository.
* Jobs on these runners declare `permissions: contents: read`. No repository or
  organisation secrets are referenced by Vivado jobs.

### Network: only GitHub

The runner bridge (`vrbr0`, a private /24 per host) has no default route and no
DNS. Guests get `HTTPS_PROXY`/`HTTP_PROXY` pointing at the host proxy on the
bridge address. nftables on the host:

* guest → bridge address tcp/3128: accept
* guest → anything else (including the host's other addresses, the LAN, fleet
  VLANs, other guests, 53/udp+tcp): drop and log
* no forwarding for the bridge at all

The proxy (squid, SSL-bump off) allows `CONNECT :443` only to hosts on the
allowlist below and refuses plain HTTP. A request to an IP literal is refused.
Every refusal is logged with slot and runner name.

Allowlist, from GitHub's self-hosted runner network requirements
(docs.github.com, "Self-hosted runners reference", fetched 2026-09-24):

| Purpose | Hosts |
|---|---|
| Essential operations | `github.com`, `api.github.com`, `*.actions.githubusercontent.com` |
| Downloading actions | `codeload.github.com` |
| Logs, artifacts, caches | `results-receiver.actions.githubusercontent.com`, `*.blob.core.windows.net` (narrowed, see below) |
| Release assets (uv, CPython, runner) | `objects.githubusercontent.com`, `objects-origin.githubusercontent.com`, `github-releases.githubusercontent.com`, `release-assets.githubusercontent.com` |

Not allowed: ghcr / packages, Git LFS (S3), PyPI, Debian mirrors, anything else.

**`*.blob.core.windows.net` is a wildcard over every Azure storage account.**
Allowing it whole would let a job exfiltrate to, or download from, any Azure
blob. Phase 0 records the exact storage hostnames a real job uses (artifact
upload, log upload, cache) from proxy logs and narrows the rule to those names
or patterns. If GitHub's names cannot be narrowed safely, that residual risk is
an open decision (D-1).

### Python dependencies without PyPI

The build extra's LiteX-family dependencies are all `git+https://github.com/…`
and are reachable. Everything else in `uv.lock` comes from PyPI: about 20
packages including transitive ones (`meson`, `ninja`, `pyserial`,
`liteiclink`, `pyyaml`, `requests`, `packaging`, …; checked 2026-09-25). The
golden image carries a uv cache pre-warmed from the full `uv.lock` at image
build time, and the image build fails if any locked PyPI distribution is
missing from that cache. `uv sync --extra build` therefore needs PyPI for
nothing. A change that adds or bumps a PyPI dependency fails with a proxy
refusal naming `pypi.org` / `files.pythonhosted.org`, and the fix is an image
rebuild (the image's lock hash is shown in the job log to make this obvious).

## Images

### Golden runner image

`runner-base-<YYYY-MM-DD>.<n>.qcow2`, built by an admin with a script in the
runner repository, from the Debian 13 generic cloud image. It contains:

* `actions/runner` at a pinned version, started once with `--jitconfig` and
  `--disableupdate`. The runner is upgraded by rebuilding the image.
* `uv`, CPython 3.12, `git`, `make`, `gcc-riscv64-unknown-elf`, and the X11 /
  ncurses / libtinfo libraries Vivado requires
* the pre-warmed uv cache
* a boot unit that mounts the seed ISO, the Vivado disk (`ro`) at `/opt/Xilinx`
  and the scratch disk at the runner work directory; runs the runner; powers
  off when it exits, successfully or not
* no SSH server, no user with a password, no credentials

Image builds need ordinary internet access (apt, PyPI), so they run on a
separate build network, never on `vrbr0` and never from a job.

### Vivado disk

`vivado-<version>-artix7-<YYYY-MM-DD>.squashfs`, made from the existing
`/opt/Xilinx/2025.2` on desktop.buddy.mithis.com (AMD's installer needs an
interactive login), with device support trimmed to Artix-7. It is attached to
each VM as a read-only virtio disk; one copy per host serves every slot. A
squashfs block device is used rather than virtiofs so no host-side daemon parses
guest requests.

Licence: every current Vivado target is Artix-7 (xc7a35t / xc7a100t /
xc7a200t), which the free Vivado ML Standard edition covers, so no licence
server or file is needed. The Vivado disk and any image containing Vivado stay
on the two hosts and are **never** published (ghcr, releases, public mirrors):
AMD's EULA permits installation, not redistribution.

### Versions and rollback

Every image is kept by version under `/var/lib/vivado-runners/images/`:

```
runner-base-2026-09-25.1.qcow2
runner-base-2026-10-02.1.qcow2
runner-base-current -> runner-base-2026-10-02.1.qcow2
vivado-2025.2-artix7-2026-09-25.squashfs
vivado-current -> vivado-2025.2-artix7-2026-09-25.squashfs
```

* The controller resolves the `*-current` symlinks when it prepares a slot and
  records the resolved versions in the job's log line. A running VM keeps the
  images it booted with.
* **Rollback = repointing `*-current` at any earlier version.** New slots pick
  it up; nothing else changes.
* Old versions are removed only by hand, never automatically.
* A second Vivado version is added as a separate file and a separate runner
  label (`vivado-2026.1`), not by replacing `vivado-current`'s target.

## Controller

A Python package (`vivado-runners`), run as a systemd service under a dedicated
user in the `libvirt` group. Configuration per host:

```toml
[github]
org = "fpgas-online"
app_id = 0            # filled at deploy
key_file = "/etc/vivado-runners/app.pem"
runner_group = "vivado"

[slots]
count = 2
vcpus = 8
memory_gib = 24
scratch_gib = 60
wall_limit_minutes = 120
labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]
```

The numbers are starting values. Phase 0 replaces them with measured ones.

### Slot loop

One asyncio task per slot; state under `/var/lib/vivado-runners/slot-N/`.

1. Resolve `runner-base-current` and `vivado-current`.
2. Create a qcow2 overlay on the base image and a fresh sparse scratch disk.
3. Request a JIT config for runner `<host>-slot<N>-<uuid8>`; write it to a seed
   ISO.
4. `virsh create` a **transient** domain named `vr-<host>-<N>` (vCPU/RAM caps,
   `vrbr0` NIC, the four disks, no graphics, no host devices).
5. Wait for the domain to shut off, or destroy it once the wall limit passes.
6. Copy the runner's `_diag` log off the scratch disk (read-only loop mount),
   then delete overlay, scratch disk and seed ISO. If the runner never
   registered, delete it from GitHub. Go to 1.

With fixed slots and no inbound webhook, an idle slot is a booted VM waiting in
the runner's long poll. GitHub queues jobs until a slot takes one.

### Failure handling

| Failure | Handling |
|---|---|
| Controller (re)start | Destroy every `vr-<host>-*` domain, delete slot files, deregister offline runners named `<host>-*` |
| JIT request fails | Exponential backoff to 10 min; logged; slot stays empty |
| VM does not boot, or runner does not register within 5 min | Tear down and retry; after 3 consecutive failures the slot stops and logs an alert |
| Job hangs | Workflow `timeout-minutes` first; controller wall limit as backstop |
| Host free disk below threshold | No new slot is started until space returns |

### Observability

* Journal, one structured line per job: slot, runner name, GitHub run/job id
  (from `_diag`), image versions, duration, exit reason.
* Proxy refusals logged with the source slot.
* `vivado-runners status` prints each slot's state, runner, image versions and
  age.

## test-designs changes

Each `build-*.yml` gains Vivado jobs for its Xilinx design × board pairs, next
to the openXC7 jobs:

```yaml
runs-on: [self-hosted, vivado-2025.2]
if: >-
  github.event_name != 'pull_request' ||
  github.event.pull_request.head.repo.full_name == github.repository
permissions:
  contents: read
timeout-minutes: 90
```

Vivado job names start with `Vivado:` (for example `Vivado: Arty A7-35T`).
`collect-bitstreams.yml` selects the jobs it waits for with
`^(Arty|NeTV2…|Fomu|TT FPGA|netv2)`, so this prefix keeps the openXC7 bundle
independent of runner availability. A runner outage then delays only the
Vivado jobs.

The `if:` keeps fork PRs off the runners in addition to the runner group
restriction and the organisation's fork-approval policy.

### Releases

A new `release-vivado-bitstreams.yml` (on tag / `workflow_dispatch`) runs on
`ubuntu-latest`. It downloads the Vivado jobs' artifacts, runs
`designs/acorn-pcie/tools/publish_release.py` (and the equivalent for the
all-designs release), and holds `contents: write`. The runners never hold a
token that can write. This replaces today's manual publish from a build tree on
buddy.

## Repositories and ownership

* **`fpgas-online/fpgas.online-vivado-runners`** (new, Apache-2.0, standard
  repo defaults): controller, tests, image build scripts, proxy and nftables
  configuration, Ansible playbook for both hosts. The controller ships as a deb
  through the secretless `debs` Release model used by nfsroot-watchdog.
  The spec moves here once the repo exists.
* **fpgas.online-test-designs**: the Vivado jobs and the release workflow.
* **Organisation settings (Tim):** create the GitHub App and install it on the
  org; create runner group `vivado` restricted to test-designs; keep fork
  workflow approval on.

## Testing

* Unit tests: the slot state machine against fake libvirt and GitHub clients
  (successful job, boot failure, registration timeout, wall-limit kill,
  controller restart with leftover domains, JIT API errors).
* Sandbox acceptance workflow (`vivado-runner-sandbox.yml`, dispatch only),
  each check a failing step if the promise is broken:
  * DNS resolution fails; `1.1.1.1:443`, a LAN address, a fleet VLAN address
    and the host's non-bridge address are unreachable
  * the proxy refuses a non-allowlisted host and an IP literal
  * `/opt/Xilinx` is read-only
  * a marker written by run A is absent in run B (two sequential jobs)
  * no GitHub App key, no SSH keys and no `ACTIONS_*` token beyond the job's
    own are readable in the VM
* End to end: Vivado build of the Acorn UART design on the runner; the `.bit`
  header reports Vivado 2025.2 and the artifact uploads.

## Rollout

Each phase is a PR with CI green before the next starts.

| Phase | Work | Exit check |
|---|---|---|
| 0 | Probe both hosts (KVM, CPU, RAM, disk, other services and mounts to wall off); measure Vivado peak RAM for the largest design; build the trimmed squashfs and record its size; record GitHub's blob hostnames from a proxied run | Numbers and hostnames written into this spec |
| 1 | Create the runner repo; controller + unit tests; image build; proxy + nftables | Unit tests green; image boots under the controller locally |
| 2 | Deploy to buddy, 1 slot, runner group live | Sandbox acceptance workflow passes; one Vivado bitstream built |
| 3 | test-designs Vivado matrix | Full Vivado matrix green on buddy |
| 4 | big-storage joins (Vivado copied from buddy); slot counts set from Phase 0 | Jobs run on both hosts |
| 5 | Release workflow replaces the manual publish | A `vivado-bitstreams-*` release made by CI with matching SHA-256s |

## Out of scope

* Toolchains other than Vivado on these runners
* Vivado jobs for fork pull requests (the sandbox is designed for it; the
  policy stays off)
* Autoscaling beyond fixed slots
* Hardware-in-the-loop tests on the fleet Pis

## Open decisions

* **D-1** What to do if `*.blob.core.windows.net` cannot be narrowed.
* **D-2** Name of the runner repository (proposed
  `fpgas-online/fpgas.online-vivado-runners`).
* **D-3** Whether big-storage's existing workloads can give up the RAM for its
  slots; Phase 0 supplies the numbers.
