#!/usr/bin/env python3
"""Find which fpgas.online FPGA board this Pi has, and run that board's verify.

Installed by fpgas-online-verify as fpgas-verify, with fpgas-verify.service, which runs it once per boot. Each
board's tools package (fpgas-online-<board>-tools) registers its verify in /usr/share/fpgas-online/verify.d/
with how to spot its board, so the same root filesystem works on any Pi: a netboot root with every board's
tools (fpgas-online-verify-all) verifies whichever board the booting Pi has, and a Pi with its own storage and
one board's tools gets the same boot check.

How a board is found, cheapest and safest first:

  1. USB and PCI IDs, read from sysfs (the Arty's FTDI, the Fomu's bootloader, the TT board's RP2350, the
     Acorn's endpoint). Nothing is driven.
  2. Only if that finds nothing: the boards found by a JTAG scan over the GPIO header (the NeTV2). The scan
     drives GPIO 4, 17 and 27, so it never runs on a Pi whose board was already found another way; pass
     --no-jtag-scan (for example in /etc/default/fpgas-verify) to rule it out altogether.

Each board's verify reports and publishes its own fleet-event. This writes the overall result to
/run/fpgas-online/verify.json and exits 0 only for "pass" and "none"; when no board is found it publishes a
`fpga-verified` event with result "none", so a host that has nothing to check still says so.

    sudo fpgas-verify                     # find, verify, report, publish
    sudo fpgas-verify --list              # the registered boards and whether each is present
    sudo fpgas-verify --board arty        # skip detection
"""

import argparse
import datetime
import json
import pathlib
import subprocess
import sys

SCHEMA_VERSION = 1
# The Acorn's verify has results between pass and fail; worst first wins.
SEVERITY = ("none", "pass", "degraded", "unconverted", "fail", "error")
REGISTRY = pathlib.Path("/usr/share/fpgas-online/verify.d")
REPORT = pathlib.Path("/run/fpgas-online/verify.json")
SYSFS_USB = pathlib.Path("/sys/bus/usb/devices")
SYSFS_PCI = pathlib.Path("/sys/bus/pci/devices")


def load_registry(root=REGISTRY):
    boards = []
    for path in sorted(pathlib.Path(root).glob("*.json")):
        try:
            entry = json.loads(path.read_text())
            if not isinstance(entry.get("command"), list) or not isinstance(entry.get("detect"), dict):
                raise ValueError("needs a command list and a detect table")
        except (OSError, ValueError) as e:
            print(f"fpgas-verify: ignoring {path}: {e}", file=sys.stderr)
            continue
        boards.append({**entry, "board": entry.get("board", path.stem)})
    return boards


def _ids(root, *names):
    found = set()
    if not pathlib.Path(root).is_dir():
        return found
    for dev in pathlib.Path(root).iterdir():
        try:
            found.add(tuple(int((dev / n).read_text().strip(), 16) for n in names))
        except (OSError, ValueError):
            continue
    return found


def usb_ids(root=SYSFS_USB):
    return _ids(root, "idVendor", "idProduct")


def pci_vendors(root=SYSFS_PCI):
    return {v for (v,) in _ids(root, "vendor")}


def spotted(entry, usb, pci):
    """Is the entry's board visible without driving anything?"""
    d = entry["detect"]
    for vendor, product in d.get("usb", []):
        if any(v == int(vendor, 16) and (product is None or p == int(product, 16)) for v, p in usb):
            return True
    return any(int(v, 16) in pci for v in d.get("pci_vendor", []))


def choose(registry, usb, pci, jtag_scan=True):
    """(boards to run, how they were chosen)."""
    found = [e for e in registry if spotted(e, usb, pci)]
    if found:
        return found, "USB/PCI IDs"
    if not jtag_scan:
        return [], "USB/PCI IDs (JTAG scan disabled)"
    return [e for e in registry if e["detect"].get("jtag")], "JTAG scan"


def run_board(entry, no_publish, run=None):
    """Run one board's verify, its output going straight to ours; its report says what it found."""
    run = run or subprocess.run
    report_path = pathlib.Path(entry.get("report", f"/run/fpgas-online/{entry['board']}-verify.json"))
    argv = [*entry["command"], "--report", str(report_path), *(["--no-publish"] if no_publish else [])]
    try:
        rc = run(argv, check=False, timeout=entry.get("timeout", 1800)).returncode
    except (OSError, subprocess.SubprocessError) as e:
        return {"board": entry["board"], "result": "error", "reason": f"could not run {argv[0]}: {e}"}
    try:
        result = json.loads(report_path.read_text())["result"]
    except (OSError, ValueError, KeyError):
        result = "pass" if rc == 0 else "error"
    if result not in SEVERITY:
        result = "error"
    return {"board": entry["board"], "result": result, "exit": rc, "report": str(report_path)}


def verify(registry, usb, pci, jtag_scan=True, only=None, no_publish=False, run=None):
    if only:
        chosen, how = [e for e in registry if e["board"] in only], "--board"
    else:
        chosen, how = choose(registry, usb, pci, jtag_scan)
    boards = [run_board(e, no_publish, run=run) for e in chosen]
    return {
        "schema_version": SCHEMA_VERSION,
        "result": max((b["result"] for b in boards), key=SEVERITY.index, default="none"),
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "registered": [e["board"] for e in registry],
        "chosen_by": how,
        "boards": boards,
    }


def exit_code(report):
    return 0 if report["result"] in ("pass", "none") else 1


def publish_none(report):
    """No board answered: say so, since no board's verify published anything that says it."""
    argv = ["fleet-event", "fpga-verified", "--detail", "result=none", "--detail", "board=-",
            "--detail", f"registered={' '.join(report['registered']) or '-'}",
            "--detail", f"chosen_by={report['chosen_by']}"]  # fmt: skip
    try:
        subprocess.run(argv, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"fpgas-verify: could not publish the result ({e})", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fpgas-verify", description=__doc__.split("\n\n")[0])
    parser.add_argument("--board", action="append", help="run this registered board's verify, skipping detection")
    parser.add_argument("--no-jtag-scan", action="store_true", help="never scan the GPIO header for a JTAG board")
    parser.add_argument("--list", action="store_true", help="show the registered boards and which are present")
    parser.add_argument("--registry", type=pathlib.Path, default=REGISTRY)
    parser.add_argument("--report", default=str(REPORT), help="where to write the JSON report ('-' for stdout)")
    parser.add_argument("--no-publish", action="store_true", help="no fleet-events, here or from the boards")
    args = parser.parse_args(argv)

    registry = load_registry(args.registry)
    usb, pci = usb_ids(), pci_vendors()
    if args.list:
        for e in registry:
            how = "JTAG scan" if e["detect"].get("jtag") else ("present" if spotted(e, usb, pci) else "absent")
            print(f"{e['board']:<10} {how:<10} {' '.join(e['command'])}")
        return 0
    unknown = set(args.board or []) - {e["board"] for e in registry}
    if unknown:
        parser.error(f"not registered: {', '.join(sorted(unknown))} (registered: "
                     f"{', '.join(e['board'] for e in registry) or 'none'})")  # fmt: skip

    report = verify(registry, usb, pci, not args.no_jtag_scan, args.board, args.no_publish)
    text = json.dumps(report, indent=2) + "\n"
    if args.report == "-":
        sys.stdout.write(text)
    else:
        out = pathlib.Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    names = ", ".join(f"{b['board']} {b['result']}" for b in report["boards"]) or "no board found"
    print(f"fpgas-verify: {report['result']} ({names}; chosen by {report['chosen_by']})", file=sys.stderr)
    if not args.no_publish and all(b["result"] == "none" for b in report["boards"]):
        publish_none(report)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
