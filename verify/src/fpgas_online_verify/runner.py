"""fpgas-verify: find the board (or boards) this host is set up for, check each, and compare with last time.

  * One board (`fpga-board = arty`, fpgas-arty-verify, or --board arty): only that board is looked for. Not
    finding it is "missing", which is fatal, whatever else is attached: nothing else is looked for.
  * `fpga-board = auto` (fpgas-online-multi-board / -all-boards): every installed board is looked for,
    first the ones visible without driving anything (USB and PCI IDs), and only if none is, the ones found by
    driving something (the NeTV2's JTAG scan). Finding none is "missing", which is fatal.

Then each board found is checked (its board module), and what it reported as its state (identity, flash) is
compared with what was recorded last time (state.py): any difference is "changed", which is fatal, unless
--update, which records what was found instead.

The site hears how it goes through fleet-events, each small and flat (EVENTS): the check starting, each board
found or no board, a board identified, each test started and finished, and the final result.
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
# The fleet-events, and the details each carries. Every one but the last two is progress: the site's gate reads
# only fpga-verifying and fpga-verified (fpgas.online-site fleet/services.py FPGA_STAGES).
EVENTS = {
    "fpga-verifying": "started_at",
    "fpga-board-found": "board, variant, where (PCI slot, USB path or JTAG IDCODE)",
    "fpga-no-board": "reason",
    "fpga-board-identified": "board, then what identifies it (an Acorn's: bdf, pci_ids, subsystem, variant, "
    "identifier, build, dna, idcode, flash_part, flash_jedec, flash_unique_id)",
    "fpga-test-started": "board, test",
    "fpga-test-finished": "board, test, result, reason",
    "fpga-verified": "the report, flattened (details())",
}
EVENT_TIMEOUT = 15  # a broker that is down must not hold up the check (nor fpgas-tt, which waits for it)


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
    # Only weak claims (a Xilinx PCIe design the Acorn module cannot name): probe as well, since it may be a
    # NeTV2 on PCIe. The weak claims stay in, and fail on their own: nothing seen is dropped.
    if spotted and (options.get("no_probe") or not all(b.weak(f) for b, _, f in spotted)):
        return spotted, "auto: USB/PCI IDs"
    if options.get("no_probe"):
        how = "auto: USB/PCI IDs, probing disabled"
    else:
        try:
            probed = [(b, hosts[n], f) for n, b in boards.items() if b.probes for f in b.probe(hosts[n])]
        except Problem as p:
            if not spotted:
                raise
            # The weak claims are still checked (and never pass); the probe's failure is said, not lost.
            return spotted, f"auto: USB/PCI IDs; probing as well failed: {p.reason}"
        if probed:
            names = ", ".join(sorted({b.name for b, _, _ in probed}))
            return spotted + probed, ("auto: USB/PCI IDs and probed (" if spotted else "auto: probed (") + names + ")"
        if spotted:
            return spotted, "auto: USB/PCI IDs, and probing found nothing more"
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
    recorded, version = state.load_record(path)
    info = {"file": str(path)}
    if update or recorded is None:
        if report["result"] in ("missing", "error") and not update:
            info["recorded"] = False
            return info
        state.save(current, report["checked_at"], path)
        info["recorded"] = "--update" if update else "first run"
        return info
    changes = state.differences(recorded, current, state.quiet_facts(version))
    if changes:
        info["changes"] = changes
    elif report["result"] != "error" and state.merged(recorded, current) != recorded:
        # only facts the record's older version did not have (an upgrade): added quietly, not a change
        state.save(state.merged(recorded, current), report["checked_at"], path)
        info["added"] = True
    return info


def _for_board(board, options, mode):
    """The options for one board's check, and the --test names skipped for it; None for the options when the
    board has none of the named tests (with `auto`), so it is not checked at all.

    With `auto`, --test names the tests of whichever boards are found: a board runs those it has and skips the
    rest. Configured for one board, a name it does not have is the check's error (testbench.py, or the Acorn's
    suite.py), and a board whose check has no selectable tests cannot take --test."""
    wanted = options.get("tests")
    if not wanted:
        return options, []
    have = getattr(board, "tests", None) or {}  # none: a board whose check has no selectable tests
    if mode != config.AUTO:
        if not have:
            raise Problem("error", f"{board.title}'s check has no selectable tests: run it without --test")
        return options, []
    run = [t for t in wanted if t in have]
    return ({**options, "tests": run} if run else None), [t for t in wanted if t not in have]


def _quiet(stage, details):
    pass


def _where(found):
    return found.get("bdf") or found.get("usb") or found.get("idcode") or "-"


def verify(options, boards=None, usb=None, pci=None, mode=None):
    """The report. options["event"], when given, is called as event(stage, details) as the check goes."""
    boards = installed() if boards is None else boards
    event = options.get("event") or _quiet
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
            event("fpga-no-board", {"reason": p.reason})
            report["state"] = compare_state(report, [], [], False, options.get("state", state.STATE))
        return report
    reports, not_checked = [], []
    keys = _keys(targets)
    for (_, _, found), key in zip(targets, keys):
        event("fpga-board-found", {"board": key, "variant": found.get("variant"), "where": _where(found)})
    for (board, host, found), key in zip(targets, keys):
        try:
            board_options, skipped = _for_board(board, options, report["mode"])
            if board_options is None:  # none of the named tests: not checked, and no "pass" for it
                not_checked.append(board.name)
                continue
            board_options = {**board_options, "event": lambda stage, d, key=key: event(stage, {"board": key, **d})}
            with hold_lock(board.lock, board.title):
                reports.append(board.check(host, found, board_options))
        except Problem as p:
            reports.append({"board": board.name, "found": found, "result": p.result, "reason": p.reason})
            skipped = []
        except Exception as e:  # a bug in a board's check: that board is an error, the others are still checked
            reports.append({"board": board.name, "found": found, "result": "error",
                            "reason": f"the check crashed: {type(e).__name__}: {e}"})  # fmt: skip
            skipped = []
        if skipped:
            reports[-1]["tests_skipped"] = skipped
    report["boards"] = reports
    if not_checked:
        report["not_checked"] = not_checked
    if not reports:  # --test named only tests that no board found has
        report.update(result="error", reason=f"no board found ({', '.join(not_checked)}) has the test "
                                             f"{', '.join(options['tests'])}")  # fmt: skip
    else:
        report["result"] = worst(r["result"] for r in reports)
    if options.get("tests"):
        # Only some tests ran, so some of the state (the flash JEDEC ID) may not have been read: recording it would
        # make the next full run report "changed", and comparing it says nothing about what was not run.
        report["state"] = {"file": str(options.get("state", state.STATE)), "recorded": False,
                           "note": "not compared or recorded: --test runs only part of the check"}  # fmt: skip
        return report
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
        if b.get("identity"):
            flatten(f"board{i}_identity", b["identity"], out)
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
    if report.get("not_checked"):
        lines.append(f"  not checked (none of the tests asked for): {', '.join(report['not_checked'])}")
    for b in report["boards"]:
        lines.append(
            f"  {b['board']} {b.get('variant') or '-'}: {b['result']}" + (f": {b['reason']}" if "reason" in b else "")
        )
        for t in b.get("tests", []):
            lines.append(f"    {t['test']:<10} {t['result']}" + (f": {t['reason']}" if "reason" in t else ""))
            if t["result"] != "pass":
                lines += [f"        {line}" for line in t.get("output", [])[-8:]]
        for test, why in (b.get("not_run") or {}).items():
            lines.append(f"    {test:<10} not run: {why}")
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


class _Progress:
    """The progress events, sent as the check goes. A broker that does not answer stops them, so a dead broker
    costs one timeout, not one per test; the final fpga-verified is still tried."""

    def __init__(self, prog, working=True):
        self.prog, self.working = prog, working

    def __call__(self, stage, details):
        if self.working:
            flat = {k: "-" if v is None else str(v) for k, v in details.items()}
            self.working = publish(stage, flat, prog=self.prog, timeout=EVENT_TIMEOUT)


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
    if options.get("tests"):
        # Part of the check is not the board's verified result: never published (the site would offer a board
        # on a partial pass), and never written over the boot's report unless --report says where.
        options = {**options, "no_publish": True, "report": options.get("report") or "-"}
    kept_in = options.get("report") or str(REPORT)
    if not options.get("no_publish"):
        # The site hears the check has started, and says the board is being verified until the result follows.
        working = publish("fpga-verifying", {"started_at": _now()}, prog=prog, timeout=EVENT_TIMEOUT)
        options = {**options, "event": _Progress(prog, working)}
    try:
        report = verify(options)
    except Exception as e:  # whatever went wrong, the site still hears a result, and the report says why
        report = {"schema_version": SCHEMA_VERSION, "result": "error", "checked_at": _now(), "boards": [],
                  "reason": f"fpgas-verify crashed: {type(e).__name__}: {e}"}  # fmt: skip
    kept_in = write(report, kept_in)
    print(summary(report), file=sys.stderr)
    if not options.get("no_publish"):
        publish("fpga-verified", details(report), kept_in, prog)
    return 0 if report["result"] == "pass" else 1
