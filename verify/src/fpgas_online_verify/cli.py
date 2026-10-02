"""The commands: fpgas-verify, and each board's fpgas-<board>-verify and fpgas-<board>-debug, which take the
board from the name they are run by (the deb's /usr/bin wrappers and pip's console scripts both call them)."""

import argparse
import pathlib
import re
import sys
import textwrap

from . import config, debug, runner, state
from .board import installed
from .testbench import TestBoard

# core.SEVERITY, for --help: tests/test_verify_boards.py holds them equal.
RESULTS = (
    ("pass", "every test passed, and the board and flash are as recorded"),
    ("changed", "a different board or flash from the recorded one"),
    ("fail", "a test failed, or the board runs a design that is not ours"),
    ("missing", "no board found"),
    ("error", "the check could not run (a missing tool or file)"),
)


def _results():
    rows = [f"  {r:<13} {what}" for r, what in RESULTS]
    return "the result is pass (exit 0) or a fail named for its worst cause (exit 1):\n" + "\n".join(rows)


def _files(board):
    rows = [
        f"  {runner.REPORT!s:<40} the report (--report)",
        f"  {state.STATE!s:<40} the recorded state (--state)",
    ]
    if board is None:
        rows.append(f"  {str(config.ADMIN_DIR) + '/*.ini':<40} fpga-board = BOARD or auto")
    return "files:\n" + "\n".join(rows)


def _tests_epilog(board):
    """The board's tests, for --help: the boot check's, then the ones only fpgas-<board>-debug runs."""
    tests = getattr(board, "tests", None)
    if not tests:
        return ""
    # A board that loads test designs marks which are in the boot check; the Acorn's are all in it.
    boot = [t for t, v in tests.items() if v.get("verify")] if isinstance(board, TestBoard) else list(tests)
    other = [t for t in tests if t not in boot]
    out = _listed("tests in the boot check", boot)
    return out + ("\n" + _listed(f"tests only fpgas-{board.slug}-debug runs", other) if other else "")


def _listed(title, words):
    """`title:` and the words under it, wrapped to fit 80 columns."""
    return f"{title}:\n" + textwrap.fill(" ".join(words), 78, initial_indent="  ", subsequent_indent="  ")


def _verify_parser(prog, board=None):
    selectable = board is None or bool(getattr(board, "tests", None))
    loads = board is None or isinstance(board, TestBoard)  # loads test designs: has variants and a UART to choose
    if board is None:  # any board: some load test designs, the Acorn is checked as it booted
        what = "Check this host's FPGA board and its wiring to this Pi."
    elif loads:
        what = f"Check this host's {board.title} with the fpgas.online test designs."
    else:
        what = f"Check this host's {board.title} as it booted from its flash."
    parser = argparse.ArgumentParser(
        prog=prog,
        usage="%(prog)s [options]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"{what}\nPrints a summary to stderr and writes a JSON report.",
        epilog="\n\n".join(e for e in (board and _tests_epilog(board), _results(), _files(board)) if e),
    )
    if board is None:
        parser.add_argument("--list", action="store_true", help="list the installed boards and the configured one")
        parser.add_argument("--board", help="check BOARD, ignoring the configuration")
        parser.add_argument("--no-probe", action="store_true", help="never scan JTAG to find a board (auto only)")
    partial = parser.add_mutually_exclusive_group()
    if selectable:
        partial.add_argument("--test", action="append", dest="tests", metavar="TEST",
                             help="run only TEST (repeatable); not published or recorded")  # fmt: skip
    partial.add_argument("--update", action="store_true", help="accept a changed board or flash: record it")
    if loads:
        parser.add_argument("--variant", help="use VARIANT's bitstreams, not the detected one")
        parser.add_argument("--port", help="the board's UART (default: the board's usual one)")
    parser.add_argument("--images", type=pathlib.Path, metavar="DIR", help="the bitstreams (default: installed)")
    parser.add_argument("--state", type=pathlib.Path, default=state.STATE, metavar="FILE", help="the recorded state")
    report = "the JSON report; '-' for stdout" + (" (the default with --test)" if selectable else "")
    parser.add_argument("--report", metavar="FILE", help=report)
    parser.add_argument("--no-publish", action="store_true", help="do not send the result to the fleet")
    return parser


def _options(args, board=None):
    out = {k: v for k, v in vars(args).items() if v is not None}
    if board:
        out["board"] = board
    return out


def verify_main(argv=None):
    """fpgas-verify: the configured board(s)."""
    args = _verify_parser("fpgas-verify").parse_args(argv)
    if args.list:
        boards = installed()
        for name, b in boards.items():
            print(f"{name:<8} {b.title:<22} {b.package}" + ("  (found by probing)" if b.probes else ""))
        try:
            mode, path = config.configured()
            print(f"configured: fpga-board = {mode} ({path})")
        except Exception as e:
            print(f"not configured: {e}")
        return 0
    return runner.run(_options(args))


def board_main(argv=None, prog=None):
    """fpgas-<board>-verify or fpgas-<board>-debug, the board and which of the two from the command's name."""
    prog = prog or pathlib.Path(sys.argv[0]).name
    m = re.fullmatch(r"fpgas-(.+)-(verify|debug)", prog)
    boards = installed()
    board = m and next((b for b in boards.values() if b.slug == m.group(1)), None)
    if board is None:
        sys.exit(f"{prog}: run this as fpgas-<board>-verify or fpgas-<board>-debug (installed: {', '.join(boards)})")
    if m.group(2) == "verify":
        return runner.run(_options(_verify_parser(prog, board).parse_args(argv), board.name), prog)
    return debug_main(argv, prog, board)


def debug_main(argv, prog, board):
    tests = getattr(board, "tests", None) if isinstance(board, TestBoard) else None  # tests it loads one by one
    commands = debug.commands(board)
    listing = [
        f"  {name + (' TEST' if takes_test else ''):<13} {help_}" for name, (_, help_, takes_test) in commands.items()
    ]
    examples = [f"  sudo {prog} detect"]
    if tests:
        first = next(iter(tests))
        examples += [f"  {prog} list", f"  sudo {prog} test {first}"]
        if "pin-id" in tests:  # after --: added to the test script's own arguments
            examples.append(f"  sudo {prog} test pin-id -- --hat-port JA")
    if board.name == "acorn":
        examples.append(f"  sudo {prog} identify")
    epilog = ["commands:\n" + "\n".join(listing), tests and _tests_epilog(board), "examples:\n" + "\n".join(examples)]
    parser = argparse.ArgumentParser(
        prog=prog,
        usage=f"%(prog)s [options] COMMAND{' [TEST] [-- ARGS]' if tests else ''}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"Run the {board.title}'s check one step at a time, with all its output."
        + ("\nARGS after -- go to the test's script." if tests else ""),
        epilog="\n\n".join(e for e in epilog if e),
    )
    if tests:
        parser.add_argument("--port", help="the board's UART (default: the board's usual one)")
        parser.add_argument("--variant", help="use VARIANT's bitstreams, not the detected one")
    parser.add_argument("--images", type=pathlib.Path, metavar="DIR", help="the bitstreams (default: installed)")
    sub = parser.add_subparsers(dest="command", required=True, help=argparse.SUPPRESS)
    for name, (_, help_, takes_test) in commands.items():
        p = sub.add_parser(name, help=help_)
        if takes_test:
            p.add_argument("test", choices=list(board.tests))
            p.add_argument("extra", nargs=argparse.REMAINDER, help="after --: arguments for the test script")
    args = parser.parse_args(argv)
    if getattr(args, "extra", None) and args.extra[0] == "--":
        args.extra = args.extra[1:]
    return debug.run(board, args)


def main():
    """`python3 -m fpgas_online_verify`: the same as fpgas-verify."""
    sys.exit(verify_main())
