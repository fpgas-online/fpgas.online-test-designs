"""fpgas-verify: find the board (or boards) this host is set up for, check each, and compare with last time.

  * One board (`fpga-board = arty`, fpgas-arty-verify, or --board arty): only that board is looked for. Not
    finding it is "missing", which is fatal, whatever else is attached: nothing else is looked for.
  * `fpga-board = auto` (fpgas-online-multi-board / -all-boards): every installed board is looked for,
    first the ones visible without driving anything (USB and PCI IDs), and only if none is, the ones found by
    driving something (the NeTV2's JTAG scan). Finding none is "missing", which is fatal.

Then each board found is checked (its board module), and what it reported as its state (identity, flash) is
compared with what was recorded last time (state.py): any difference is "changed", which is fatal, unless
--update, which records what was found instead.
"""

import datetime
import json
import pathlib
import sys

from . import config, state
from .board import installed
from .core import Problem, flatten, hold_lock, pci_devices, publish, usb_devices, worst

SCHEMA_VERSION = 2
REPORT = pathlib.Path("/run/fpgas-online/verify.json")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def find(boards, mode, options, usb, pci):
    """[(board, host, found)] to check, and how they were chosen. A board that is not there is a Problem."""
    if mode != config.AUTO:
        board = boards.get(mode) or next((b for b in boards.values() if b.slug == mode), None)
        if board is None:
            have = ", ".join(boards) or "none"
            raise Problem("error", f"this host is set up for {mode!r}, but no such board module is installed "
                                   f"(fpgas-online-{mode}-tools?); installed: {have}")  # fmt: skip
        host = board.facts(options.get("port"))
        found = board.find(host, usb, pci)
        if not found:
            raise Problem(
                "missing", f"no {board.title} found: this host is set up for one, and nothing else is looked for"
            )
        return [(board, host, f) for f in found], f"configured: {board.name}"
    if not boards:
        raise Problem("error", "fpga-board = auto, but no board module is installed (fpgas-online-<board>-tools)")
    hosts = {name: b.facts(options.get("port")) for name, b in boards.items()}
    spotted = [(b, hosts[n], f) for n, b in boards.items() for f in b.spot(hosts[n], usb, pci)]
    if spotted:
        return spotted, "auto: USB/PCI IDs"
    if options.get("no_probe"):
        how = "auto: USB/PCI IDs, probing disabled"
    else:
        probed = [(b, hosts[n], f) for n, b in boards.items() if b.probes for f in b.probe(hosts[n])]
        if probed:
            return probed, "auto: probed (" + ", ".join(sorted({b.name for b, _, _ in probed})) + ")"
        how = "auto: USB/PCI IDs, then probing"
    raise Problem("missing", f"none of the installed boards ({', '.join(boards)}) was found ({how})")


def _keys(targets):
    """A state key per board found: its name, or with more than one of a kind, name@where."""
    names = [b.name for b, _, _ in targets]
    keys = []
    for (_, _, found), name in zip(targets, names):
        where = found.get("bdf") or found.get("usb") or found.get("idcode") or str(len(keys))
        keys.append(name if names.count(name) == 1 else f"{name}@{where}")
    return keys


def compare_state(report, targets, reports, update, path):
    """Compare what the boards reported as their state with the recorded state; record it when asked."""
    current = {k: r["state"] for k, r in zip(_keys(targets), reports) if "state" in r}
    recorded = state.load(path)
    info = {"file": str(path)}
    if update or recorded is None:
        if report["result"] in ("missing", "error") and not update:
            info["recorded"] = False
            return info
        state.save(current, report["checked_at"], path)
        info["recorded"] = "--update" if update else "first run"
        return info
    changes = state.differences(recorded, current)
    if changes:
        info["changes"] = changes
    return info


def verify(options, boards=None, usb=None, pci=None, mode=None):
    boards = installed() if boards is None else boards
    report = {"schema_version": SCHEMA_VERSION, "result": "pass", "checked_at": _now(), "boards": []}
    try:
        if options.get("board"):
            report["mode"], report["configured_by"] = options["board"], "command line"
        elif mode:
            report["mode"], report["configured_by"] = mode
        else:
            mode_value, path = config.configured(options.get("mode_dir", config.MODE_DIR),
                                                 options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
            report["mode"], report["configured_by"] = mode_value, str(path)
        usb = usb_devices() if usb is None else usb
        pci = pci_devices() if pci is None else pci
        targets, report["chosen_by"] = find(boards, report["mode"], options, usb, pci)
    except Problem as p:
        report.update(result=p.result, reason=p.reason)
        if p.result == "missing":  # say what was recorded, if anything: nothing is recorded now
            report["state"] = compare_state(report, [], [], False, options.get("state", state.STATE))
        return report
    reports = []
    for board, host, found in targets:
        try:
            with hold_lock(board.lock, board.title):
                reports.append(board.check(host, found, options))
        except Problem as p:
            reports.append({"board": board.name, "found": found, "result": p.result, "reason": p.reason})
    report["boards"] = reports
    report["result"] = worst(r["result"] for r in reports)
    report["state"] = compare_state(report, targets, reports, options.get("update"), options.get("state", state.STATE))
    if report["state"].get("changes"):
        report["result"] = worst([report["result"], "changed"])
    return report


# -- telling people ------------------------------------------------------------------------------------------


def details(report):
    """The fleet-event's details: flat strings."""
    out = {"result": report["result"], "mode": report.get("mode", "-")}
    if "reason" in report:
        out["reason"] = report["reason"]
    for i, b in enumerate(report["boards"]):
        out[f"board{i}"] = f"{b['board']} {b.get('variant') or '-'} {b['result']}"
        if "reason" in b:
            out[f"board{i}_reason"] = b["reason"]
        if b.get("tests"):
            out[f"board{i}_tests"] = " ".join(f"{t['test']}={t['result']}" for t in b["tests"])
        if b.get("bitstreams"):
            out[f"board{i}_bitstreams"] = str(b["bitstreams"])
        flatten(f"board{i}_state", b.get("state", {}), out)
    for j, change in enumerate(report.get("state", {}).get("changes", [])):
        out[f"changed{j}"] = change
    return out


def summary(report):
    lines = []
    bad = report["result"] != "pass"
    if bad:
        lines += [
            "",
            "*" * 78,
            f"*** FPGA VERIFY: {report['result'].upper()} " + "*" * max(0, 58 - len(report["result"])),
        ]
    lines.append(f"fpgas-verify: {report['result']} (mode {report.get('mode', '-')}, {report.get('chosen_by', '-')})")
    if "reason" in report:
        lines.append(f"  {report['reason']}")
    for b in report["boards"]:
        lines.append(
            f"  {b['board']} {b.get('variant') or '-'}: {b['result']}" + (f": {b['reason']}" if "reason" in b else "")
        )
        for t in b.get("tests", []):
            lines.append(f"    {t['test']:<10} {t['result']}" + (f": {t['reason']}" if "reason" in t else ""))
            if t["result"] != "pass":
                lines += [f"        {line}" for line in t.get("output", [])[-8:]]
        for s in b.get("flash", {}).get("slots", []) if isinstance(b.get("flash"), dict) else []:
            lines.append(
                f"    flash {s['slot']} {s['result']}"
                + (f" at {s['first_difference']}" if "first_difference" in s else "")
            )
        if b.get("flash_note"):
            lines.append(f"    flash {b['flash_note']}")
    st = report.get("state", {})
    for change in st.get("changes", []):
        lines.append(f"  CHANGED {change}")
    if st.get("changes"):
        lines.append("  if this change was meant (a board flashed or swapped on purpose): sudo fpgas-verify --update")
    elif st.get("recorded"):
        lines.append(f"  state recorded ({st['recorded']}) in {st['file']}")
    if bad:
        lines.append("  more: fpgas-<board>-debug (fpgas-online-<board>-debug)")
        lines += ["*" * 78, ""]
    return "\n".join(lines)


def write(report, where):
    text = json.dumps(report, indent=2) + "\n"
    if where == "-":
        sys.stdout.write(text)
        return "stdout"
    out = pathlib.Path(where)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return str(out)


def run(options, prog="fpgas-verify"):
    report = verify(options)
    kept_in = write(report, options.get("report") or str(REPORT))
    print(summary(report), file=sys.stderr)
    if not options.get("no_publish"):
        publish("fpga-verified", details(report), kept_in, prog)
    return 0 if report["result"] == "pass" else 1
