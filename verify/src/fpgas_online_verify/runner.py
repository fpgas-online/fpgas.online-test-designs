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

import contextlib
import datetime
import json
import os
import pathlib
import sys
import tempfile

from . import conclusion, config, identity, state
from .board import installed
from .core import Problem, flatten, hold_lock, pci_devices, publish, tail, usb_devices, worst
from .core import run as run_command

SCHEMA_VERSION = 2
REPORT = pathlib.Path("/run/fpgas-online/verify.json")
# The fleet-events, and the details each carries. Every one but the last two is progress: the site's gate reads
# only fpga-verifying and fpga-verified (fpgas.online-site fleet/services.py FPGA_STAGES).
EVENTS = {
    "fpga-verifying": "started_at",
    "fpga-board-found": "board, variant, where (PCI slot, USB path or JTAG IDCODE)",
    "fpga-no-board": "reason",
    "fpga-board-identified": "schema (fpga-identity/1), board, then who it is (identity.py, docs/identity.md)",
    "fpga-test-started": "board, test",
    "fpga-test-finished": "board, test, result, reason",
    "fpga-verified": "the report, flattened (details())",
}
EVENT_TIMEOUT = 15  # a broker that is down must not hold up the check (nor fpgas-tt, which waits for it)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@contextlib.contextmanager
def probing(board):
    """find's `probing` for the boot check and fpgas-<board>-debug: hold the board's lock while its pins are
    driven to look for it, waiting as long as it takes (as the check does), and let it go once it has been."""
    with hold_lock(board.lock, board.title):
        yield True


def find(boards, mode, options, usb, pci):
    """[(board, host, found)] to check, and how they were chosen. A board that is not there is a Problem.

    options["probing"] is called with each `probes` board and gives a context manager that is held around
    anything that drives the board's pins to look for it (its find or probe), and says whether to go ahead:
    False skips the board, as not looked for. By default (`probing`) it holds the board's lock, unbounded;
    --identify's waits at most LOCK_WAIT. Either way no board's pins are driven without its lock.
    """
    probing_board = options.get("probing") or probing
    if mode != config.AUTO:
        board = boards.get(mode) or next((b for b in boards.values() if b.slug == mode), None)
        if board is None:
            have = ", ".join(boards) or "none"
            raise Problem("error", f"this host is set up for {mode!r}, but no such board module is installed "
                                   f"(fpgas-online-{mode}-tools?); installed: {have}")  # fmt: skip
        host = board.facts(options.get("port"))
        with probing_board(board) if board.probes else contextlib.nullcontext(True) as free:
            found = board.find(host, usb, pci) if free else []
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
            probed = []
            for n, b in boards.items():
                if b.probes:
                    with probing_board(b) as free:
                        probed += [(b, hosts[n], f) for f in b.probe(hosts[n])] if free else []
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


def recorded_and_gone(boards, mode, path):
    """For each board looked for whose own check takes it off its bus (Board.gone_after_check) and that the
    recorded state has: a sentence saying so. Nothing was found, so such a board may be there and unseen."""
    recorded = state.load(path)
    if not isinstance(recorded, dict) or "unreadable" in recorded:
        return []
    looked_for = boards.values() if mode == config.AUTO else [b for b in boards.values() if mode in (b.name, b.slug)]
    out = []
    for b in looked_for:
        if b.gone_after_check and any(key == b.name or key.startswith(f"{b.name}@") for key in recorded):
            out.append(f"a {b.title} was found on this host by an earlier check and is not there now: "
                       f"{b.gone_after_check}")  # fmt: skip
    return out


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
    upgraded = state.widened(recorded, current, version)
    changes = state.differences(upgraded, current, state.quiet_facts(version))
    if changes:
        info["changes"] = changes
    elif report["result"] != "error" and state.merged(upgraded, current) != recorded:
        # only facts the record's older version did not have, or had less of (an upgrade): recorded quietly
        state.save(state.merged(upgraded, current), report["checked_at"], path)
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
        if "power_cycle_check" not in options:  # opt-in, whichever way the board was chosen (config.py)
            on, path = config.power_cycle_check(options.get("mode_dir", config.MODE_DIR),
                                                options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
            if on:
                options = {**options, "power_cycle_check": True}
                report["power_cycle_check"] = {"on": True, "configured_by": str(path)}
        usb = usb_devices() if usb is None else usb
        pci = pci_devices() if pci is None else pci
        targets, report["chosen_by"] = find(boards, report["mode"], options, usb, pci)
    except Problem as p:
        report.update(result=p.result, reason=p.reason)
        if p.result == "missing":  # say what was recorded, if anything: nothing is recorded now
            gone = recorded_and_gone(boards, report.get("mode"), options.get("state", state.STATE))
            report["reason"] = "; ".join([p.reason, *gone])
            event("fpga-no-board", {"reason": report["reason"]})
            report["state"] = compare_state(report, [], [], False, options.get("state", state.STATE))
        return report
    reports, not_checked = [], []
    keys = _keys(targets)
    for (_, _, found), key in zip(targets, keys):
        event("fpga-board-found", {"board": key, "variant": found.get("variant"), "where": _where(found)})
    for (board, host, found), key in zip(targets, keys):
        identified, kept = [], []  # the identified event sent; the identity the check built (identity.keep())

        def board_event(stage, d, key=key, identified=identified):
            if stage == "fpga-board-identified":
                identified.append(key)
            event(stage, {"board": key, **d})

        try:
            board_options, skipped = _for_board(board, options, report["mode"])
            if board_options is None:  # none of the named tests: not checked, and no "pass" for it
                not_checked.append(board.name)
                # still found, so still identified (once), from what finding it showed
                board_event("fpga-board-identified", identity.details(identity.base(key, board.name, found)))
                continue
            # configured: the host is set up for this board (or its own command was run), not found by `auto`;
            # the Acorn tests a card it cannot name by its IDs only then (#155)
            board_options = {**board_options, "event": board_event, "board_key": key, identity.KEEP: kept.append,
                             "configured": report["mode"] != config.AUTO}  # fmt: skip
            with hold_lock(board.lock, board.title):
                reports.append(board.check(host, found, board_options))
        except Problem as p:
            reports.append({"board": board.name, "found": found, "result": p.result, "reason": p.reason})
            skipped = []
        except Exception as e:  # a bug in a board's check: that board is an error, the others are still checked
            reports.append({"board": board.name, "found": found, "result": "error",
                            "reason": f"the check crashed: {type(e).__name__}: {e}"})  # fmt: skip
            skipped = []
        if kept:  # a check that stopped after saying who the board is keeps it in its error report
            reports[-1].setdefault("identity", kept[-1])
        if not identified:  # the check stopped before saying who the board is: say what finding it showed
            reports[-1].setdefault("identity", identity.base(key, board.name, found))
        if "identity" in reports[-1]:
            _sendable_identity(reports[-1], identity.base(key, board.name, found))
        if not identified:
            board_event("fpga-board-identified", identity.details(reports[-1]["identity"]))
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


def _sendable_identity(report, base):
    """Leave out of a board's identity any field whose name or value cannot be sent (a bug in the board's
    module), and make each one an error on that board, so the other boards are still checked and fpga-verified
    is sent. An identity that is not a dict is replaced by `base` (what finding the board showed)."""
    try:
        bad = identity.refused(report["identity"])
    except TypeError as e:
        report["identity"], reasons = base, [f"the identity cannot be sent: {e}"]
    else:
        if not bad:
            return
        report["identity"] = {k: v for k, v in report["identity"].items() if k not in bad}
        reasons = [f"the identity field {k} cannot be sent: {why}" for k, why in bad.items()]
    report["result"] = worst([report.get("result", "error"), "error"])
    report["reason"] = "; ".join([report["reason"], *reasons] if report.get("reason") else reasons)


# -- telling people ------------------------------------------------------------------------------------------


def details(report):
    """The fleet-event's details: flat strings."""
    out = {"result": report["result"], "mode": report.get("mode", "-")}
    if "reason" in report:
        out["reason"] = report["reason"]
    for i, b in enumerate(report["boards"]):
        # three words (the site reads them so); another board's title is in the reason
        name, variant = conclusion.shown(b)
        out[f"board{i}"] = f"{name} {'-' if name == conclusion.OTHER_PCIE else variant or '-'} {b['result']}"
        if "reason" in b:
            out[f"board{i}_reason"] = b["reason"]
        if b.get("tests"):
            out[f"board{i}_tests"] = " ".join(f"{t['test']}={t['result']}" for t in b["tests"])
        if b.get("not_run"):
            out[f"board{i}_not_run"] = ", ".join(b["not_run"])
        if b.get("left_running"):
            out[f"board{i}_left_running"] = b["left_running"]["design"]
        if b.get("warnings"):
            out[f"board{i}_warnings"] = "; ".join(b["warnings"])
        if b.get("bitstreams"):
            out[f"board{i}_bitstreams"] = str(b["bitstreams"])
        flatten(f"board{i}_state", b.get("state", {}), out)
        if b.get("identity"):
            try:
                flat = identity.details(b["identity"])
            except TypeError as e:  # never ends the event: that board's identity says why it is not there
                out[f"board{i}_identity_error"] = str(e)
            else:
                del flat["schema"]
                out.update({f"board{i}_identity_{k}": v for k, v in flat.items()})
    for j, change in enumerate(report.get("state", {}).get("changes", [])):
        out[f"changed{j}"] = change
    return out


def summary(report, kept_in=None):
    """What a person reads: every test as it ran, and for a check that did not pass, the plain conclusion last
    (conclusion.py). `kept_in` is where the JSON report was written."""
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
    if "publish" in report:
        pub = report["publish"]
        by = f"`{config.PUBLISH} = {'on' if pub['on'] else 'off'}` in {pub.get('configured_by')}"
        lines.append(f"  published to the fleet: {by}" if pub["on"] else f"  not published: {pub.get('why') or by}")
    if report.get("not_checked"):
        lines.append(f"  not checked (none of the tests asked for): {', '.join(report['not_checked'])}")
    for b in report["boards"]:
        name, variant = conclusion.shown(b)
        lines.append(f"  {name} {variant or '-'}: {b['result']}")
        lines += [f"    {reason}" for reason in conclusion.own_reasons(b)]  # a test's reason is on its own line
        for t in b.get("tests", []):
            lines.append(f"    {t['test']:<10} {t['result']}" + (f": {t['reason']}" if "reason" in t else ""))
            if t["result"] != "pass":
                lines += [f"        {line}" for line in t.get("output", [])[-8:]]
        for test, why in (b.get("not_run") or {}).items():
            lines.append(f"    {test:<10} not run: {why}")
        left = b.get("left_running")
        if left:
            lines.append(f"    left running: the {left['design']} design ({left['bitstream']})")
        lines += [f"    WARNING: {w}" for w in b.get("warnings", [])]
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
    if st.get("recorded") and not st.get("changes"):
        lines.append(f"  state recorded ({st['recorded']}) in {st['file']}")
    if bad:
        lines += [*conclusion.lines(report, kept_in), "*" * 78, ""]
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
    if out.is_symlink() or (out.exists() and not out.is_file()):
        # A symlink, a device or a pipe (--report /dev/stdout, /dev/null): written through, as it always was.
        # Renaming a file over it would replace the link or, as root, the device node itself.
        out.write_text(text)
        return str(out)
    # Written beside the report and renamed over it: whoever reads the report (the site's bridge, a person)
    # sees the old one or the new one, never half of either.
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=out.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    return str(out)


def start_services(units):
    """Start the units the boards' checks stopped (testbench.services_stopped); what could not be queued.

    --no-block, as there: from inside fpgas-verify.service a blocking start of a unit ordered after it would
    wait on the verify's own start job."""
    failed = []
    for unit in units:
        try:
            rc, text = run_command(["systemctl", "start", "--no-block", unit], 60)
        except Problem as p:
            rc, text = 1, p.reason
        if rc != 0:
            failed.append(f"{unit} was not started again: {' '.join(tail(text, 2))}")
    return failed


# Which directories were read is the caller's business (config.publish); the fleet's file is named as the example.
NO_FILE = f"no file says `{config.PUBLISH} = on` (the fpgas.online Pi root has {config.ADMIN_DIR}/fleet.ini)"


def run(options, prog="fpgas-verify"):
    if options.get("tests"):
        # Part of the check is not the board's verified result: never published (the site would offer a board
        # on a partial pass), and never written over the boot's report unless --report says where.
        options = {**options, "no_publish": True, "report": options.get("report") or "-"}
    kept_in = options.get("report") or str(REPORT)
    # Nothing is sent unless a file says `publish = on` (config.py: the fleet's Pi root does); --no-publish and
    # --test send nothing even then. A setting that cannot be read is the run's result, and is not published.
    # Every report and summary says which, and why: a fleet root that lost its file shows in one look at a board.
    publishing, unreadable = False, None
    if options.get("tests"):
        published = {"on": False, "why": "--test runs part of the check"}
    elif options.get("no_publish"):
        published = {"on": False, "why": "--no-publish"}
    else:
        try:
            publishing, said_by = config.publish(options.get("mode_dir", config.MODE_DIR),
                                                 options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
            published = {"on": publishing, "configured_by": str(said_by)} if said_by else {"on": False, "why": NO_FILE}
        except Problem as p:
            unreadable, published = p, {"on": False, "why": "the setting could not be read"}
    if publishing:
        # The site hears the check has started, and says the board is being verified until the result follows.
        working = publish("fpga-verifying", {"started_at": _now()}, prog=prog, timeout=EVENT_TIMEOUT)
        options = {**options, "event": _Progress(prog, working)}
    # The services the checks stop are started here, after the report is written: one that reads the report
    # when it starts (the TT site's bridge) must find this run's, not the one before.
    stopped = []
    options = {**options, "restart_later": stopped}
    to_stdout = kept_in == "-"
    try:
        try:
            if unreadable:
                report = {"schema_version": SCHEMA_VERSION, "result": unreadable.result, "checked_at": _now(),
                          "boards": [], "reason": unreadable.reason}  # fmt: skip
            else:
                report = verify(options)
        except Exception as e:  # whatever went wrong, the site still hears a result, and the report says why
            report = {"schema_version": SCHEMA_VERSION, "result": "error", "checked_at": _now(), "boards": [],
                      "reason": f"fpgas-verify crashed: {type(e).__name__}: {e}"}  # fmt: skip
        report["publish"] = published
        if not to_stdout:
            kept_in = write(report, kept_in)
    finally:
        # However the check or the write ended (an interrupt, a full disk), a stopped service is not left down.
        not_started = start_services(stopped)
    if not_started:  # the service may be left down: the result says so, and a report file is written again
        report["services_failed"] = not_started
        report["result"] = worst([report["result"], "error"])
        report["reason"] = "; ".join([*([report["reason"]] if report.get("reason") else []), *not_started])
    if to_stdout or not_started:  # stdout gets one document, after the starts: nothing reads it as a file
        kept_in = write(report, kept_in)
    print(summary(report, kept_in), file=sys.stderr)
    if publishing:
        publish("fpga-verified", details(report), kept_in, prog)
    return 0 if report["result"] == "pass" else 1
