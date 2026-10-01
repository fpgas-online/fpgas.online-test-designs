#!/usr/bin/env python3
"""Collect the latest fpgas-verify result from every fpgas.online Pi at a site, as a markdown table.

Each Pi is read over SSH through the site's jump host, read-only: the boot's report
(/run/fpgas-online/verify.json), the state of fpgas-verify.service, the installed fpgas-online-verify
version, and, when there is no report, the end of the unit's journal. Nothing is loaded, run, stopped or
rebooted, so it is safe while other people use the boards.

That report is what the Pi published as its `fpga-verified` fleet-event, which the site's `/fleet/` pages
and its `verified_serials` gate read; this shows every test in it, not just the overall result.

    uv run --no-project python scripts/collect_verify_status.py \\
        --ssh-config ../fpgas.online-infra/ansible/ssh.cfg
    uv run --no-project python scripts/collect_verify_status.py --host 10.21.2.47 --json tmp/verify.json

By default it tries every access port on both Welland switches (Pi on switch s, port p = 10.21.s.p) but
the Orange Pis' FEL host (sw2 p30), and lists the ports with no Pi on them at the end. It first checks the
jump host, and exits 2 if that cannot be reached; it exits 1 if it read no Pi at all, if a Pi answered but
could not be read, or if an address given with --host did not answer.

Every Pi boots the same netboot root, so they share one host key, which survives root rebuilds (infra
keeps the root's /etc/ssh/ssh_host_* out of the image rsync). It is checked under one alias,
`fpgas-netboot-pi`, in its own known-hosts file (--known-hosts), learned on first use. After a deliberate
rekey, forget it with `ssh-keygen -R fpgas-netboot-pi -f <that file>` (never -H). The jump host's key is
checked as the SSH config says. Run it from a host that can reach the jump host: the WireGuard network or
the site LAN.
"""

import argparse
import collections
import concurrent.futures
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

DEFAULT_JUMP = "ansible@10.99.21.2"  # tweed, the Welland gateway, as fpgas.online-infra's automation reaches it
DEFAULT_PORTS = "1:1-40 2:1-48"  # gsm7252ps-s2 (sw1) access ports 1-40, s3300-1 (sw2) 1-48
DEFAULT_EXCLUDE = "2:30"  # the Orange Pis' FEL host: not on the fpgas root, and it refuses the key
DEFAULT_KNOWN_HOSTS = "~/.config/fpgas-online/netboot_known_hosts"
HOST_KEY_ALIAS = "fpgas-netboot-pi"  # every Pi shares the netboot root's host key
SUBNET = "10.21"
SSH_TIMEOUT = 60

BOARD_TITLES = {
    "acorn": "Acorn",
    "arty": "Arty A7",
    "netv2": "NeTV2",
    "tt": "TT FPGA",
    "fomu": "Fomu EVT",
    "pcie-other": "Unrecognised PCIe FPGA",
}
# The Acorn module claims every Xilinx or SQRL PCIe endpoint, but only these are Acorns it recognised.
ACORN_KINDS = ("fpgas-online", "sqrl-factory")
REASON_MAX = 140
# What ssh says when the jump host could not forward to the port: there is no Pi there. Anything else (a
# timeout, a refused key) is a Pi, or the jump host, that answered badly.
NO_PI = re.compile(r"channel \d+: open failed|stdio forwarding failed")

# Runs on the Pi under `python3 -`: read-only, stdlib only, prints one JSON object.
REMOTE = r"""
import json, subprocess

def run(*argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)

def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None

unit = {}
for line in run("systemctl", "show", "fpgas-verify.service", "-p", "LoadState", "-p", "ActiveState",
                "-p", "SubState", "-p", "Result", "-p", "ExecMainStatus",
                "-p", "ExecMainExitTimestamp")[1].splitlines():
    k, _, v = line.partition("=")
    unit[k] = v
report = read("/run/fpgas-online/verify.json")
journal = None
if report is None:
    journal = run("journalctl", "-b", "-u", "fpgas-verify.service", "--no-pager", "-o", "cat", "-n", "15")[1]
print(json.dumps({
    "hostname": (read("/etc/hostname") or "").strip(),
    "boot_id": (read("/proc/sys/kernel/random/boot_id") or "").strip(),
    "model": (read("/proc/device-tree/model") or "").strip("\0\n"),
    "unit": unit,
    "version": run("dpkg-query", "-W", "-f=${Version}", "fpgas-online-verify")[1].strip() or None,
    "report": report,
    "journal": journal,
}))
"""


# -- which Pis ------------------------------------------------------------------------------------------------


def parse_ports(spec):
    """(switch, port) pairs from a spec: "1:1-40 2:1-48,50" -> [(1, 1), ..., (1, 40), (2, 1), ..., (2, 48), (2, 50)].

    A malformed spec is a ValueError that says what was expected."""
    out = []
    for part in spec.split():
        switch, _, ports = part.partition(":")
        try:
            if not ports:
                raise ValueError
            for item in ports.split(","):
                first, _, last = item.partition("-")
                out += [(int(switch), p) for p in range(int(first), int(last or first) + 1)]
        except ValueError:
            raise ValueError(f"{part!r}: expected SWITCH:PORTS, e.g. 2:1-48 or 1:10,12,14-18") from None
    return out


def address(switch, port):
    return f"{SUBNET}.{switch}.{port}"


def name_from_address(ip):
    """10.21.2.47 -> pi-sw2-p47, the name the site gives that port's Pi; anything else as it is."""
    m = re.fullmatch(re.escape(SUBNET) + r"\.(\d+)\.(\d+)", ip)
    return f"pi-sw{m.group(1)}-p{m.group(2)}" if m else ip


def sort_key(name):
    m = re.fullmatch(r"pi-sw(\d+)-p(\d+)", name)
    return (0, int(m.group(1)), int(m.group(2)), "") if m else (1, 0, 0, name)


# -- reading one Pi -------------------------------------------------------------------------------------------


def _ssh_base(ssh_config, connect_timeout):
    argv = ["ssh"]
    if ssh_config:
        argv += ["-F", str(ssh_config)]
    return [*argv, "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}"]


def ssh_argv(ip, jump=DEFAULT_JUMP, ssh_config=None, user="root", connect_timeout=10,
             known_hosts=DEFAULT_KNOWN_HOSTS):  # fmt: skip
    """ssh to one Pi, running REMOTE from stdin. The -o options apply to the Pi only, not the jump host."""
    argv = [
        *_ssh_base(ssh_config, connect_timeout),
        # Every Pi has the netboot root's one host key: checked under one alias, whatever the address.
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", f"HostKeyAlias={HOST_KEY_ALIAS}",
        "-o", "CheckHostIP=no",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "HashKnownHosts=no",
        "-o", "ForwardAgent=no",
    ]  # fmt: skip
    if jump:
        argv += ["-J", jump]
    return [*argv, f"{user}@{ip}", "python3", "-"]


def jump_argv(jump, ssh_config=None, connect_timeout=10):
    """A no-op on the jump host, to check it can be reached before trying every port through it."""
    return [*_ssh_base(ssh_config, connect_timeout), "-o", "HashKnownHosts=no", jump, "true"]


def collect_one(ip, options):
    argv = ssh_argv(ip, options.jump, options.ssh_config, options.user, options.connect_timeout,
                    options.known_hosts)  # fmt: skip
    try:
        r = subprocess.run(argv, input=REMOTE, capture_output=True, text=True, timeout=SSH_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"address": ip, "error": f"no answer within {SSH_TIMEOUT} s"}
    if r.returncode != 0:
        err = [line for line in (r.stderr or "").splitlines() if line.strip()]
        record = {"address": ip, "error": "; ".join(err[-3:]) or f"ssh exited {r.returncode}"}
        if NO_PI.search(r.stderr or ""):
            record["no_pi"] = True
        return record
    return parse_remote(ip, r.stdout)


# -- making sense of it -------------------------------------------------------------------------------------


def parse_remote(ip, text):
    """One Pi's status record from what REMOTE printed."""
    try:
        raw = json.loads(text)
    except ValueError:
        return {"address": ip, "error": f"unreadable answer: {text.strip()[:200]!r}"}
    record = {
        "address": ip,
        "host": raw.get("hostname") or name_from_address(ip),
        "model": raw.get("model", ""),
        "boot_id": raw.get("boot_id", ""),
        "version": raw.get("version"),
        "unit": raw.get("unit", {}),
    }
    try:
        report = None if raw.get("report") is None else json.loads(raw["report"])
    except ValueError:
        return {**record, "error": "/run/fpgas-online/verify.json is not JSON"}
    return {**record, **summarize(report, record["unit"], raw.get("journal")), "report": report}


def summarize(report, unit, journal=None):
    """{"status", "reason", "checked_at", "boards"} from a verify.json report and the unit's state.

    Without a report: "verifying" while the unit runs, "not installed" with no unit, else "no report".
    """
    if report is None:
        if unit.get("LoadState") == "not-found":
            return {"status": "not installed", "reason": "no fpgas-verify.service", "boards": []}
        if unit.get("ActiveState") == "activating":
            return {"status": "verifying", "reason": "fpgas-verify is running", "boards": []}
        lines = [line for line in (journal or "").splitlines() if line.strip()]
        why = lines[-1] if lines else f"unit {unit.get('ActiveState', '?')}/{unit.get('Result', '?')}"
        return {"status": "no report", "reason": why, "boards": []}
    boards = []
    for b in report.get("boards", []):
        name = b.get("board", "?")
        if name == "acorn" and b.get("kind", (b.get("found") or {}).get("kind")) not in ACORN_KINDS:
            name = "pcie-other"
        boards.append({
            "board": name,
            "variant": b.get("variant") or "-",
            "result": b.get("result", "?"),
            "tests": [(t.get("test", "?"), t.get("result", "?")) for t in b.get("tests", [])],
            "reason": b.get("reason", ""),
        })  # fmt: skip
    out = {"status": report.get("result", "?"), "reason": report.get("reason", ""),
           "checked_at": report.get("checked_at"), "boards": boards}  # fmt: skip
    if unit.get("ActiveState") == "activating":
        out["note"] = "a new check is running; this is the previous report"
    return out


def board_title(name):
    return BOARD_TITLES.get(name, name)


def model_short(model):
    """A short name for a Pi model: "Raspberry Pi 3 Model B Plus Rev 1.3" -> "Pi 3B+",
    "Xunlong Orange Pi PC" -> "Orange Pi PC"."""
    m = re.match(r"Raspberry Pi (Compute Module )?(\d+)(?: Model ([AB])( Plus)?)?", model or "")
    if m:
        return ("CM" if m.group(1) else "Pi ") + m.group(2) + (m.group(3) or "") + ("+" if m.group(4) else "")
    return re.sub(r"^Xunlong ", "", model or "") or "-"


def short(text, limit=REASON_MAX):
    text = re.sub(r"\s+", " ", text or "").strip().replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def tests_cell(tests):
    cells = [f"{name}={'**' + result + '**' if result != 'pass' else result}" for name, result in tests]
    return " ".join(cells) or "-"


def rows(records):
    """One table row per board found, or one per Pi that found none."""
    out = []
    for r in records:
        checked = (r.get("checked_at") or "-").replace("+00:00", "Z")
        if not r["boards"]:
            out.append([r["host"], model_short(r.get("model")), "-", "-", r["status"], "-", short(r.get("reason")),
                        checked, r.get("version") or "-"])  # fmt: skip
        for b in r["boards"]:
            reason = b["reason"] or (r.get("reason") if len(r["boards"]) == 1 else "")
            out.append([r["host"], model_short(r.get("model")), board_title(b["board"]), b["variant"], b["result"],
                        tests_cell(b["tests"]), short(reason), checked, r.get("version") or "-"])  # fmt: skip
    return out


def by_board(records):
    """{board title: {"pis": n, "results": Counter, "tests": {test: Counter}}}."""
    out = {}
    for r in records:
        for b in r["boards"]:
            entry = out.setdefault(board_title(b["board"]), {"pis": 0, "results": collections.Counter(), "tests": {}})
            entry["pis"] += 1
            entry["results"][b["result"]] += 1
            for test, result in b["tests"]:
                entry["tests"].setdefault(test, collections.Counter())[result] += 1
    return out


def markdown(records, unreachable, collected_at):
    found = [r for r in records if "error" not in r]
    lines = [f"Collected {collected_at} from {len(found)} Pis by `scripts/collect_verify_status.py`.", ""]
    lines += ["| Board | Pis | Result | Tests (passed / run) |", "|---|---|---|---|"]
    for title, entry in sorted(by_board(found).items()):
        results = ", ".join(f"{k} {v}" for k, v in sorted(entry["results"].items()))
        tests = ", ".join(f"{t} {c['pass']}/{sum(c.values())}" for t, c in entry["tests"].items())
        lines.append(f"| {title} | {entry['pis']} | {results} | {tests or '-'} |")
    no_board = collections.Counter(r["status"] for r in found if not r["boards"])
    if no_board:
        lines.append(f"| (no board) | {sum(no_board.values())} | "
                     + ", ".join(f"{k} {v}" for k, v in sorted(no_board.items())) + " | - |")  # fmt: skip
    lines += ["", "| Host | Pi | Board | Variant | Result | Tests | Reason | Checked (UTC) | fpgas-online-verify |",
              "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    lines += ["| " + " | ".join(row) + " |" for row in rows(found)]
    failed = [r for r in records if "error" in r]
    if failed:
        lines += ["", "Could not be read: " + ", ".join(f"{r['address']} ({short(r['error'], 60)})" for r in failed)]
    if unreachable:
        lines += ["", f"No Pi answered on {len(unreachable)} ports: {compact(unreachable)}."]
    return "\n".join(lines) + "\n"


def compact(addresses):
    """["10.21.1.1", "10.21.1.2", "10.21.1.3", "10.21.2.5"] -> "sw1 p1-3; sw2 p5"."""
    ports = collections.defaultdict(list)
    other = []
    for ip in addresses:
        m = re.fullmatch(re.escape(SUBNET) + r"\.(\d+)\.(\d+)", ip)
        if m:
            ports[int(m.group(1))].append(int(m.group(2)))
        else:
            other.append(ip)
    parts = []
    for switch in sorted(ports):
        runs, nums = [], sorted(ports[switch])
        start = prev = nums[0]
        for n in [*nums[1:], None]:
            if n is not None and n == prev + 1:
                prev = n
                continue
            runs.append(f"p{start}" if start == prev else f"p{start}-{prev}")
            if n is not None:
                start = prev = n
        parts.append(f"sw{switch} " + ",".join(runs))
    return "; ".join(parts + other)


def is_unreachable(record):
    """No Pi there at all (the jump host could not forward to it), as opposed to a Pi that answered badly."""
    return bool(record.get("no_pi"))


# -- the command ---------------------------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--jump",
        default=os.environ.get("FPGAS_JUMP_HOST", DEFAULT_JUMP),
        help=f"the jump host, user@host ('' for none; default $FPGAS_JUMP_HOST or {DEFAULT_JUMP})",
    )
    parser.add_argument(
        "--ssh-config",
        type=pathlib.Path,
        default=os.environ.get("FPGAS_SSH_CONFIG"),
        help="an ssh_config for the jump host and identity, e.g. fpgas.online-infra's "
        "ansible/ssh.cfg (default $FPGAS_SSH_CONFIG, else your own)",
    )
    parser.add_argument(
        "--known-hosts",
        default=os.environ.get("FPGAS_NETBOOT_KNOWN_HOSTS", DEFAULT_KNOWN_HOSTS),
        help=f"where the netboot Pis' shared host key is kept, as {HOST_KEY_ALIAS} "
        f"(default $FPGAS_NETBOOT_KNOWN_HOSTS or {DEFAULT_KNOWN_HOSTS})",
    )
    parser.add_argument("--user", default="root", help="the login on the Pis (default root)")
    parser.add_argument(
        "--ports",
        default=DEFAULT_PORTS,
        help=f"SWITCH:PORTS ... to try, the Pi at 10.21.SWITCH.PORT (default {DEFAULT_PORTS!r})",
    )
    parser.add_argument(
        "--exclude",
        default=DEFAULT_EXCLUDE,
        help=f"SWITCH:PORTS ... not to try (default {DEFAULT_EXCLUDE!r}, the Orange Pis' FEL host; '' for none)",
    )
    parser.add_argument("--host", action="append", help="read only this address (repeatable); overrides --ports")
    parser.add_argument("--connect-timeout", type=int, default=10, help="seconds for each SSH connection")
    parser.add_argument("--parallel", type=int, default=8, help="Pis read at once (default 8)")
    parser.add_argument("--json", type=pathlib.Path, help="also write every record, with the full reports, here")
    options = parser.parse_args(argv)
    try:
        excluded = set(parse_ports(options.exclude))
        ports = [sp for sp in parse_ports(options.ports) if sp not in excluded]
    except ValueError as e:
        parser.error(str(e))
    options.known_hosts = os.path.expanduser(options.known_hosts)
    pathlib.Path(options.known_hosts).parent.mkdir(parents=True, exist_ok=True)

    if options.jump:
        try:
            r = subprocess.run(jump_argv(options.jump, options.ssh_config, options.connect_timeout),
                               capture_output=True, text=True, timeout=SSH_TIMEOUT, check=False)  # fmt: skip
            why = (r.stderr or "").strip() or f"ssh exited {r.returncode}"
        except subprocess.TimeoutExpired:
            r, why = None, f"no answer within {SSH_TIMEOUT} s"
        if r is None or r.returncode != 0:
            print(f"collect_verify_status: cannot reach the jump host {options.jump}: {why}", file=sys.stderr)
            return 2

    addresses = options.host or [address(s, p) for s, p in ports]
    collected_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with concurrent.futures.ThreadPoolExecutor(max_workers=options.parallel) as pool:
        records = list(pool.map(lambda ip: collect_one(ip, options), addresses))
    unreachable = [r["address"] for r in records if is_unreachable(r)]
    records = [r for r in records if not is_unreachable(r)]
    records.sort(key=lambda r: sort_key(r.get("host") or name_from_address(r["address"])))
    sys.stdout.write(markdown(records, unreachable, collected_at))
    if options.json:
        options.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"collected_at": collected_at, "pis": records, "unreachable": unreachable}
        options.json.write_text(json.dumps(payload, indent=2) + "\n")
    read = [r for r in records if "error" not in r]
    if not read:
        print("collect_verify_status: no Pi could be read", file=sys.stderr)
        return 1
    if options.host and unreachable:
        print(f"collect_verify_status: no Pi at {', '.join(unreachable)}", file=sys.stderr)
        return 1
    return 1 if len(read) < len(records) else 0


if __name__ == "__main__":
    sys.exit(main())
