# Sandboxed self-hosted Vivado runners — design

Date: 2026-09-25
Status: design approved in conversation. Revised 2026-10-03 with what writing the
implementation plans found, and to make the design independent of which
machines the runners are on (see "Implementation plans" at the end).

## Goal

Build Xilinx bitstreams for this repository with AMD Vivado in GitHub Actions,
on self-hosted runners on our own hardware, without the runners becoming a way
into the machines they run on, the networks around them, or the next job.

How the system works does not depend on where it runs. A runner host can be
any machine that meets "Host requirements" below; which machines are used is a
deployment choice recorded in one inventory file.

The openXC7 builds on `ubuntu-latest` stay exactly as they are. Vivado builds
are added beside them.

## Host requirements

A runner host is a Debian 13 (trixie) x86-64 machine with the CPU
virtualisation extensions KVM needs. Nothing else about it is assumed:

* **Nothing host-specific is in the code, the package, the VM image or the
  workflows.** No host name, address, CPU list or memory size. The only place a
  host is named is the deployment inventory.
* **A host is described by itself, not by configuration.** The controller reads
  the host's short name (the prefix of its runner and VM names), its NUMA
  layout, its CPU count and its memory at run time. On a host with several NUMA
  nodes it keeps each VM's vCPUs and memory on one node and spreads the slots
  across the nodes; on a single-node host it pins nothing.
* **The only per-host settings say how much of the host the runners may use:**
  the number of slots and each slot's vCPUs, memory and scratch disk. The
  controller refuses a configuration the host it starts on cannot carry (more
  vCPUs than it has, or more than 75% of its memory).
* **The runner network is private to each host and identical on all of them**
  (bridge `vrbr0`, `192.168.76.0/24`, not routed anywhere), so the firewall
  table, the proxy configuration and the VM image are the same everywhere.
* **Deployment checks the requirements and changes nothing if one is not met:**
  Debian 13 on x86-64; `/dev/kvm` exists; the host does not already run its own
  squid; nothing else on it uses `192.168.76.0/24`; no two runner hosts share a
  short name (a controller removes every runner and VM carrying its own name
  when it starts).
* **Runners on different hosts are interchangeable.** They carry the same
  labels and the same image, so a workflow selects runners by label only and a
  job cannot tell which host it is on.
* **The sandbox check does not know any host either.** Its built-in list of
  destinations that must be unreachable is the same everywhere. Each host's own
  addresses are supplied when the check is run, from
  `vivado-runners sandbox-targets` on that host.

What every host deployment must respect, whichever machine it is:

* A host may already run docker and libvirt, whose rules live in the
  iptables-nft `ip filter`/`nat` tables. The runner rules go in a separate nft
  table (`inet vivado_runners`) with a higher-priority `forward` and `input`
  hook, so they apply regardless of other tools' chains.
* `vrbr0` gets **no IPv6** (no address, no RA, `disable_ipv6=1`). Whatever
  global IPv6 the host has must never reach a guest.
* Nothing of the host's is shared into guests, and the controller's paths stay
  under `/var/lib/vivado-runners`.

### Candidate hosts (probed 2026-09-25)

Deployment knowledge, not part of the design.

| | big-storage.welland.mithis.com | buddy.mithis.com |
|---|---|---|
| CPU | 2× Xeon Gold 6152, 88 threads, 2 NUMA nodes | i7-8700, 12 threads |
| RAM | 503 GiB, ~477 GiB available | 125 GiB, **~15 GiB available, 24 GiB in swap** |
| Load (1/5/15) | 2.4 / 3.9 / 4.0 | 5.5 / 5.6 / 6.2 |
| KVM / libvirt | `/dev/kvm`, libvirtd active, no running VMs | `/dev/kvm`, libvirtd active, 4 running VMs (siliconprawn-backup, desktop, checker/data-wafer-space) |
| Free disk | 2.7 TiB on `/` | 230 GiB on `/` |
| OS | Debian 13, 6.12.73 | Debian 13, 6.12.41 |
| Network | Welland LAN `10.1.8.0/21` + IPv6; docker running | public Hetzner host, `95.216.246.231/26` + a routed IPv6 /56 |
| Vivado | none | 2025.2 in the `desktop` VM (desktop.buddy), ~50 GiB |

big-storage has the capacity and is deployed first. buddy has no spare memory
today (D-3). Any other machine that meets the requirements can be added the
same way.

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
   ▲ outbound HTTPS only (no inbound ports on a runner host)
   │
┌──┴──────── a runner host (any Debian 13 x86-64 KVM machine) ──────┐
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

* `actions/runner` at a pinned version, started once with `--jitconfig`.
  GitHub stops sending jobs to a runner more than 30 days behind the latest
  release, so the image is rebuilt at least monthly; a weekly check opens an
  issue when a newer release exists. (`--disableupdate` is a `config.sh` flag
  and a JIT runner never runs `config.sh`; Plan 2 records what a JIT config
  says about self-update.)
* `uv`, CPython 3.12, `git`, `make`, `gcc-riscv64-unknown-elf`, and the X11 /
  ncurses / libtinfo libraries Vivado requires
* the pre-warmed uv cache
* a boot unit that mounts the seed (an ISO 9660 image on a read-only virtio
  disk, found by its serial), the Vivado disk (`ro`) at `/opt/Xilinx`
  and the scratch disk at the runner work directory; runs the runner; powers
  off when it exits, successfully or not
* no SSH server, no `sudo`, no user with a password, no credentials
* `UV_PYTHON` set to the Python the cache was built for, and
  `UV_PYTHON_DOWNLOADS=never`

Image builds need ordinary internet access (apt, PyPI), so they run on a
separate build network, never on `vrbr0` and never from a job.

### Vivado disk

`vivado-<version>-<YYYY-MM-DD>.squashfs`, made from the existing
`/opt/Xilinx/2025.2` on desktop.buddy.mithis.com (AMD's installer needs an
interactive login). That install is ~50 GiB (`data` 19, `tps` 9.4, `Vivado`
7.3, `lnx64` 5.5, `gnu` 4.5, `Vitis` 3.7) and already carries few device
families: `data/parts` is 3.4 GiB of which Artix-7 is 271 MiB. Trimming
device support therefore saves little. Phase 0 records the compressed size and
checks whether `Vitis/` and `data/xsim` can be left out without breaking a
LiteX Vivado build. It is attached to
each VM as a read-only virtio disk; one copy per host serves every slot. A
squashfs block device is used rather than virtiofs so no host-side daemon parses
guest requests.

Licence: every current Vivado target is Artix-7 (xc7a35t / xc7a100t /
xc7a200t), which the free Vivado ML Standard edition covers, so no licence
server or file is needed. Versions that do need one are a later phase: see
"Vivado licences". The Vivado disk and any image containing Vivado stay
on the runner hosts and are **never** published (ghcr, releases, public mirrors):
AMD's EULA permits installation, not redistribution.

### Versions and rollback

Every image is kept by version under `/var/lib/vivado-runners/images/`:

```
runner-base-2026-09-25.1.qcow2
runner-base-2026-10-02.1.qcow2
runner-base-current -> runner-base-2026-10-02.1.qcow2
vivado-2025.2-2026-09-25.squashfs
vivado-current -> vivado-2025.2-2026-09-25.squashfs
```

* The controller resolves the `*-current` symlinks when it prepares a slot and
  records the resolved versions in the job's log line. A running VM keeps the
  images it booted with.
* **Rollback = repointing `*-current` at any earlier version.** New slots pick
  it up; nothing else changes.
* Old versions are removed only by hand, never automatically.
* A second Vivado version is added as a separate file and a separate runner
  label (`vivado-2026.1`), not by replacing `vivado-current`'s target.

## Vivado licences

Some Vivado versions and device families need a licence file, and a
node-locked licence is tied to one MAC address: Vivado runs only on a machine
that has a network device with exactly that address.

### Phase one: only versions that need no licence file

The first deployment supports only licence-free Vivado (2025.2 Standard, which
covers every current target). Nothing handles a licence file, and the design
makes sure none gets in by accident, because **a job can read everything in its
VM**:

* The Vivado disk is attached, readable, to every job's VM. Its build refuses a
  source tree holding a `.lic` file that is tied to a machine (a `HOSTID=` other
  than `ANY`/`DEMO`, or a `SERVER`/`USE_SERVER` line). The generic licences AMD
  ships inside the product are `HOSTID=ANY` and are fine. Checked on
  2026-10-03: `/opt/Xilinx/2025.2` holds two `.lic` files, both generic.
* The runner image build copies no licence, sets no `XILINXD_LICENSE_FILE` or
  `LM_LICENSE_FILE`, and creates no `~/.Xilinx`.
* The sandbox acceptance check fails if a VM has either variable set, a
  `~/.Xilinx`, or a machine-tied `.lic` file under `/opt/Xilinx` or the home
  directory.

In phase one each VM has one network card, with the fixed per-slot MAC
(`52:54:00:76:00:<slot>`) that ties its address and its proxy log lines to the
slot. That MAC is not a licence identity.

### Later phase: versions that need a licence file

Not built in the first rollout. The design, so that phase one does not block it:

* **A licence seat** is three things that travel together: the licence file,
  the MAC address it is locked to, and the runner label of the Vivado version
  it unlocks. A VM's MAC is ours to choose, so we pick the MAC and request the
  licence for it. A seat is therefore not tied to any physical machine and can
  be assigned to any runner host, in the deployment inventory.
* **The VM gets a network device with exactly that MAC.** It is a second
  virtio device whose only job is to carry the address: link down, not on the
  runner bridge. The first device keeps its per-slot MAC, so addressing, the
  firewall and the proxy log are unchanged, and two VMs never put the same MAC
  on one network.
* **A seat is in at most one running VM.** It is bound to one slot on one host.
  The controller refuses a configuration with the same MAC twice, and
  deployment refuses a seat assigned to two hosts. That is also what a
  node-locked licence permits: one machine.
* **The licence file lives on the host only** (`/etc/vivado-runners/licences/`,
  readable by the controller alone). It is never in a repository, the
  inventory, the runner image, the shared Vivado disk or a log. A licensed
  slot's VM gets it on its own read-only disk; other slots' VMs do not.
* **Jobs choose a licensed version by label**, like any other runner.

To be verified when this is built, with a real licensed version:

* that the version's licence check finds the MAC on a second device that is
  link-down and has a modern interface name. Older FlexLM releases looked only
  at `eth0`-style names. If it does not, the licence MAC goes on the first
  device and the slot's address mapping follows the seat;
* the exact list of what needs a licence (which versions, parts and IP cores).
* that the runner's job-started hook can register masked values (the log
  masking below depends on it).

**What cannot be prevented, and what follows from it.** Vivado runs as the
job, so the job must be able to read a node-locked licence file. A job that
*wants* to leak it can print it to the (public) log or put it in an artifact,
and the network sandbox does not stop that, because GitHub is the one place a
VM may talk to. A leaked node-locked licence is usable by anyone who sets
their MAC to match. So for licensed slots:

* **Who may run code there is the real barrier**, not the sandbox. Licensed
  slots are a separate runner group and label, used only by workflows on
  trusted refs. This is the one place the design does not hold against
  "anyone".
* **Accidental leaks are engineered against:** the file is outside the
  workspace and home directory, so artifact globs and `tar` of a build tree do
  not pick it up; a runner job-started hook registers the licence's key strings
  as masked values, so a stray `cat` shows `***` in the log; the artifact
  staging script refuses a file that looks like a licence; and the phase-one
  guards above still apply to every unlicensed slot.
* **The alternative that removes the exposure** is a floating licence: a
  licence server on the host side holds the file, and VMs only check a licence
  out over the network, so no job ever sees the file. It needs a floating
  licence (a different, dearer product), a firewall opening from job VMs to the
  server's ports, and the server (a closed-source daemon fed by hostile VMs) in
  a VM of its own. Which of the two to build is decision D-4.

## Controller

A Python package (`vivado-runners`), run as a systemd service under a dedicated
user in the `libvirt` group. The configuration file describes no host; the
same file is valid on any machine, apart from how many slots it should run:

```toml
[github]
org = "fpgas-online"
app_id = 0            # filled at deploy
key_file = "/etc/vivado-runners/app.pem"
runner_group = "vivado"

[slots]
count = 4             # how much of this host the runners may use
vcpus = 8
memory_gib = 16
scratch_gib = 60
wall_limit_minutes = 120
labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]
```

Measured on desktop.buddy on 2026-10-02 (12 threads, Vivado 2025.2): the
largest design (Acorn PCIe SoC, xc7a200t) peaks at 3.3 GB and takes 8.5
minutes; a UART SoC 2.8 GB and 3.5 minutes. Slot memory is the peak plus 4 GiB
for the guest, rounded up to a multiple of 4 and never under 16: **16 GiB**.
The earlier 24 GiB was a guess. Plan 1 re-measures with `/usr/bin/time -v`.

### Slot loop

One thread per slot (every hypervisor call is a blocking subprocess); state
under `/var/lib/vivado-runners/slot-N/`.

1. Resolve `runner-base-current` and `vivado-current`.
2. Create a qcow2 overlay on the base image and a fresh sparse scratch disk.
3. Request a JIT config for runner `<host>-slot<N>-<uuid8>`; write it to a seed
   ISO.
4. `virsh create` a **transient** domain named `vr-<host>-<N>` (vCPU/RAM caps,
   `vrbr0` NIC, the four disks, no graphics, no host devices).
5. Wait for the domain to shut off, or destroy it once the wall limit passes.
6. Delete overlay, scratch disk and seed ISO. If GitHub still lists the
   runner, it never ran a job: delete it. Go to 1.

The host never mounts or parses a disk a job VM has written to. (An earlier
draft copied the runner's `_diag` log off the scratch disk; that would have
the host read a filesystem a hostile job controls.)

With fixed slots and no inbound webhook, an idle slot is a booted VM waiting in
the runner's long poll. GitHub queues jobs until a slot takes one.

### Failure handling

| Failure | Handling |
|---|---|
| Controller (re)start | Destroy every `vr-<host>-*` domain, delete slot files, deregister every runner named `<host>-slot*` (its VM is gone, whatever GitHub's status says) |
| JIT request fails | Exponential backoff to 10 min; logged; slot stays empty |
| VM does not boot, runner does not register within 5 min, or the VM powers off without having run a job | Tear down and retry; after 3 consecutive failures the slot stops and logs an alert |
| Job hangs | Workflow `timeout-minutes` first; controller wall limit as backstop |
| Host free disk below threshold | No new slot is started until space returns |

### Observability

* Journal, one structured line per job: slot, runner name, image versions,
  duration, exit reason. GitHub's jobs API reports the same runner name as
  `runner_name`, which ties a line to a workflow run.
* Proxy refusals logged with the source slot.
* `vivado-runners status` prints each slot's state, runner, image versions and
  age.

## test-designs changes

One new workflow, `Build: Vivado` (`build-vivado.yml`), runs one job per
design × board × variant from a Python matrix. Each job is:

```yaml
runs-on: [self-hosted, vivado-2025.2]
if: >-
  github.event_name != 'pull_request' ||
  github.event.pull_request.head.repo.full_name == github.repository
permissions:
  contents: read
timeout-minutes: 90
```

It is a separate workflow, not jobs inside each `build-*.yml`, because
`collect-bitstreams.yml` waits for every other workflow run of the commit to
finish, and takes artifacts only from finished runs. A Vivado job inside
`build-uart-test.yml` would hold that run open while it waits for a runner, so
a runner outage would stall the openXC7 bundle. The separate workflow is left
out of the bundle by name. Vivado job names also start with `Vivado:`, which
the bundle's job-name pattern (`^(Arty|NeTV2…|Fomu|TT FPGA|netv2)`) cannot
match. A runner outage then delays only the Vivado jobs. Vivado checks must
not become required status checks, for the same reason.

The matrix is 39 jobs: `uart`, `spi-flash-id`, `ddr-memory`, `pmod-loopback`
and `pmod-pin-id` on Arty A7-35, NeTV2 A7-35/A7-100 and the three Acorn
variants; `ethernet-test` on Arty and NeTV2; and the Acorn PCIe SoC in three
variants, plain and golden. Two things found while planning:

* On `main` no LiteX SoC design builds with `--toolchain vivado`:
  `patch_yosys_template()` asserts on the Vivado toolchain. Plan 3 starts with
  that one-function fix.
* `pcie-enumeration` is not in the matrix: under Vivado it defines `pcie_s7`
  twice. The fix exists only on the unmerged pull request #14.

The `if:` keeps fork PRs off the runners in addition to the runner group
restriction and the organisation's fork-approval policy.

### Releases

A new `release-vivado-bitstreams.yml` (on tag / `workflow_dispatch`) runs on
`ubuntu-latest`. It downloads the Vivado jobs' artifacts, runs
`designs/acorn-pcie/tools/publish_release.py`, and holds `contents: write`.
The all-designs release (`vivado-bitstreams-v0.0-496-gf162f60`, 2026-04-17) was
made by `scripts/publish_vivado_bitstreams.py`, which exists only on the
unmerged pull request #14 and also does the building. Phase 5 adds a smaller
script that only assembles a release from CI artifacts, keeping that release's
file names, `manifest.json` schema and `SHA256SUMS` format. The runners never
hold a token that can write. This replaces today's manual publish from a build
tree on buddy.

## Repositories and ownership

* **`fpgas-online/fpgas.online-vivado-runners`** (new, Apache-2.0, standard
  repo defaults): controller, tests, image build scripts, proxy and nftables
  configuration, Ansible playbook for both hosts. The controller ships as a deb
  in a signed apt repository on GitHub Pages, built and published with
  `mithro/apt-repo-action` as nfsroot-watchdog is. The spec and plans move
  here once the repo exists.
* **fpgas.online-test-designs**: the Vivado jobs and the release workflow.
* **Organisation settings (Tim):** create the GitHub App and install it on the
  org; create runner group `vivado` restricted to test-designs (with "allow
  public repositories" on, since the repository is public); require approval
  for fork workflows from all external contributors.

## Testing

* Unit tests: the slot state machine against fake libvirt and GitHub clients
  (successful job, boot failure, registration timeout, wall-limit kill,
  controller restart with leftover domains, JIT API errors).
* Sandbox acceptance workflow (`vivado-runner-sandbox.yml`, dispatch only),
  each check a failing step if the promise is broken:
  * DNS resolution fails; `1.1.1.1:443`, the bridge host, every other slot
    address, and the host's own addresses on its other networks (supplied per
    host, not written into the check) are unreachable
  * the proxy refuses a non-allowlisted host, an IP literal, and a port other
    than 443; there is no default route and no IPv6 address
  * the job is not root, has no `sudo`, and cannot read the seed disk
  * `/opt/Xilinx` is read-only
  * a marker written by run A is absent in run B (two sequential jobs)
  * no GitHub App key, no SSH keys and no `ACTIONS_*` token beyond the job's
    own are readable in the VM
  * no licence environment variable and no licence file tied to a machine
* End to end: Vivado build of the Acorn UART design on the runner; the `.bit`
  header reports Vivado 2025.2 and the artifact uploads.
* The squid allowlist's behaviour is also tested in the runner repo's CI,
  against real destinations, without a VM.

## Rollout

Each phase is a PR with CI green before the next starts.

| Phase | Work | Exit check |
|---|---|---|
| 0 | Host inventory is done (above). Measure Vivado peak RAM for the largest design; build the squashfs and record its size; find out what `uv sync` needs with PyPI blocked | Numbers written into `docs/measurements.md` |
| 1 | Create the runner repo; controller + unit tests; image build scripts; proxy + nftables; package | Unit tests green; proxy allowlist test green; package builds and installs |
| 2 | Deploy to the first host, 1 slot, runner group live; first image build and first boot (the machine with the Vivado install has no libvirt); record GitHub's blob hostnames from the proxy log | Sandbox acceptance workflow passes |
| 3 | test-designs: the `patch_yosys_template()` fix, then one design end to end, then the whole matrix | Full Vivado matrix green |
| 4 | Raise the first host to the slot count it can carry; add further hosts by the same procedure if D-3 says so | Matrix runs in parallel; host load stays within limits |
| 5 | Release workflow replaces the manual publish | A `vivado-bitstreams-*` release made by CI with matching SHA-256s |
| later | Vivado versions that need a licence file ("Vivado licences"); needs its own plan and decision D-4 | A licensed version builds on a licensed slot; the licence is absent from every other VM |

## Out of scope

* Toolchains other than Vivado on these runners
* Vivado versions that need a licence file, in the first rollout (designed in
  "Vivado licences", built later)
* Vivado jobs for fork pull requests (the sandbox is designed for it; the
  policy stays off)
* Autoscaling beyond fixed slots
* Hardware-in-the-loop tests on the fleet Pis

## Open decisions

* **D-1** What to do if `*.blob.core.windows.net` cannot be narrowed.
* **D-2** Decided 2026-10-02: the runner repository is
  `fpgas-online/fpgas.online-vivado-runners`.
* **D-3** Which hosts run builds besides the first. buddy has ~15 GiB
  available and is already swapping, so even a 16 GiB slot needs its other VMs
  trimmed first; big-storage alone may be enough. Adding any host is the same
  procedure (Plan 2, Task 9).
* **D-4** (not needed until licensed Vivado versions are built) Node-locked
  licence files in trusted-only licensed slots, or a floating licence server
  so that no job ever sees the file.
* **CI-1 to CI-6** are decisions about the test-designs workflows (who
  publishes the first CI-made release, the Acorn PCIe release order, pull
  request #14, the Arty A7-100T, the full matrix on every push, failing on
  missed Vivado timing). They are set out at the end of Plan 3.

## Implementation plans

In `docs/superpowers/plans/`:

1. `2026-10-02-vivado-runners-1-runner-repo.md`: the runner repository
   (rollout Phases 0 and 1).
2. `2026-10-02-vivado-runners-2-deployment.md`: deployment to a runner host
   and the sandbox proof (Phases 2 and 4).
3. `2026-10-02-vivado-runners-3-test-designs-ci.md`: the Vivado workflow and
   releases in test-designs (Phases 3 and 5).
