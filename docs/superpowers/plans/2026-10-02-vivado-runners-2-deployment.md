# Vivado Runners 2: Deployment and Sandbox Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ] `) syntax for tracking.

**Goal:** Put the runner controller from Plan 1 into service on a runner host, prove with a workflow that a job VM can reach GitHub and nothing else and leaves nothing behind, narrow the proxy's Azure storage rule, and document how to operate it.

**Architecture:** An Ansible playbook in the runner repo installs the `vivado-runners` package and its configuration and leaves the controller off until told otherwise. Images are built on the host. A dispatch-only workflow in fpgas.online-test-designs runs a check script inside two consecutive VMs; its results, the proxy log and the nftables counters are the evidence.

**Tech Stack:** Ansible (ansible-core, builtin modules only), libvirt/KVM, squid, nftables, GitHub Apps, GitHub Actions, Python 3 stdlib.

**Spec:** `docs/superpowers/specs/2026-09-25-vivado-runners-design.md` in `fpgas-online/fpgas.online-vivado-runners`.

**Which host.** The system does not depend on where it runs. A runner host is any Debian 13 (trixie) x86-64 machine with KVM; the playbook checks that and nothing else about it. Everything a host contributes (its name, NUMA layout, CPU count, memory, addresses) is read from the host, not written into the code, the package or the workflows. The only place a host is named is `deploy/inventory.yml`.

In this plan `<host>` is the inventory name of the host being deployed and `<name>` is its short name (the part before the first dot), which is what runner and VM names start with. Tasks 3, 4 and 6 are written once and run per host. The first host is the inventory's first entry; at the time of writing that is big-storage.welland.mithis.com. "Notes on particular hosts" at the end holds what is known about individual machines.

**This is plan 2 of 3.** It needs Plan 1 merged and its package published (or a locally built deb). Plan 3 adds the Vivado build jobs.

## Global Constraints

- **Nothing in this plan is deployed without Tim saying so for that step.** Each task that changes a host or the GitHub organisation starts by asking. Merging a PR is not permission to deploy it.
- Run the whole playbook every time. No `--tags`, no `--skip-tags`; scope with `--limit` and `-e` only.
- Never restart or stop a service on the machine the session runs on. All service changes happen on the runner host, through the playbook.
- One host first, with one slot. A further host is added only when Tim says so (Task 9).
- Nothing host-specific goes into code, package files, workflows or the check script. If a step seems to need a host's address or layout written down, it belongs in `deploy/inventory.yml` or is read from the host at run time.
- Repositories: runner code and playbook in `fpgas-online/fpgas.online-vivado-runners`; the sandbox workflow in `fpgas-online/fpgas.online-test-designs`.
- Names and addresses, from Plan 1: package `vivado-runners`; units `vivado-runners.service`, `vivado-runners-proxy.service`, `vivado-runners-firewall.service`, `vivado-runners-firewall.timer`; libvirt network `vivado-runners` on bridge `vrbr0`; host `192.168.76.1`, proxy port 3128, slot `i` at `192.168.76.<10+i>`; state in `/var/lib/vivado-runners`; config `/etc/vivado-runners/config.toml`; App key `/etc/vivado-runners/app.pem`; runner group `vivado`; labels `self-hosted`, `linux`, `x64`, `vivado-2025.2`.
- The GitHub App's private key is never committed, never printed, never copied into a VM, and never leaves Tim's machine and the runner host.
- Vivado, the Vivado disk and the runner image are copied only between Tim's own machines (from the machine with the Vivado install to a runner host). Never to GitHub, a registry or any other host.
- Over ssh to a runner host: one simple remote command per call; anything longer is a Python script copied to the host.
- Python via `uv`; no shell with loops or conditionals; ISO dates; no `/tmp`; never redirect stderr to `/dev/null`.
- PRs only, CI green, merge with `gh pr merge --merge`. A PR is ready to merge only when it is based on current `origin/main` and a sub-agent review found it good; say both when asking Tim to merge.
- When reporting a result, say what was really exercised. "CI is green" is not "it works".
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LmomwnyBcsZWKXnx2Thc2Y
  ```

## File Structure

In `fpgas.online-vivado-runners`:

```
deploy/
  ansible.cfg                 inventory path, no become by default
  inventory.yml               the runner hosts and their slot settings
  site.yml                    the whole deployment, one play
  templates/config.toml.j2    /etc/vivado-runners/config.toml
tools/
  inspect_jit.py              decode one JIT config's non-secret part, then delete the runner
  check_runner_version.py     compare the pinned runner with the latest release
.github/workflows/
  ci.yml                      + job: playbook syntax and lint
  runner-version.yml          weekly: open an issue when the image is behind
docs/
  operations.md               day-to-day procedures
  measurements.md             + section: GitHub's blob storage hostnames
host/allowed-blob-regex       narrowed in Task 7
```

In `fpgas.online-test-designs`:

```
.github/workflows/vivado-runner-sandbox.yml   dispatch-only acceptance workflow
scripts/ci/sandbox_check.py                   the checks, run inside the VM
```

## Pull requests

| PR | Repo | Tasks | Exit check |
|---|---|---|---|
| G | vivado-runners | 2 | playbook passes `--syntax-check` and `ansible-lint` in CI |
| H | test-designs | 5 | workflow file parses; script lints; nothing runs until dispatched |
| I | vivado-runners | 7 | `packaging/proxy-test.py` still green with the narrowed blob rule |
| J | vivado-runners | 8 | docs and the weekly version check; the check script ran once by hand |

Tasks 1, 3, 4, 6 and 9 change the GitHub organisation or a host and produce no PR.

---

### Task 1: GitHub organisation setup (Tim)

Only an organisation owner can do this. The executor prepares the checklist, Tim does the clicks, the executor verifies with the API.

**Interfaces:**
- Produces: App ID and installation ID (not secret, go in `deploy/inventory.yml`); the App's private key file on Tim's machine at `~/.config/vivado-runners/app.pem` (mode 0600); runner group `vivado`.

- [ ] **Step 1: Give Tim this checklist**

1. Create a GitHub App owned by the `fpgas-online` organisation (Organisation settings, Developer settings, GitHub Apps, New GitHub App):
   - Name: `fpgas-online-vivado-runners`
   - Homepage URL: `https://github.com/fpgas-online/fpgas.online-vivado-runners`
   - Webhook: **Active unticked** (the controller only makes outbound calls)
   - Organisation permissions: **Self-hosted runners: Read and write**. Nothing else, no repository permissions.
   - Where can this App be installed: **Only on this account**
2. On the App's page: note the **App ID**; "Generate a private key" and save the downloaded `.pem` as `~/.config/vivado-runners/app.pem`, mode 0600.
3. "Install App" on `fpgas-online` (it has no repository permissions, so the repository choice does not matter). The installation ID is the number at the end of the page's URL (`.../installations/<id>`).
4. Organisation settings, Actions, Runner groups, New runner group:
   - Name: `vivado`
   - Repository access: **Selected repositories**, only `fpgas.online-test-designs`
   - **Allow public repositories: ticked** (the repository is public; without this the group refuses it)
5. Organisation settings, Actions, General, "Fork pull request workflows from outside collaborators": **Require approval for all external contributors**.

- [ ] **Step 2: Verify the runner group**

Run: `gh api orgs/fpgas-online/actions/runner-groups --jq '.runner_groups[] | select(.name=="vivado") | {id, visibility, allows_public_repositories}'`
Expected: `{"id": <number>, "visibility": "selected", "allows_public_repositories": true}`.

Run: `gh api orgs/fpgas-online/actions/runner-groups/<id>/repositories --jq '[.repositories[].full_name]'`
Expected: `["fpgas-online/fpgas.online-test-designs"]` and nothing else.

- [ ] **Step 3: Verify the fork approval policy**

Run: `gh api repos/fpgas-online/fpgas.online-test-designs/actions/permissions/fork-pr-contributor-approval`
Expected: `{"approval_policy":"all_external_contributors"}`. (On 2026-09-24 it was `first_time_contributors`.)

- [ ] **Step 4: Verify the App can do what the controller needs, and nothing more**

With the runner repo checked out (Plan 1 merged), write `tmp/inspect.toml` from `debian/config.toml.example` with the real `app_id` and `installation_id`, `key_file = "/home/tim/.config/vivado-runners/app.pem"` and `host = "setup-check"`, then run Task 2's `tools/inspect_jit.py` (write that file first if Task 2 has not been done):

Run: `uv run python tools/inspect_jit.py --config tmp/inspect.toml`
Expected: it prints the runner group ID, the names of the files inside the JIT config and the non-secret `.runner` settings, and ends with `runner <id> deleted`. A `GitHub API 403` means the App lacks the permission or is not installed; a `runner group 'vivado' not found` means step 4 of the checklist is not done.

Record from its output, in `docs/measurements.md` under a new heading "JIT runner settings": whether the settings include a key about updates (for example `disableUpdate`) and its value. This answers spec difference 4 from Plan 1.

---

### Task 2: Playbook and tools

**Files (runner repo):**
- Create: `deploy/ansible.cfg`, `deploy/inventory.yml`, `deploy/site.yml`, `deploy/templates/config.toml.j2`
- Create: `tools/inspect_jit.py`
- Modify: `.github/workflows/ci.yml` (add job `deploy-lint`)

**Interfaces:**
- Consumes: package `vivado-runners` (Plan 1 Task 13); `vivado_runners.config.load`, `vivado_runners.github.GitHubClient` (Plan 1 Tasks 2, 4).
- Produces: `ansible-playbook -i deploy/inventory.yml deploy/site.yml --limit <host>` with these variables:
  - `vivado_runners_enabled` (default `false`): whether the controller runs
  - `vivado_runners_app_key_src` (optional): path on the control machine to the App key; when unset the key must already be on the host
  - `vivado_runners_deb` (optional): path on the control machine to a locally built deb, used instead of the apt repository
  - `vivado_runners_version` (optional): exact package version to install from the apt repository. Unset, the package is installed if missing and never upgraded; an upgrade is a reviewed change of this value in the inventory
  - for the group, overridable per host: `vivado_runners_slots`, `vivado_runners_vcpus`, `vivado_runners_memory_gib`, `vivado_runners_scratch_gib` (how much of a host the runners may use), and `vivado_runners_app_id`, `vivado_runners_installation_id`
  - nothing describes a host: its short name is taken from the inventory name, and the controller reads the NUMA layout, CPU count and memory from the host
- The play starts with preflight checks and changes nothing if one fails: Debian 13 on x86-64; `/dev/kvm` exists; no two inventory hosts share a short name; the host is not already running its own squid; nothing else on the host uses 192.168.76.0/24.

- [ ] **Step 1: Write the inspection tool**

`tools/inspect_jit.py`:

```python
#!/usr/bin/env python3
"""Ask GitHub for one JIT runner config, show its non-secret settings, delete the runner.

    uv run python tools/inspect_jit.py --config /etc/vivado-runners/config.toml

Proves the GitHub App can create and delete runners in the runner group, and
shows what a JIT runner is configured to do (for example whether it updates
itself). Credentials inside the config are never printed: only file names.
"""

import argparse
import base64
import json
import secrets
import sys
from pathlib import Path

from vivado_runners import config
from vivado_runners.github import GitHubClient

SECRET_WORDS = ("token", "secret", "key", "credential", "password")


def describe(encoded: str) -> None:
    files = json.loads(base64.b64decode(encoded))
    print("files in the JIT config:", ", ".join(sorted(files)))
    if ".runner" not in files:
        print("no .runner file: the JIT config format has changed; read the names above")
        return
    settings = json.loads(base64.b64decode(files[".runner"]).decode("utf-8-sig"))
    for name in sorted(settings):
        hidden = any(word in name.lower() for word in SECRET_WORDS)
        print(f"  .runner {name} = {'<hidden>' if hidden else settings[name]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("/etc/vivado-runners/config.toml"))
    args = parser.parse_args()

    cfg = config.load(args.config)
    github = GitHubClient(
        cfg.github.org, cfg.github.app_id, cfg.github.installation_id, cfg.github.key_file.read_text()
    )
    group_id = github.runner_group_id(cfg.github.runner_group)
    print(f"runner group {cfg.github.runner_group!r} has id {group_id}")
    name = f"{cfg.runner_prefix}X-inspect-{secrets.token_hex(2)}"
    jit = github.create_jit(name, group_id, list(cfg.slots.labels))
    try:
        print(f"created runner {name} (id {jit.id})")
        describe(jit.encoded_jit_config)
    finally:
        github.delete_runner(jit.id)
        print(f"runner {jit.id} deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the playbook**

`deploy/ansible.cfg`:

```ini
[defaults]
inventory = inventory.yml
interpreter_python = /usr/bin/python3
stdout_callback = default
callbacks_enabled = ansible.posix.profile_tasks

[ssh_connection]
pipelining = true
```

`deploy/inventory.yml`:

```yaml
# Runner hosts. Any Debian 13 x86-64 machine with KVM can be one: add it here
# and run the playbook. A host's entry holds only how much of it the runners may
# use; its name, NUMA layout, CPU count and memory are read from the host.
#
# App and installation IDs are not secret. The key is, and is never in this
# repository.
vivado_runners:
  vars:
    vivado_runners_app_id: 0            # from the GitHub App (Task 1)
    vivado_runners_installation_id: 0   # from the GitHub App (Task 1)
    vivado_runners_slots: 1
    vivado_runners_vcpus: 8
    vivado_runners_memory_gib: 16       # docs/measurements.md decides the real value
    vivado_runners_scratch_gib: 60
  hosts:
    big-storage.welland.mithis.com:
```

`deploy/templates/config.toml.j2`:

```
# Written by deploy/site.yml. Edit deploy/inventory.yml, not this file.
host = "{{ inventory_hostname_short }}"

[github]
org = "fpgas-online"
app_id = {{ vivado_runners_app_id }}
installation_id = {{ vivado_runners_installation_id }}
key_file = "/etc/vivado-runners/app.pem"
runner_group = "vivado"

[slots]
count = {{ vivado_runners_slots }}
vcpus = {{ vivado_runners_vcpus }}
memory_gib = {{ vivado_runners_memory_gib }}
scratch_gib = {{ vivado_runners_scratch_gib }}
wall_limit_minutes = 120
labels = ["self-hosted", "linux", "x64", "vivado-2025.2"]
```

`deploy/site.yml`:

```yaml
# The whole deployment of a Vivado runner host. Always run all of it:
#
#   cd deploy
#   ansible-playbook site.yml --limit <host> \
#       -e vivado_runners_app_key_src=$HOME/.config/vivado-runners/app.pem
#
# <host> is any entry of inventory.yml. The play is the same for every host:
# what it needs from one is checked first, and nothing about a host is assumed.
#
# The controller stays off unless -e vivado_runners_enabled=true is given.
# A changed configuration takes effect when the controller next starts; this
# playbook never restarts a running controller, because that kills its jobs.
- name: Vivado runner host
  hosts: vivado_runners
  become: true
  vars:
    vivado_runners_enabled: false
    vivado_runners_apt_url: https://fpgas.online/fpgas.online-vivado-runners
    vivado_runners_network_xml: /usr/share/vivado-runners/host/network.xml
  tasks:
    # ---- What a runner host has to be. Fail here, before changing anything. ----
    - name: The host is Debian 13 on x86-64
      ansible.builtin.assert:
        that:
          - ansible_facts.distribution == "Debian"
          - ansible_facts.distribution_major_version == "13"
          - ansible_facts.architecture == "x86_64"
        fail_msg: A runner host must be Debian 13 (trixie) on x86-64

    - name: Look for KVM
      ansible.builtin.stat:
        path: /dev/kvm
      register: vivado_runners_kvm

    - name: The host can run KVM virtual machines
      ansible.builtin.assert:
        that: vivado_runners_kvm.stat.exists
        fail_msg: /dev/kvm is missing. Enable virtualisation extensions (VT-x or AMD-V) in the firmware

    # A runner's name starts with its host's short name, and a controller removes
    # every runner and VM that carries its own name when it starts.
    - name: Every runner host has a different short name
      ansible.builtin.assert:
        that: >-
          (groups["vivado_runners"] | map("split", ".") | map("first") | unique | length)
          == (groups["vivado_runners"] | length)
        fail_msg: Two hosts in the inventory share a short name; their controllers would delete each other's runners

    - name: Look at the services already on the host
      ansible.builtin.service_facts:

    - name: The host does not already run a squid of its own
      ansible.builtin.assert:
        that: (ansible_facts.services["squid.service"] | default({})).state | default("") != "running"
        fail_msg: squid.service is running here. This play would mask it; move that service first

    - name: Look for the runner subnet on the host
      ansible.builtin.command:
        argv: [ip, -4, route, show, root, 192.168.76.0/24]
      register: vivado_runners_routes
      changed_when: false

    - name: Nothing else on the host uses 192.168.76.0/24
      ansible.builtin.assert:
        that: vivado_runners_routes.stdout_lines | reject("search", "dev vrbr0") | list | length == 0
        fail_msg: "192.168.76.0/24 is already in use here: {{ vivado_runners_routes.stdout }}"

    - name: The IDs from the GitHub App are set
      ansible.builtin.assert:
        that:
          - vivado_runners_app_id | int > 0
          - vivado_runners_installation_id | int > 0
        fail_msg: Set vivado_runners_app_id and vivado_runners_installation_id in deploy/inventory.yml

    # The package depends on squid, whose own unit would listen on every
    # interface. Mask it before it is installed; our instance is a separate unit.
    - name: The distribution's squid unit is masked
      ansible.builtin.file:
        path: /etc/systemd/system/squid.service
        src: /dev/null
        state: link
        force: true

    - name: The apt keyring directory exists
      ansible.builtin.file:
        path: /etc/apt/keyrings
        state: directory
        mode: "0755"
      when: vivado_runners_deb is not defined

    - name: The repository signing key is installed
      ansible.builtin.get_url:
        url: "{{ vivado_runners_apt_url }}/fpgas.online-vivado-runners.gpg"
        dest: /etc/apt/keyrings/vivado-runners.gpg
        mode: "0644"
      when: vivado_runners_deb is not defined

    - name: The apt repository is configured
      ansible.builtin.copy:
        dest: /etc/apt/sources.list.d/vivado-runners.list
        content: "deb [signed-by=/etc/apt/keyrings/vivado-runners.gpg] {{ vivado_runners_apt_url }}/trixie/ ./\n"
        mode: "0644"
      when: vivado_runners_deb is not defined

    # Without vivado_runners_version this installs the package if it is missing
    # and never upgrades it. An upgrade is a reviewed change to the inventory.
    - name: The package is installed from the apt repository
      ansible.builtin.apt:
        name: "vivado-runners{{ '=' ~ vivado_runners_version if vivado_runners_version is defined else '' }}"
        state: present
        update_cache: true
        install_recommends: true
      when: vivado_runners_deb is not defined

    - name: A locally built package is copied to the host
      ansible.builtin.copy:
        src: "{{ vivado_runners_deb }}"
        dest: /var/cache/vivado-runners.deb
        mode: "0644"
      when: vivado_runners_deb is defined

    - name: The locally built package is installed
      ansible.builtin.apt:
        deb: /var/cache/vivado-runners.deb
        install_recommends: true
      when: vivado_runners_deb is defined

    - name: The controller configuration is written
      ansible.builtin.template:
        src: config.toml.j2
        dest: /etc/vivado-runners/config.toml
        owner: root
        group: vivado-runners
        mode: "0640"

    - name: The GitHub App key is copied from the control machine
      ansible.builtin.copy:
        src: "{{ vivado_runners_app_key_src }}"
        dest: /etc/vivado-runners/app.pem
        owner: vivado-runners
        group: vivado-runners
        mode: "0400"
      no_log: true
      when: vivado_runners_app_key_src is defined

    - name: Look for the GitHub App key
      ansible.builtin.stat:
        path: /etc/vivado-runners/app.pem
      register: vivado_runners_app_key

    - name: The GitHub App key is present and private
      ansible.builtin.assert:
        that:
          - vivado_runners_app_key.stat.exists
          - vivado_runners_app_key.stat.mode == "0400"
          - vivado_runners_app_key.stat.pw_name == "vivado-runners"
        fail_msg: /etc/vivado-runners/app.pem is missing or not 0400 vivado-runners; pass -e vivado_runners_app_key_src=<path>

    - name: Look for the libvirt network
      ansible.builtin.command:
        argv: [virsh, -c, "qemu:///system", net-info, vivado-runners]
      register: vivado_runners_net
      changed_when: false
      failed_when: false

    - name: The libvirt network is defined
      ansible.builtin.command:
        argv: [virsh, -c, "qemu:///system", net-define, "{{ vivado_runners_network_xml }}"]
      when: vivado_runners_net.rc != 0
      changed_when: true

    - name: The libvirt network starts with the host
      ansible.builtin.command:
        argv: [virsh, -c, "qemu:///system", net-autostart, vivado-runners]
      when: "vivado_runners_net.rc != 0 or 'Autostart:      yes' not in vivado_runners_net.stdout"
      changed_when: true

    - name: The libvirt network is running
      ansible.builtin.command:
        argv: [virsh, -c, "qemu:///system", net-start, vivado-runners]
      when: "vivado_runners_net.rc != 0 or 'Active:         yes' not in vivado_runners_net.stdout"
      changed_when: true

    - name: The firewall table is loaded and re-asserted every minute
      ansible.builtin.systemd_service:
        name: "{{ item }}"
        enabled: true
        state: started
        daemon_reload: true
      loop:
        - vivado-runners-firewall.service
        - vivado-runners-firewall.timer

    - name: The egress proxy is running
      ansible.builtin.systemd_service:
        name: vivado-runners-proxy.service
        enabled: true
        state: started

    - name: The controller runs only when asked for
      ansible.builtin.systemd_service:
        name: vivado-runners.service
        enabled: "{{ vivado_runners_enabled | bool }}"
        state: "{{ 'started' if vivado_runners_enabled | bool else 'stopped' }}"
```

- [ ] **Step 3: Check the playbook locally**

Run:

```bash
cd deploy
uvx --from ansible-core --with ansible ansible-playbook site.yml --syntax-check
uvx --with ansible ansible-lint site.yml
```

Expected: `playbook: site.yml` from the first; `Passed: 0 failure(s), 0 warning(s)` from the second (when this plan was written it passed at the `production` profile). Fix what ansible-lint names; do not add a skip list.

- [ ] **Step 4: Add the CI job**

Append to `jobs:` in `.github/workflows/ci.yml`:

```yaml
  deploy-lint:
    name: Playbook syntax and lint
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Syntax
        working-directory: deploy
        run: uvx --from ansible-core --with ansible ansible-playbook site.yml --syntax-check
      - name: Lint
        working-directory: deploy
        run: uvx --with ansible ansible-lint site.yml
```

- [ ] **Step 5: Commit, push, open PR G**

```bash
git add deploy tools/inspect_jit.py .github/workflows/ci.yml
git commit -m "deploy: playbook for a runner host, and a JIT config inspector"
git push -u origin deploy
gh pr create --title "Deployment playbook and JIT config inspector" --body "One play that installs the package, writes the config, defines the libvirt network and starts the firewall and proxy. The controller stays off unless asked for. Checked with --syntax-check and ansible-lint only; it has not been run against a host (that is the next task, with Tim's go-ahead)."
```

---

### Task 3: First deployment to a host, controller off

**Interfaces:**
- Consumes: Task 1's IDs and key; PR G merged; the package published, or a deb built locally as in Plan 1 Task 13 Step 4.
- Produces: the host with the bridge, the nftables table and the proxy running, and `vivado-runners.service` stopped and disabled.

- [ ] **Step 1: Ask Tim**

"Deploy the runner host configuration to `<host>` now? It installs the `vivado-runners` package (which pulls in squid, masked), defines a new isolated libvirt network `vivado-runners` on bridge `vrbr0` (192.168.76.0/24), loads an nftables table that only affects that bridge, and starts a squid bound to 192.168.76.1. The controller stays off; no VM starts." Proceed only on yes.

- [ ] **Step 2: Record the host's state before**

Each as its own ssh call; save the outputs under `tmp/<name>-before/` in the runner repo checkout (the directory is ignored by git):

```bash
ssh <host> 'sudo -n virsh net-list --all'
ssh <host> 'sudo -n nft list ruleset'
ssh <host> 'ss -ltnH'
ssh <host> 'ip -br addr'
ssh <host> 'systemctl is-enabled squid.service'
```

The last one is expected to say `not-found` (squid is not installed yet). If it says anything else, stop: the host already runs a squid, and masking it would break something. Tell Tim.

- [ ] **Step 3: Set the IDs and run the playbook**

Set `vivado_runners_app_id` and `vivado_runners_installation_id` in `deploy/inventory.yml` (commit on a branch `deploy-ids`, PR, merge as usual), then:

```bash
cd deploy
ansible-playbook site.yml --limit <host> --diff \
  -e vivado_runners_app_key_src=$HOME/.config/vivado-runners/app.pem
```

(Add `-e vivado_runners_deb=<path to the deb>` if the apt repository is not published yet.)

Expected: `failed=0`. Run it a second time: `changed=0`. If the second run reports changes, the task that changed is not idempotent; fix it in the playbook before going on.

Then record which package version is installed and pin it, so later runs cannot change it by accident:

```bash
ssh <host> "dpkg-query -W -f '\${Version}\n' vivado-runners"
```

Set `vivado_runners_version: "<that version>"` for the `vivado_runners` group in `deploy/inventory.yml` (PR, merge).

- [ ] **Step 4: Verify on the host**

Each its own ssh call:

```bash
ssh <host> 'sudo -n virsh net-info vivado-runners'
```
Expected: `Active: yes`, `Autostart: yes`, `Bridge: vrbr0`.

```bash
ssh <host> 'ip -br addr show vrbr0'
```
Expected: `192.168.76.1/24` and **no** `inet6` address.

```bash
ssh <host> 'sudo -n nft list table inet vivado_runners'
```
Expected: the `input` and `forward` chains from `host/vivado-runners.nft`, counters at 0.

```bash
ssh <host> 'sudo -n ss -ltnpH sport = :3128'
```
Expected: exactly one listener, on `192.168.76.1:3128`, process `squid`. A listener on `0.0.0.0:3128` or `[::]:3128` means the distribution's squid is running: stop and fix the mask.

```bash
ssh <host> 'systemctl is-active vivado-runners.service vivado-runners-proxy.service vivado-runners-firewall.timer squid.service'
```
Expected, in order: `inactive`, `active`, `active`, `inactive`.

```bash
ssh <host> 'sudo -n nft list ruleset'
```
Compare with the "before" copy: the only difference is the new `table inet vivado_runners` and whatever libvirt added for `vrbr0`. Any other difference: stop and report.

- [ ] **Step 5: Check the proxy from the host itself**

The proxy only accepts clients from 192.168.76.0/24. From the host, bind the source address to the bridge:

```bash
ssh <host> 'curl -s -o /dev/null -m 20 -w "%{http_connect}\n" --interface 192.168.76.1 -x http://192.168.76.1:3128 https://api.github.com/zen'
ssh <host> 'curl -s -o /dev/null -m 20 -w "%{http_connect}\n" --interface 192.168.76.1 -x http://192.168.76.1:3128 https://pypi.org/simple/'
```

Expected: `200` then `403`. Then:

```bash
ssh <host> 'sudo -n tail -2 /var/log/vivado-runners/proxy-access.log'
```

Expected: a `TCP_TUNNEL/200 CONNECT api.github.com:443` line and a `TCP_DENIED/403 CONNECT pypi.org:443` line, both from `192.168.76.1`.

- [ ] **Step 6: Report**

Tell Tim what is now on the host (network, table, proxy; controller off), with the verification output, and what was not exercised yet (no VM has booted).

---

### Task 4: Build the images and boot one VM by hand

**Interfaces:**
- Consumes: `image/build_vivado_disk.py`, `image/build_image.py` (installed under `/usr/share/vivado-runners/image/`), `vivado-runners images` (Plan 1).
- Produces: on the host, `vivado-2025.2-<date>.squashfs` and `runner-base-<date>.1.qcow2` in `/var/lib/vivado-runners/images`, both selected by their `-current` symlinks.

- [ ] **Step 1: Ask Tim**

"Build the Vivado disk on the machine that has the Vivado install (about 30 GiB written under the runner repo's `tmp/`), copy it to `<host>`, and build the runner image there (downloads Debian's cloud image and packages; one build VM on libvirt's `default` network for about 15 minutes)?" Proceed only on yes.

- [ ] **Step 2: Build the Vivado disk where Vivado is installed**

In the runner repo checkout, using the exclusions `docs/measurements.md` chose as the default (none if the full disk is the default):

```bash
mkdir -p tmp/vivado-disk
uv run python image/build_vivado_disk.py --source /opt/Xilinx/2025.2 --images-dir tmp/vivado-disk
```

Expected last lines: `built vivado-2025.2-<date>.squashfs (<size> GiB)`.

- [ ] **Step 3: Copy it to the host**

```bash
rsync --partial --progress tmp/vivado-disk/vivado-2025.2-*.squashfs <host>:
ssh <host> 'sudo -n install -o vivado-runners -g libvirt-qemu -m 0440 -t /var/lib/vivado-runners/images vivado-2025.2-*.squashfs'
ssh <host> 'rm vivado-2025.2-*.squashfs'
ssh <host> 'sudo -n sha256sum /var/lib/vivado-runners/images/vivado-2025.2-*.squashfs'
sha256sum tmp/vivado-disk/vivado-2025.2-*.squashfs
```

Expected: the two checksums are equal. Then delete the local copy (`rm -r tmp/vivado-disk`): it contains Vivado and must not linger in a repository checkout.

- [ ] **Step 4: Build the runner image on the host**

The image's uv cache is warmed from test-designs' lock file. Fetch the two files to the host:

```bash
ssh <host> 'sudo -n -u vivado-runners mkdir -p /var/lib/vivado-runners/lock'
ssh <host> 'sudo -n -u vivado-runners curl -fsSL -o /var/lib/vivado-runners/lock/uv.lock https://raw.githubusercontent.com/fpgas-online/fpgas.online-test-designs/main/uv.lock'
ssh <host> 'sudo -n -u vivado-runners curl -fsSL -o /var/lib/vivado-runners/lock/pyproject.toml https://raw.githubusercontent.com/fpgas-online/fpgas.online-test-designs/main/pyproject.toml'
```

Start the build detached, so a dropped ssh session does not kill it (the host has `systemd-run`):

```bash
ssh <host> 'sudo -n systemd-run --unit=vivado-runners-image-build --uid=vivado-runners --gid=vivado-runners --property=SupplementaryGroups="libvirt libvirt-qemu" --collect python3 /usr/share/vivado-runners/image/build_image.py --images-dir /var/lib/vivado-runners/images --lock /var/lib/vivado-runners/lock/uv.lock --pyproject /var/lib/vivado-runners/lock/pyproject.toml'
```

Follow it, reporting to Tim at least every 5 minutes while it runs:

```bash
ssh <host> 'sudo -n journalctl -u vivado-runners-image-build --no-pager -n 30'
ssh <host> 'sudo -n virsh list --all'
```

Expected at the end: the manifest JSON, then `built runner-base-<date>.1.qcow2`. The build VM `vr-image-build` is gone from `virsh list`.

If it ends with "provisioning did not finish", the work disk is kept: read the build VM's own log with `ssh <host> 'sudo -n virt-cat -a /var/lib/vivado-runners/build/work.qcow2 /var/log/cloud-init-output.log'` (one command; the disk is the trusted build VM's, not a job's). Fix `image/provision.py` in a PR, rebuild the deb, redeploy, rebuild the image. Record what was missing.

- [ ] **Step 5: Select both images**

```bash
ssh <host> 'sudo -n -u vivado-runners vivado-runners images list'
ssh <host> 'sudo -n -u vivado-runners vivado-runners images activate vivado vivado-2025.2-<date>.squashfs'
ssh <host> 'sudo -n -u vivado-runners vivado-runners images activate base runner-base-<date>.1.qcow2'
ssh <host> 'sudo -n -u vivado-runners vivado-runners images list'
```

(`<date>` is the date in the names the first command printed.) Expected: the last listing marks both with `*`.

- [ ] **Step 6: Boot one VM through the controller, by hand**

Ask Tim: "Start the controller on `<host>` with one slot? One VM will boot, register an idle runner in the `vivado` group and wait for a job." On yes:

```bash
cd deploy
ansible-playbook site.yml --limit <host> -e vivado_runners_enabled=true
```

Then, each its own call, about a minute apart, until the runner is online or five minutes pass:

```bash
ssh <host> 'sudo -n -u vivado-runners vivado-runners status'
ssh <host> 'sudo -n virsh list'
gh api orgs/fpgas-online/actions/runners --jq '.runners[] | {name, status, busy}'
```

Expected: slot 0 `running`; domain `vr-<name>-0` running; a runner `<name>-slot0-<hex>` with `status: online`, `busy: false`.

- [ ] **Step 7: If the runner does not come online, read the VM's console**

```bash
ssh <host> 'sudo -n tail -60 /var/lib/vivado-runners/console/slot-0.log'
ssh <host> 'sudo -n journalctl -u vivado-runners --no-pager -n 40'
ssh <host> 'sudo -n tail -20 /var/log/vivado-runners/proxy-access.log'
```

Use the `superpowers:systematic-debugging` skill. The three places a first boot most plausibly fails, and where the fix goes:

| Symptom | Cause | Fix in |
|---|---|---|
| `virsh create` fails with a permission error on a disk | qemu's user cannot traverse `/var/lib/vivado-runners/slot-N` (mode 0700, controller's user) | Plan 1 `hypervisor.py`: create the slot directory 0750 with group `libvirt-qemu`, and its test |
| Console stops at "A start job is running for ... network" | the image's network unit does not match the NIC | `image/provision.py`, `network()` |
| Console shows the runner exiting at once; proxy log shows `TCP_DENIED` for a GitHub name | a hostname is missing from `host/allowed-hosts` | `host/allowed-hosts`, and add the name to `packaging/proxy-test.py` |

Each fix is a PR to the runner repo with a test that would have caught it, then a redeploy (ask Tim) and, for image changes, a new image build. The controller halts a slot after three failures in a row; restart it only through the playbook.

- [ ] **Step 8: Report**

What was exercised: a VM booted from the image under the controller and its runner registered through the proxy. What was not: no job has run, and nothing has tested what the VM can reach.

---

### Task 5: The sandbox acceptance workflow

**Files (test-designs repo, worktree `.worktrees/vivado-runner-sandbox`, branch `ci/vivado-runner-sandbox`):**
- Create: `scripts/ci/sandbox_check.py`, `.github/workflows/vivado-runner-sandbox.yml`

**Interfaces:**
- Consumes: the guest contract from Plan 1 Task 11 (user `runner`, proxy variables, `/opt/Xilinx` read-only, disk serials `vr-vivado` / `vr-seed` / `vr-scratch`).
- Produces: `python3 scripts/ci/sandbox_check.py {first|second} [host:port ...]`. The destinations built into the script are the same on every runner host (the internet, GitHub by address, the bridge host, the other slot addresses). A host's own addresses are not in the script: they are passed as arguments, from `vivado-runners sandbox-targets` run on each host. Exit status 0 only if every check passes. In `first` mode it leaves marker files; in `second` mode it requires them to be absent. It writes `runner=<RUNNER_NAME>` to `$GITHUB_OUTPUT`.

What each check proves (spec, "Threat model" items 1-5):

| Check | Proves |
|---|---|
| `user` | the job is not root and has no sudo |
| `dns` | no DNS: names cannot be resolved, so DNS cannot carry data out |
| `no default route`, `no ipv6` | nothing is routable except the bridge |
| `direct <host:port>` | the internet, the runner host on the bridge, every other slot, and (from the `extra_targets` input) the host's own addresses on its other networks cannot be reached directly. A refused connection also fails: it means the packet arrived |
| `own address is a slot address` | the VM is on the runner network and nowhere else |
| `proxy allows / refuses` | the proxy tunnels GitHub and refuses PyPI, other names, raw addresses and other ports |
| `vivado read-only` | the toolchain cannot be modified |
| `seed unreadable` | the job cannot read the (spent) runner registration or the raw Vivado disk |
| `no host secrets` | no App key, no ssh keys, no controller config in the VM |
| `markers` | a second job sees nothing the first one wrote |
| `fresh runner` | the second job ran in a different VM |

- [ ] **Step 1: Write the check script**

`scripts/ci/sandbox_check.py`:

```python
#!/usr/bin/env python3
"""Checks run inside a Vivado runner VM to prove the sandbox holds.

    python3 scripts/ci/sandbox_check.py first  [host:port ...]
    python3 scripts/ci/sandbox_check.py second [host:port ...]

`first` leaves marker files behind; `second`, run as a later job, requires
them to be gone. Standard library only: the VM has no PyPI.

The destinations built in here are the same on every runner host. What differs
per host (its own addresses) is passed as extra host:port arguments: run
`vivado-runners sandbox-targets` on each runner host and pass what it prints.
"""

import errno
import os
import pathlib
import pwd
import shutil
import socket
import sys
import urllib.parse

# The runner network is the same on every host: the host is .1, slot i is .10+i.
BRIDGE_HOST = "192.168.76.1"
SLOT_ADDRESSES = [f"192.168.76.{10 + i}" for i in range(8)]
# Must be unreachable without the proxy. A refused connection counts as reached.
UNREACHABLE = [
    ("1.1.1.1", 443),  # the internet
    ("140.82.112.3", 443),  # GitHub by address, bypassing the proxy
    (BRIDGE_HOST, 22),  # the runner host, on the bridge
    (BRIDGE_HOST, 53),
]
PROXY_ALLOWED = ["github.com:443", "api.github.com:443", "codeload.github.com:443"]
PROXY_REFUSED = [
    "pypi.org:443",
    "files.pythonhosted.org:443",
    "example.com:443",
    "1.1.1.1:443",
    "140.82.112.3:443",
    "github.com:22",
    "github.com:80",
]
MARKERS = [
    pathlib.Path.home() / "sandbox-marker",
    pathlib.Path("/var/tmp/sandbox-marker"),
    pathlib.Path(os.environ.get("RUNNER_WORKSPACE", ".")).parent / "sandbox-marker",
]

failures = 0


def report(ok: bool, name: str, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}", flush=True)


def check_user() -> None:
    name = pwd.getpwuid(os.getuid()).pw_name
    report(os.getuid() != 0 and name == "runner", "user", f"{name} (uid {os.getuid()})")
    report(shutil.which("sudo") is None, "no sudo")
    report(not os.access("/etc/shadow", os.R_OK), "cannot read /etc/shadow")


def check_dns() -> None:
    try:
        answer = socket.getaddrinfo("github.com", 443)
    except socket.gaierror as error:
        report(True, "dns", f"github.com does not resolve ({error})")
    else:
        report(False, "dns", f"github.com resolved to {answer[0][4][0]}")


def check_routes() -> None:
    lines = pathlib.Path("/proc/net/route").read_text().splitlines()[1:]
    defaults = [line.split()[0] for line in lines if line.split()[1] == "00000000"]
    report(not defaults, "no default route", f"default via {defaults}" if defaults else "")
    inet6 = pathlib.Path("/proc/net/if_inet6")
    addresses = inet6.read_text().split("\n") if inet6.exists() else []
    addresses = [a for a in addresses if a.strip()]
    report(not addresses, "no ipv6", f"{len(addresses)} address(es)" if addresses else "")


def check_direct(targets: list[tuple[str, int]]) -> None:
    for host, port in targets:
        name = f"direct {host}:{port}"
        try:
            socket.create_connection((host, port), timeout=3).close()
        except ConnectionRefusedError:
            report(False, name, "connection refused: the packet reached the destination")
        except OSError as error:
            report(True, name, f"unreachable ({error})")
        else:
            report(False, name, "connected")


def own_address() -> str:
    """The address this VM uses towards the bridge host (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect((BRIDGE_HOST, 9))
        except OSError:
            return ""
        return sock.getsockname()[0]


def other_slots() -> list[tuple[str, int]]:
    mine = own_address()
    report(mine in SLOT_ADDRESSES, "own address is a slot address", mine or "none")
    return [(address, 22) for address in SLOT_ADDRESSES if address != mine]


def proxy_status(proxy: tuple[str, int], target: str) -> str:
    with socket.create_connection(proxy, timeout=15) as sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        line = sock.makefile("rb").readline().decode(errors="replace").split()
    return line[1] if len(line) > 1 else "none"


def check_proxy() -> None:
    url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not url:
        report(False, "proxy", "HTTPS_PROXY is not set")
        return
    parsed = urllib.parse.urlparse(url)
    proxy = (parsed.hostname, parsed.port)
    for target in PROXY_ALLOWED:
        status = proxy_status(proxy, target)
        report(status == "200", f"proxy allows {target}", status)
    for target in PROXY_REFUSED:
        status = proxy_status(proxy, target)
        report(status == "403", f"proxy refuses {target}", status)


def check_vivado_read_only() -> None:
    root = pathlib.Path("/opt/Xilinx")
    settings = list(root.glob("*/Vivado/settings64.sh"))
    report(bool(settings), "vivado present", str(settings[0]) if settings else "no */Vivado/settings64.sh")
    report(bool(os.statvfs(root).f_flag & os.ST_RDONLY), "vivado mounted read-only")
    probe = root / "sandbox-write-test"
    try:
        probe.write_text("x")
    except OSError as error:
        report(error.errno in (errno.EROFS, errno.EACCES), "vivado not writable", os.strerror(error.errno))
    else:
        probe.unlink()
        report(False, "vivado not writable", "created (and removed) a file under /opt/Xilinx")


def check_disks() -> None:
    for serial in ("vr-seed", "vr-vivado", "vr-scratch"):
        device = f"/dev/disk/by-id/virtio-{serial}"
        try:
            with open(device, "rb") as f:
                f.read(512)
        except PermissionError:
            report(True, f"{serial} unreadable")
        except FileNotFoundError:
            report(False, f"{serial} unreadable", f"{device} does not exist: the disk serials have changed")
        else:
            report(False, f"{serial} unreadable", "read the raw device")


def check_no_host_secrets() -> None:
    for path in ("/etc/vivado-runners", str(pathlib.Path.home() / ".ssh"), "/run/vr-seed/jitconfig"):
        report(not os.path.exists(path), f"absent {path}")
    suspicious = sorted(n for n in os.environ if "APP_KEY" in n or "PRIVATE_KEY" in n or n.startswith("VIVADO_RUNNERS"))
    report(not suspicious, "no host secrets in the environment", ", ".join(suspicious))


def check_markers(mode: str) -> None:
    if mode == "first":
        for marker in MARKERS:
            try:
                marker.write_text(os.environ.get("RUNNER_NAME", "unknown"))
            except OSError as error:
                report(False, f"wrote {marker}", os.strerror(error.errno))
            else:
                report(True, f"wrote {marker}")
        return
    for marker in MARKERS:
        found = marker.exists()
        report(not found, f"marker gone {marker}", f"left by {marker.read_text()}" if found else "")
    first = os.environ.get("FIRST_RUNNER", "")
    mine = os.environ.get("RUNNER_NAME", "")
    report(bool(first) and bool(mine) and first != mine, "fresh runner", f"first={first} second={mine}")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("first", "second"):
        print(__doc__)
        return 2
    mode = sys.argv[1]
    extra = []
    for arg in sys.argv[2:]:
        host, _, port = arg.rpartition(":")
        extra.append((host, int(port)))

    print(f"runner {os.environ.get('RUNNER_NAME', '?')}, {os.cpu_count()} CPUs", flush=True)
    manifest = pathlib.Path("/etc/vivado-runner-image.json")
    print(manifest.read_text() if manifest.exists() else "no image manifest", flush=True)

    check_user()
    check_dns()
    check_routes()
    check_direct(UNREACHABLE + other_slots() + extra)
    check_proxy()
    check_vivado_read_only()
    check_disks()
    check_no_host_secrets()
    check_markers(mode)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as f:
            f.write(f"runner={os.environ.get('RUNNER_NAME', '')}\n")
    print(f"{failures} check(s) failed" if failures else "all checks passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: See it fail on an ordinary machine**

A check script that cannot fail proves nothing. On an ordinary development machine:

Run: `uv run python scripts/ci/sandbox_check.py first`
Expected: exit status 1 and `FAIL` lines for at least `user`, `dns`, `no default route`, `direct 1.1.1.1:443` and `proxy` (this machine has DNS, a default route, the internet and no proxy). When this plan was written it reported 15 failed checks on desktop.buddy. It writes marker files; remove them afterwards:

```bash
rm -f ~/sandbox-marker /var/tmp/sandbox-marker ../sandbox-marker
```

On a machine where `/opt/Xilinx` exists and is writable, the `vivado not writable` check creates a probe file and removes it again; check with `ls /opt/Xilinx` that only the version directories are there.

If any of those five lines says `ok`, the check is wrong: fix it before going on.

- [ ] **Step 3: Write the workflow**

`.github/workflows/vivado-runner-sandbox.yml`:

```yaml
# .github/workflows/vivado-runner-sandbox.yml
name: "Vivado runner sandbox check"

# Proves the self-hosted Vivado runners are sandboxed: two jobs, one after the
# other, each in its own throwaway VM. Run by hand after any change to the
# runner hosts, their image or their network policy.
on:
  workflow_dispatch:
    inputs:
      extra_targets:
        description: "The output of `vivado-runners sandbox-targets` from every runner host (host:port pairs that must be unreachable)"
        required: false
        default: ""

permissions:
  contents: read

jobs:
  first:
    name: "Sandbox: first VM"
    runs-on: [self-hosted, vivado-2025.2]
    timeout-minutes: 20
    outputs:
      runner: ${{ steps.check.outputs.runner }}
    steps:
      - uses: actions/checkout@v4

      - name: Sandbox checks
        id: check
        env:
          EXTRA_TARGETS: ${{ inputs.extra_targets }}
        run: python3 scripts/ci/sandbox_check.py first $EXTRA_TARGETS

      - name: Vivado runs and reports its version
        run: |
          source /opt/Xilinx/2025.2/Vivado/settings64.sh
          vivado -version | tee vivado-version.txt
          grep -q "v2025.2" vivado-version.txt

      - name: Python dependencies install without PyPI
        run: uv sync --frozen --extra build

      # Uploading exercises GitHub's blob storage through the proxy; the
      # hostnames it uses are read from the proxy log afterwards.
      - name: Upload a small artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: vivado-runner-sandbox-first
          path: vivado-version.txt
          if-no-files-found: warn

  second:
    name: "Sandbox: second VM"
    needs: first
    runs-on: [self-hosted, vivado-2025.2]
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Sandbox checks, and nothing left by the first job
        env:
          EXTRA_TARGETS: ${{ inputs.extra_targets }}
          FIRST_RUNNER: ${{ needs.first.outputs.runner }}
        run: python3 scripts/ci/sandbox_check.py second $EXTRA_TARGETS
```

- [ ] **Step 4: Lint**

Run: `uv run ruff check scripts/ci/sandbox_check.py && uv run ruff format --check scripts/ci/sandbox_check.py`
Expected: no findings.

Run: `uv run --with pyyaml python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/vivado-runner-sandbox.yml')); print('parses')"`
Expected: `parses`.

- [ ] **Step 5: Commit, push, open PR H**

```bash
git add scripts/ci/sandbox_check.py .github/workflows/vivado-runner-sandbox.yml
git commit -m "ci: sandbox acceptance workflow for the Vivado runners"
git push -u origin ci/vivado-runner-sandbox
gh pr create --title "ci: sandbox acceptance workflow for the Vivado runners" --body "A dispatch-only workflow that runs scripts/ci/sandbox_check.py in two consecutive runner VMs. Nothing runs on a pull request or push. Exercised so far: the script fails as it should on an ordinary machine. It has not yet run on a runner VM; that happens after this is merged (a dispatch-only workflow must be on the default branch to be started)."
```

---

### Task 6: Run the acceptance workflow and collect the evidence

**Interfaces:**
- Consumes: PR H merged; Task 4's idle runner.
- Produces: one green run of "Vivado runner sandbox check", and host-side evidence, recorded in `docs/operations.md` (Task 8) under "Last sandbox acceptance run".

- [ ] **Step 1: Note the host counters before**

```bash
ssh <host> 'sudo -n nft list table inet vivado_runners'
ssh <host> 'sudo -n wc -l /var/log/vivado-runners/proxy-access.log'
```

- [ ] **Step 2: Dispatch and watch**

First collect what must be unreachable from every runner host that is in service (one call per host), and join the outputs with spaces:

```bash
ssh <host> 'vivado-runners sandbox-targets'
```

It prints the host's own IPv4 addresses on every interface but the runner bridge, each as `address:22`. Then:

```bash
gh workflow run vivado-runner-sandbox.yml --repo fpgas-online/fpgas.online-test-designs --ref main -f extra_targets="<the joined output>"
gh run list --repo fpgas-online/fpgas.online-test-designs --workflow vivado-runner-sandbox.yml --limit 3 --json databaseId,headSha,status,createdAt
```

Take the run whose `createdAt` is now (address it by `databaseId` from here on; do not trust "the newest" without checking). Then:

```bash
gh run watch <databaseId> --repo fpgas-online/fpgas.online-test-designs --exit-status
```

With one slot the two jobs run one after the other, each in a new VM. Expected: both jobs succeed.

- [ ] **Step 3: Read every check line, not only the conclusion**

```bash
gh run view <databaseId> --repo fpgas-online/fpgas.online-test-designs --log
```

Expected in the first job: every line of the "Sandbox checks" step starts with `ok`, the Vivado step prints `v2025.2`, and `uv sync` finishes. In the second: every `marker gone` line is `ok` and `fresh runner` shows two different names.

If a check fails, that is a finding about the sandbox, not about the test. Use `superpowers:systematic-debugging`, fix it in the runner repo (with a test), redeploy with Tim's go-ahead, and run the workflow again. Never edit a check to make it pass.

If Vivado fails to start for a missing shared library, add the Debian package that provides it to `APT_PACKAGES` in `image/provision.py` (PR), rebuild the image, activate it, and rerun.

- [ ] **Step 4: Collect the host-side evidence**

```bash
ssh <host> 'sudo -n nft list table inet vivado_runners'
```
Expected: the `drop` counters in `input` and `forward` are greater than before: the direct connection attempts were dropped by this table.

```bash
ssh <host> 'sudo -n grep -c TCP_DENIED /var/log/vivado-runners/proxy-access.log'
ssh <host> 'sudo -n grep TCP_DENIED /var/log/vivado-runners/proxy-access.log'
```
Expected: denials from `192.168.76.10` for `pypi.org:443`, `files.pythonhosted.org:443`, `example.com:443`, `1.1.1.1:443`, `140.82.112.3:443`, `github.com:22`, `github.com:80`, and no denial for a GitHub name the job legitimately needed.

```bash
ssh <host> 'sudo -n journalctl -u vivado-runners --no-pager --since "-30min" -g "job "'
```
Expected: two `job {...}` lines with `"reason": "finished"`, different `runner` names, and the image versions.

```bash
ssh <host> 'sudo -n ls -la /var/lib/vivado-runners/slot-0'
ssh <host> 'sudo -n virsh list --all'
```
Expected: a fresh slot directory for the next idle VM (overlay created after the second job ended), and exactly one `vr-<name>-0` domain.

- [ ] **Step 5: Report to Tim**

State exactly what was exercised (the list of check lines, the Vivado version, the denials in the proxy log, the nftables counters, two jobs in two VMs) and what was not (no full bitstream build yet: Plan 3; only one host; the Azure blob rule is still the wide initial one).

---

### Task 7: Narrow the Azure blob rule (decision D-1)

**Files (runner repo):**
- Modify: `host/allowed-blob-regex`, `packaging/proxy-test.py`, `docs/measurements.md`

**Interfaces:**
- Consumes: Task 6's proxy log.
- Produces: an allowlist that matches GitHub's storage accounts and no other Azure storage account, or a decision from Tim.

- [ ] **Step 1: List the blob hostnames real jobs used**

```bash
ssh <host> 'sudo -n grep -o "CONNECT [^ ]*blob.core.windows.net:443" /var/log/vivado-runners/proxy-access.log'
```

Save the output locally and count the distinct names with a short Python snippet (`sorted(set(...))`). Record the distinct names and the date in `docs/measurements.md` under "GitHub's blob storage hostnames".

- [ ] **Step 2: Decide whether they can be narrowed**

The names are expected to share a prefix that only GitHub would own (when the plan was written, `productionresultssa0.blob.core.windows.net` resolved and answered; that suggests names of the form `productionresultssa<number>`). Read GitHub's current documentation on the same question before trusting a pattern: fetch `https://docs.github.com/en/actions/reference/runners/self-hosted-runners` and look for the storage hostnames it lists.

- If every observed name matches one documented or self-evidently GitHub-owned pattern: write that pattern. For names of the form `productionresultssa<number>` the file becomes:

  ```
  # Azure storage accounts GitHub uses for logs, artifacts and caches.
  # Observed in the proxy log on <date>; see docs/measurements.md.
  ^productionresultssa[0-9]+\.blob\.core\.windows\.net$
  ```

- If the names do not follow a pattern that excludes other Azure customers, this is decision D-1. Put it to Tim with the AskUserQuestion tool, recommended option first: (1) allow only the exact names observed, and accept that a new GitHub storage account breaks uploads until it is added; (2) keep the wildcard and accept that a job could exchange data with any Azure storage account; (3) do not allow blob storage at all, so jobs cannot upload artifacts, which makes the runners useless for building bitstreams. Record the answer in the spec.

- [ ] **Step 3: Extend the proxy test**

In `packaging/proxy-test.py`, add to `ALLOWED` one observed name (for example `"https://productionresultssa0.blob.core.windows.net/"`) and add to `REFUSED`:

```python
    "https://example.blob.core.windows.net/",
    "https://productionresultssa0.blob.core.windows.net.example.com/",
```

Run the test as in Plan 1 Task 10 Step 5.
Expected: all `ok`. Before the regex is narrowed, the first new `REFUSED` line must be `FAIL`: run the test once with the old file to see that it does catch the wide rule.

- [ ] **Step 4: Commit, PR I, deploy, re-prove**

```bash
git add host/allowed-blob-regex packaging/proxy-test.py docs/measurements.md
git commit -m "proxy: allow only GitHub's blob storage accounts"
git push -u origin narrow-blob
gh pr create --title "proxy: allow only GitHub's blob storage accounts" --body "Replaces the wildcard over every Azure storage account with the names GitHub's runners were seen to use. The proxy test now refuses another Azure account."
```

After merge and publish, set `vivado_runners_version` in `deploy/inventory.yml` to the new package version (PR, merge), ask Tim, then run the playbook. `allowed-blob-regex` is a conffile nobody edited on the host, so the upgrade replaces it: confirm with `ssh <host> 'sudo -n cat /etc/vivado-runners/allowed-blob-regex'`. The running proxy still has the old list; reload it with `ssh <host> 'sudo -n systemctl reload vivado-runners-proxy.service'` (a reload re-reads the lists and does not drop open tunnels). Rerun Task 6 Steps 2-4.
Expected: the workflow is still green (the artifact upload still works), and the proxy log shows `TCP_TUNNEL/200` for the blob name.

---

### Task 8: Operations document and the runner-version check

**Files (runner repo):**
- Create: `docs/operations.md`, `tools/check_runner_version.py`, `.github/workflows/runner-version.yml`

**Interfaces:**
- Consumes: `image/versions.toml` (Plan 1 Task 11).
- Produces: `uv run python tools/check_runner_version.py [--open-issue]`: exit 0 when the pinned runner is the latest release, 1 when it is behind.

GitHub stops sending jobs to a self-hosted runner that is more than 30 days behind the latest release. The image pins the runner, so somebody has to rebuild it. The weekly workflow opens an issue when a newer release exists.

- [ ] **Step 1: Write the version check**

`tools/check_runner_version.py`:

```python
#!/usr/bin/env python3
"""Is the runner pinned in image/versions.toml the latest actions/runner release?

    uv run python tools/check_runner_version.py              # report only
    uv run python tools/check_runner_version.py --open-issue # and open an issue when behind

Needs the `gh` CLI, authenticated (in Actions: GH_TOKEN). GitHub stops sending
jobs to runners more than 30 days behind, so a newer release means the runner
image needs rebuilding within 30 days of that release.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import tomllib

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "image" / "versions.toml"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--open-issue", action="store_true")
    args = parser.parse_args()

    pinned = tomllib.loads(VERSIONS.read_text())["runner"]["version"]
    release = json.loads(gh("api", "repos/actions/runner/releases/latest"))
    latest = release["tag_name"].removeprefix("v")
    published = release["published_at"][:10]
    if latest == pinned:
        print(f"runner {pinned} is the latest release")
        return 0

    title = f"Runner image is behind: actions/runner {latest} is out (image has {pinned})"
    print(title)
    print(f"{latest} was published on {published}; rebuild within 30 days of that date.")
    if args.open_issue:
        search = f'"{latest}" in:title'
        existing = json.loads(gh("issue", "list", "--state", "open", "--search", search, "--json", "title"))
        if any(issue["title"] == title for issue in existing):
            print("an issue is already open")
        else:
            body = (
                f"`actions/runner` {latest} was published on {published}. `image/versions.toml` pins {pinned}.\n\n"
                "GitHub stops sending jobs to runners more than 30 days behind the latest release.\n\n"
                "To do: update `[runner]` in `image/versions.toml` (version and the linux-x64 sha256 from the "
                'release notes), merge, then follow "Rebuild the runner image" in `docs/operations.md`.'
            )
            print(gh("issue", "create", "--title", title, "--body", body))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

Run it once by hand: `uv run python tools/check_runner_version.py`
Expected: either `runner 2.337.0 is the latest release` (exit 0) or the "is behind" title (exit 1). Both are correct outputs; record which one was seen.

- [ ] **Step 2: Write the weekly workflow**

`.github/workflows/runner-version.yml`:

```yaml
name: Runner version check

# Weekly: open an issue when actions/runner has a release newer than the one
# pinned in image/versions.toml.
on:
  schedule:
    - cron: "17 3 * * 1"
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  check:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Compare the pinned runner with the latest release
        env:
          GH_TOKEN: ${{ github.token }}
        # Exit status 1 means "behind", which the issue reports; the job itself stays green.
        run: uv run python tools/check_runner_version.py --open-issue || test $? -eq 1
```

- [ ] **Step 3: Write the operations document**

`docs/operations.md` (complete content; fill the "Last sandbox acceptance run" values from Task 6):

```markdown
# Operating the Vivado runners

The runner hosts are the entries of `deploy/inventory.yml`. The procedures are the same on every host. All commands run on the host as shown.
Deployments go through `deploy/site.yml`, the whole playbook every time.

## See what is happening

    sudo -u vivado-runners vivado-runners status
    sudo journalctl -u vivado-runners -g "job "          # one line per finished job
    sudo tail /var/log/vivado-runners/proxy-access.log   # every allowed and refused connection
    sudo tail -50 /var/lib/vivado-runners/console/slot-0.log
    sudo nft list table inet vivado_runners              # drop counters

A job's log line names its runner. GitHub shows the same name as the job's
runner, which ties a line to a workflow run. The proxy log's source address is
the slot: 192.168.76.10 is slot 0, .11 is slot 1, and so on.

## Stop and start

Stopping the controller destroys its VMs and kills their jobs.

    ansible-playbook site.yml --limit <host>                               # controller off
    ansible-playbook site.yml --limit <host> -e vivado_runners_enabled=true # controller on

## A slot says `halted`

A slot halts after three failed starts in a row (the VM did not boot, its
runner never registered, or it powered off without running a job). The journal
has an `ALERT` line with the reason. Read the slot's console log, fix the
cause, then restart the controller through the playbook (off, then on).

## A job fails with a proxy refusal

The log shows a `403` from 192.168.76.1 and the name of a host. If the host is
`pypi.org` or `files.pythonhosted.org`, the job needs a Python package the
image does not have: rebuild the runner image (below). The image's
`/etc/vivado-runner-image.json` records the `uv.lock` it was built from.

Any other host is refused on purpose. Adding one to `host/allowed-hosts` widens
what every job can reach: it needs a PR and Tim's agreement.

## Rebuild the runner image

Needed when test-designs' `uv.lock` changes, when `actions/runner` has a new
release (an issue is opened weekly; GitHub drops runners more than 30 days
behind), or when the image scripts change.

    sudo -u vivado-runners curl -fsSL -o /var/lib/vivado-runners/lock/uv.lock \
        https://raw.githubusercontent.com/fpgas-online/fpgas.online-test-designs/main/uv.lock
    sudo -u vivado-runners curl -fsSL -o /var/lib/vivado-runners/lock/pyproject.toml \
        https://raw.githubusercontent.com/fpgas-online/fpgas.online-test-designs/main/pyproject.toml
    sudo systemd-run --unit=vivado-runners-image-build --uid=vivado-runners --gid=vivado-runners \
        --property=SupplementaryGroups="libvirt libvirt-qemu" --collect \
        python3 /usr/share/vivado-runners/image/build_image.py \
        --images-dir /var/lib/vivado-runners/images \
        --lock /var/lib/vivado-runners/lock/uv.lock --pyproject /var/lib/vivado-runners/lock/pyproject.toml
    sudo journalctl -fu vivado-runners-image-build

The build never changes which image is in use. Select the new one:

    sudo -u vivado-runners vivado-runners images list
    sudo -u vivado-runners vivado-runners images activate base runner-base-<date>.<n>.qcow2

New VMs use it; a running VM keeps the image it booted from. Then run the
"Vivado runner sandbox check" workflow in fpgas.online-test-designs.

## Roll back an image

    sudo -u vivado-runners vivado-runners images list
    sudo -u vivado-runners vivado-runners images activate base <an earlier name>

The same command with `vivado` rolls back the Vivado disk. Old images are never
deleted automatically; remove one by hand only when it is not the current one.

## Vivado

The Vivado disk is built from an existing install with
`image/build_vivado_disk.py` and copied to the host. It and any image
containing it stay on Tim's machines: AMD's licence does not allow
redistributing Vivado. Never upload either to GitHub or a registry.

## Last sandbox acceptance run

| | |
|---|---|
| Date | <date> |
| Run | <URL of the workflow run> |
| Images | <runner-base name>, <vivado name> |
| Result | <n> checks passed in each of two VMs; Vivado <version> |
| Host evidence | <n> proxy denials from 192.168.76.10; nftables drop counters input <n>, forward <n> |
```

The angle-bracket values are filled from Task 6's real run; a committed file has none left.

- [ ] **Step 4: Commit, push, open PR J**

```bash
git add docs/operations.md tools/check_runner_version.py .github/workflows/runner-version.yml
git commit -m "docs: operating the runners; weekly check for a newer actions/runner"
git push -u origin operations
gh pr create --title "Operations document and weekly runner-version check" --body "docs/operations.md records the procedures and the last acceptance run. The version check was run once by hand; the scheduled workflow has not fired yet."
```

---

### Task 9: Scale up, and add further hosts (decision D-3)

**Interfaces:**
- Consumes: `docs/measurements.md` slot memory (Plan 1 Task 14); a green acceptance run (Task 6).
- Produces: the first host at the slot count it can carry; a recorded decision on which other hosts run builds; the procedure for adding one.

- [ ] **Step 1: Work out how many slots the host can carry**

Read the host, do not assume it:

```bash
ssh <host> 'nproc'
ssh <host> 'free -g'
ssh <host> 'uptime'
```

The slot count is the largest number that satisfies all of:

- slots x `vivado_runners_vcpus` is at most half the host's CPU threads (the host has other work);
- slots x `vivado_runners_memory_gib` is at most a quarter of the host's total memory, and less than its `available` memory with room to spare;
- at most 8 (the controller's limit).

The controller enforces a looser hard limit by itself (all the vCPUs must exist, and at most 75% of the memory): a configuration beyond that makes it exit with status 2 and a message naming the numbers. Set `vivado_runners_slots` (and `vivado_runners_memory_gib` to the measured value) for the host in `deploy/inventory.yml`. PR, merge.

A worked example with the numbers probed on 2026-09-25: a host with 88 threads and 503 GiB carries 5 slots of 8 vCPUs by the CPU rule and 7 of 16 GiB by the memory rule, so 5; a host with 12 threads and 15 GiB available carries none until memory is freed.

- [ ] **Step 2: Deploy (ask Tim) and restart the controller**

A slot-count change takes effect when the controller restarts, which kills running jobs. Check `vivado-runners status` shows no slot running a job (an idle slot is `running` with an idle runner; confirm with `gh api orgs/fpgas-online/actions/runners --jq '.runners[] | {name, busy}'` that none is `busy`), then:

```bash
cd deploy
ansible-playbook site.yml --limit <host>
ansible-playbook site.yml --limit <host> -e vivado_runners_enabled=true
```

- [ ] **Step 3: Verify**

```bash
ssh <host> 'sudo -n -u vivado-runners vivado-runners status'
ssh <host> 'lscpu --parse=CPU,NODE'
ssh <host> 'sudo -n virsh vcpupin vr-<name>-1'
gh api orgs/fpgas-online/actions/runners --jq '[.runners[] | select(.name | startswith("<name>-slot")) | .status]'
```

Expected: every slot `running` and as many `online` runners as slots. On a host whose `lscpu` output shows more than one NUMA node, slot 1's vCPUs are pinned to the CPUs of the second node (slots go round the nodes in order); on a single-node host `vcpupin` shows every vCPU free to use all CPUs. Nobody told the controller which it is.

Dispatch the sandbox workflow once more (Task 6 Step 2).
Expected: green, and the `direct 192.168.76.<n>:22` lines still `ok` although other slots' VMs now really exist at those addresses.

- [ ] **Step 4: Watch the host under load**

After Plan 3's first matrix run, or by dispatching the Acorn UART Vivado job once per slot, read:

```bash
ssh <host> 'uptime'
ssh <host> 'free -g'
```

Expected: load under the host's thread count, `available` memory not falling towards zero, swap use not growing. Report the numbers to Tim.

- [ ] **Step 5: Decide which other hosts run builds (D-3)**

Put the question to Tim with the AskUserQuestion tool, recommended option first, using the numbers from "Notes on particular hosts": (1) the first host only, if Step 4 shows it has capacity to spare; (2) add a named second host for redundancy when the first, or its network link, is down. Record the answer in the spec's "Open decisions".

- [ ] **Step 6: Adding a host (whenever one is added)**

The procedure is the same for any machine:

1. Check it is a Debian 13 x86-64 machine with KVM and enough free disk for the images (about 60 GiB) plus `vivado_runners_scratch_gib` per slot. The playbook's preflight checks refuse a host that is not.
2. Add its name under `hosts:` in `deploy/inventory.yml`, with `vivado_runners_slots` from Step 1's rule if it differs from the group's. Nothing else: no addresses, no CPU lists. PR, merge.
3. Run Task 3 (deploy, controller off), Task 4 (copy the Vivado disk, build the runner image there, boot one VM) and Task 6 (the acceptance workflow) with `--limit` set to the new host. In Task 6, `extra_targets` carries the `sandbox-targets` output of every host in service, the new one included.
4. Add anything learnt about the machine to "Notes on particular hosts".

Runners on different hosts are interchangeable to a workflow: they carry the same labels, the same image contract and the same network policy. A job cannot tell, and must not need to know, which host it landed on.

---

## Notes on particular hosts

Deployment knowledge about individual machines. None of it is used by the code, the package or the workflows.

| Host | Probed 2026-09-25 | Notes |
|---|---|---|
| big-storage.welland.mithis.com | 88 threads (2 NUMA nodes), 503 GiB, about 477 GiB available, 2.7 TiB free on `/`, libvirt and docker running, no VMs | The first runner host. If ssh to its name hangs, use `HostName=2404:e80:a137:111::155` with `HostKeyAlias=big-storage.welland.mithis.com`. It also carries backups under `/backups` and `/space*`; the runners use only `/var/lib/vivado-runners` |
| buddy.mithis.com | 12 threads, 125 GiB, about 15 GiB available and 24 GiB in swap, 4 other VMs running | A public host with a routed IPv6 /56. It has no memory to spare today. On a public host the `no ipv6` check and the before/after nftables comparison of Task 3 matter most |
| desktop.buddy.mithis.com | 12 threads, 31 GiB | Not a runner host (no libvirt). It has the Vivado 2025.2 install the Vivado disk is built from |

---

## Self-review checklist (done when writing this plan)

- Spec coverage: organisation settings (Task 1); Ansible deployment (Tasks 2-3); first image build and boot, moved here from Phase 1 (Task 4); sandbox acceptance workflow with every check the spec lists, plus the proxy and IPv6 checks the design added (Tasks 5-6); the blob wildcard, D-1 (Task 7); observability and rollback procedures (Task 8); Phase 4 scale-up, D-3 and the procedure for any further host (Task 9). The end-to-end Vivado bitstream build is Plan 3's first PR.
- Names: `vivado_runners_*` variables are the same in `inventory.yml`, `config.toml.j2` and `site.yml`; unit, path and address names are Plan 1's; the disk serials in `sandbox_check.py` are Plan 1 Task 5's.
- Every host-changing step asks Tim first.
- Host independence: no task writes a host's name, address, CPU list or memory into code, package files, workflows or the check script. Host names appear in `deploy/inventory.yml`, in "Notes on particular hosts", and in this plan's statement of which host is first.
