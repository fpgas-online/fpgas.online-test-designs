"""fpgas-<board>-debug: look closer at a board when its verify fails, one step at a time.

Uses the same detection, bitstreams and programming as the verify, but shows everything as it happens, and
has the tests the boot check leaves out because they need extra wiring: the PMOD loopback and pin
identification (a PMOD HAT) and Ethernet (a USB Ethernet adapter).

    sudo fpgas-arty-debug detect                  # is the board there, and how would it be loaded
    fpgas-arty-debug list                         # the tests and the installed bitstream for each
    sudo fpgas-arty-debug check                   # the installed bitstreams against their manifest
    sudo fpgas-arty-debug program uart            # load a test's design and leave it running
    sudo fpgas-arty-debug test ddr                # load it and run its test, output as it comes
    sudo fpgas-arty-debug test pin-id -- --hat-port JA    # after --: arguments for the test script
    sudo fpgas-acorn-debug identify               # who the Acorn is: fpgas-acorn-verify --identify
"""

import contextlib
import json
import subprocess
import sys

from . import bitstreams, identify, runner
from .core import Problem, hold_lock, pci_devices, usb_devices
from .testbench import TestBoard


def _live(argv):
    argv = [str(a) for a in argv]
    print("$ " + " ".join(argv), flush=True)
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError:
        print(f"{argv[0]} is not installed", flush=True)
        return 127


def _find(board, host):
    """board.find, under the board's lock when finding it drives its pins (the NeTV2's JTAG scan), waiting for it
    as the boot check does (runner.probing). Not for use while the lock is already held (program, test)."""
    with runner.probing(board) if board.probes else contextlib.nullcontext():
        return board.find(host, usb_devices(), pci_devices())


def detect(board, host, args):
    found = _find(board, host)
    print(json.dumps({"board": board.name, "host": host, "found": found}, indent=2, default=str))
    return 0 if found else 1


def _variant(board, host, args):
    if args.variant:
        return args.variant
    if len(board.variants) == 1:
        return next(iter(board.variants))
    found = board.find(host, usb_devices(), pci_devices())  # only from program and test: the lock is held
    if not found:
        raise Problem("missing", f"no {board.title} found, so no variant to choose: pass --variant")
    return found[0]["variant"]


def listing(board, host, args):
    images = bitstreams.images_dir(board.slug, args.images)
    try:
        manifest = bitstreams.load_manifest(images, board.bitstreams_package)
    except Problem as p:
        print(p.reason)
        manifest = {}
    have = {f["path"] for f in manifest.get("files", [])}
    print(f"{board.title}: {board.bitstreams_package} {manifest.get('version', '-')} in {images}")
    for name, t in board.tests.items():
        where = "boot check" if t.get("verify") else "debug only"
        for variant in board.variants:
            path = board.artifact(name, variant)
            print(f"  {name:<10} {variant:<8} {where:<11} {path}{'' if path in have else '  (not installed)'}")
    return 0


def check_files(board, host, args):
    images = bitstreams.images_dir(board.slug, args.images)
    manifest = bitstreams.load_manifest(images, board.bitstreams_package)
    bad = 0
    for entry in manifest.get("files", []):
        try:
            bitstreams.checked(images, entry)
            print(f"ok   {entry['path']}")
        except Problem as p:
            bad += 1
            print(f"BAD  {p.reason}")
    print(f"{len(manifest.get('files', [])) - bad} ok, {bad} bad ({manifest.get('version')}, {manifest.get('commit')})")
    return 1 if bad else 0


def program(board, host, args, then_test=False):
    if args.test not in board.tests:
        raise Problem("error", f"{board.name} has no test {args.test!r}: {', '.join(board.tests)}")
    variant = _variant(board, host, args)
    images = bitstreams.images_dir(board.slug, args.images)
    manifest = bitstreams.load_manifest(images, board.bitstreams_package)
    bitstream = board.bitstream(images, manifest, args.test, variant)
    with board.services_stopped(lambda argv, timeout: (_live(argv), "")):
        return _program(board, host, args, bitstream, then_test)


def _program(board, host, args, bitstream, then_test):
    for step in board.pre_steps(args.test, host):
        _live(step)
    if board.tests[args.test].get("runner") == "tt-bridge":  # loads the design and bridges the UART in one go
        if not then_test:
            return _live(board.program_argv(bitstream, host, args.test))
        return _live([*board.test_argv(args.test, host, bitstream), *args.extra])
    if then_test and board.tests[args.test].get("listen"):  # the test listens first: see listen.py
        test = [*board.test_argv(args.test, host, bitstream), *args.extra]
        return _live([sys.executable, "-m", "fpgas_online_verify.listen", host["port"], str(len(test)), *test,
                      *board.program_argv(bitstream, host, args.test)])  # fmt: skip
    rc = _live(board.program_argv(bitstream, host, args.test))
    if rc != 0 or not then_test:
        return rc
    return _live([*board.test_argv(args.test, host, bitstream), *args.extra])


def acorn_identify(board, host, args):
    """The same document as fpgas-acorn-verify --identify."""
    options = {"board": board.name, **({"images": args.images} if args.images else {})}
    return identify.run(options, f"fpgas-{board.slug}-debug", {board.name: board})


def commands(board):
    """{name: (function, help, takes a test)} for this board."""
    out = {"detect": (detect, "find the board; exit 1 if it is not there", False)}
    if isinstance(board, TestBoard):
        out.update({
            "list": (listing, "list the tests and their bitstreams", False),
            "check": (check_files, "check the bitstreams' sha256s", False),
            "program": (program, "load TEST's design and leave it running", True),
            "test": (lambda b, h, a: program(b, h, a, then_test=True), "load TEST's design and run its test", True),
        })  # fmt: skip
    if board.name == "acorn":
        out["identify"] = (acorn_identify, "print who the board is (as fpgas-acorn-verify --identify)", False)
    return out


def run(board, args):
    host = board.facts(getattr(args, "port", None))
    func = commands(board)[args.command][0]
    try:
        if args.command in ("program", "test"):
            with hold_lock(board.lock, board.title):
                return func(board, host, args)
        return func(board, host, args)
    except Problem as p:
        print(f"fpgas-{board.slug}-debug: {p.result}: {p.reason}", flush=True)
        return 1
