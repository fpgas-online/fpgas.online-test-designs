"""The commands: fpgas-verify, and each board's fpgas-<board>-verify and fpgas-<board>-debug, which take the
board from the name they are run by (the deb's /usr/bin wrappers and pip's console scripts both call them)."""

import argparse
import pathlib
import re
import sys

from . import debug, runner, state
from .board import installed


def _verify_parser(prog, board=None):
    parser = argparse.ArgumentParser(prog=prog, description=(runner.__doc__ or "").split("\n\n")[0])
    if board is None:
        parser.add_argument("--board", help="verify this board only, whatever the configuration says")
        parser.add_argument("--list", action="store_true", help="the installed boards, and the configured mode")
        parser.add_argument(
            "--no-probe", action="store_true",
            help="with fpga-board = auto, never drive anything to find a board (no JTAG scan)",
        )  # fmt: skip
    parser.add_argument("--update", action="store_true",
                        help="record what is found now as this host's state (after flashing or swapping a board "
                             "on purpose), instead of failing on the difference")  # fmt: skip
    parser.add_argument("--test", action="append", help="run only this test (repeatable)")
    parser.add_argument("--variant", help="use this variant's bitstreams instead of the detected one")
    parser.add_argument("--port", help="the board's UART on this Pi (default: the board's usual one)")
    parser.add_argument("--images", type=pathlib.Path, help="the installed bitstreams to use")
    parser.add_argument("--state", type=pathlib.Path, default=state.STATE, help="the recorded state")
    parser.add_argument("--report", default=str(runner.REPORT), help="where to write the JSON report ('-': stdout)")
    parser.add_argument("--no-publish", action="store_true", help="do not send the fleet-event")
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
        from . import config

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
    parser = argparse.ArgumentParser(prog=prog, description=(debug.__doc__ or "").split("\n\n")[0])
    parser.add_argument("--port", help="the board's UART on this Pi (default: the board's usual one)")
    parser.add_argument("--variant", help="use this variant's bitstreams instead of the detected one")
    parser.add_argument("--images", type=pathlib.Path, help="the installed bitstreams to use")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_, takes_test) in debug.commands(board).items():
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
