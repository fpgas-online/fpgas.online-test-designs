#!/usr/bin/env python3
"""Look closer at an Arty A7, NeTV2, Fomu EVT or TT FPGA board when fpgas-<board>-verify fails.

Installed by fpgas-online-<board>-debug as fpgas-<board>-debug. It uses the same bitstreams, detection and
programming as the verify (board_verify.py, from fpgas-online-<board>-tools), but runs one step at a time,
shows everything as it happens, and also has the tests the boot check leaves out because they need extra
wiring: the PMOD loopback and pin identification (a PMOD HAT) and Ethernet (a USB Ethernet adapter).

    sudo fpgas-arty-debug detect                  # is the board there, which part, how it would be loaded
    fpgas-arty-debug list                         # the tests and the installed bitstream for each
    sudo fpgas-arty-debug check                   # the installed bitstreams against their manifest
    sudo fpgas-arty-debug program uart            # load a test's bitstream and leave it running
    sudo fpgas-arty-debug test ddr                # load it and run its test, output as it comes
    sudo fpgas-netv2-debug test pin-id -- --hat-port JA   # extra arguments go to the test script
"""

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("board_verify", _HERE / "board_verify.py")
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)


def cmd_detect(board, host, args):
    found = bv.detect(board, host) if "jtag" not in bv.BOARDS[board]["detect"] or host["model"] else None
    facts = {
        "board": board,
        "host": host["model"] or "not a Raspberry Pi",
        "port": host["port"],
        "detected": found if found is not None else "not a Raspberry Pi: no GPIO header to scan",
    }
    if found and found.get("present"):
        test = bv.verify_tests(board)[0]
        variant = args.variant or found["variant"]
        if variant in bv.BOARDS[board]["variants"]:
            path = pathlib.Path(args.images) / bv.artifact_path(board, test, variant)
            facts["program_with"] = bv.program_argv(board, path, host, test)
    print(json.dumps(facts, indent=2))
    return 0 if found and found.get("present") else 1


def cmd_list(board, host, args):
    try:
        manifest = bv.load_manifest(args.images)
    except bv.Problem as p:
        print(p.reason, file=sys.stderr)
        manifest = {"files": []}
    have = {f["path"] for f in manifest.get("files", [])}
    print(f"{bv.BOARDS[board]['title']}: bitstreams {manifest.get('version', '-')} in {args.images}")
    for name, t in bv.BOARDS[board]["tests"].items():
        where = "boot check" if t.get("verify") else "debug only"
        for variant in bv.BOARDS[board]["variants"]:
            path = bv.artifact_path(board, name, variant)
            print(f"  {name:<10} {variant:<8} {where:<11} {path}{'' if path in have else '  (not installed)'}")
    return 0


def cmd_check(board, host, args):
    try:
        manifest = bv.load_manifest(args.images)
    except bv.Problem as p:
        print(p.reason, file=sys.stderr)
        return 1
    bad = 0
    for entry in manifest.get("files", []):
        try:
            bv.checked_bitstream(args.images, manifest, entry["path"])
            print(f"ok   {entry['path']}")
        except bv.Problem as p:
            bad += 1
            print(f"BAD  {p.reason}")
    print(f"{len(manifest.get('files', [])) - bad} ok, {bad} bad ({manifest.get('version')}, {manifest.get('commit')})")
    return 1 if bad else 0


def _variant(board, host, args):
    if args.variant:
        return args.variant
    variants = bv.BOARDS[board]["variants"]
    if len(variants) == 1:
        return next(iter(variants))
    found = bv.detect(board, host)
    if found["variant"] is None:
        raise bv.Problem("error", f"cannot tell which variant this is ({found}); pass --variant")
    return found["variant"]


def _live(argv):
    print("$ " + " ".join(str(a) for a in argv), flush=True)
    try:
        return subprocess.run([str(a) for a in argv], check=False).returncode
    except FileNotFoundError:
        print(f"{argv[0]} is not installed", file=sys.stderr)
        return 127


def cmd_program(board, host, args, then_test=False):
    t = bv.BOARDS[board]["tests"][args.test]
    variant = _variant(board, host, args)
    manifest = bv.load_manifest(args.images)
    bitstream = bv.checked_bitstream(args.images, manifest, bv.artifact_path(board, args.test, variant))
    steps = list(t.get("pre", []))
    if "{port}" in " ".join(t["args"]) and t.get("runner") != "tt-bridge":
        steps += bv.uart_pre(board, host)
    for step in steps:
        _live(step)
    if then_test and t.get("runner") == "tt-bridge":  # programs and bridges the UART in one go
        return _live([*bv.test_argv(board, args.test, host, bitstream), *args.extra])
    rc = _live(bv.program_argv(board, bitstream, host, args.test))
    if rc != 0 or not then_test:
        return rc
    return _live([*bv.test_argv(board, args.test, host, bitstream), *args.extra])


def main(argv=None, prog=None):
    prog = prog or pathlib.Path(sys.argv[0]).name
    board = bv.board_for_program(prog)
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    parser.add_argument("--board", choices=sorted(bv.BOARDS), default=board, required=board is None)
    parser.add_argument("--port", help="the board's UART on this Pi (default: the board's usual one)")
    parser.add_argument("--variant", help="use this variant's bitstreams instead of the detected one")
    parser.add_argument("--images", type=pathlib.Path, help="installed bitstreams (manifest.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("detect", help="find the board and say how it would be loaded")
    sub.add_parser("list", help="the tests and their installed bitstreams")
    sub.add_parser("check", help="check every installed bitstream against the manifest")
    for name, help_ in (("program", "load a test's bitstream"), ("test", "load a test's bitstream and run it")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("test")
        p.add_argument("extra", nargs=argparse.REMAINDER, help="after --: extra arguments for the test script")
    args = parser.parse_args(argv)
    if getattr(args, "extra", None) and args.extra[0] == "--":
        args.extra = args.extra[1:]
    if getattr(args, "test", None) and args.test not in bv.BOARDS[args.board]["tests"]:
        parser.error(f"{args.board} has no test {args.test!r}: {', '.join(bv.BOARDS[args.board]['tests'])}")
    if args.variant and args.variant not in bv.BOARDS[args.board]["variants"]:
        parser.error(f"{args.board} variants: {', '.join(bv.BOARDS[args.board]['variants'])}")
    args.images = args.images or bv.images_dir(args.board)
    host = bv.host_facts(args.board, args.port)

    try:
        if args.command in ("program", "test"):
            with bv.hold_lock(args.board):
                return cmd_program(args.board, host, args, then_test=args.command == "test")
        return {"detect": cmd_detect, "list": cmd_list, "check": cmd_check}[args.command](args.board, host, args)
    except bv.Problem as p:
        print(f"{prog}: {p.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
