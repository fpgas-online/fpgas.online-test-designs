"""The last lines of a check that did not pass, for a person who has not seen fpgas-verify before.

The summary above them (runner.summary) is every test in the order it ran, with a failed test's last lines of
output. These lines say it again plainly, and last, so they are what is left on the terminal: the verdict in
words; each board with its faults and its failed tests, one line of reason each; what was not run and why;
and what to do next, chosen from the faults found (ADVICE). The JSON report is for machines and is unchanged.

ADVICE follows docs/verify.md's "Common failures": a line there that names something to do has its entry here.
"""

import re
import textwrap

DOCS = "https://docs.fpgas.online/en/latest/verify/fpgas-verify.html"
REPO_DOCS = "https://github.com/fpgas-online/fpgas.online-test-designs/blob/main/docs"
ACORN_PROGRAMMING = f"{REPO_DOCS}/hardware/acorn-pcie-programming.md"
ISSUES = "https://github.com/fpgas-online/fpgas.online-test-designs/issues"

VERDICT = {
    "changed": "the board, or what is in its flash, is not what was recorded last time",
    "fail": "a board did not pass",
    "missing": "no board was found",
    "error": "the check itself could not run properly, so it shows nothing about the board",
}

# Board names that are not their package and command names (fpgas-<slug>-debug, fpgas-online-<slug>-debug).
SLUGS = {"tt": "tt-fpga"}
WIDTH = 78  # of the advice, which is sentences; a reason is one line however long, so it can be searched for

# (what a reason says, what to do about it). Every entry whose pattern is found in any reason of the report is
# listed once, in this order.
ADVICE = (
    (r"unconverted: runs SQRL's factory image",
     "The Acorn still runs the image it was sold with, not the fpgas.online one, so only its PCIe link and its "
     "JTAG could be tested. It has to be converted once (the fpgas.online image loaded over JTAG, then written "
     f"to its flash with fpgas-acorn-flash): {ACORN_PROGRAMMING}"),
    (r"unconverted: runs the vendor XDMA sample",
     "The board runs Xilinx's XDMA sample design, not the fpgas.online one. If it is an Acorn, convert it: "
     f"{ACORN_PROGRAMMING}"),
    (r"running the golden image",
     "The Acorn fell back to its golden image: the operational image in its flash did not start. Write the "
     f"operational image again with fpgas-acorn-flash: {ACORN_PROGRAMMING}"),
    (r"is not an Acorn setup in wiring\.toml",
     "This host is not one of the Acorn setups the check knows the wiring of (a Raspberry Pi 5 with the PCIe "
     "HAT, a Compute Blade with a CM4 or CM5), so the tests that use its wires (JTAG, the P2 UART and GPIO) "
     "were not run. The tests over PCIe were."),
    (r"the FPGA has not restarted since",
     "The FPGA kept its configuration across the Pi's restart: power-cycle the Pi (not a reboot), then run the "
     "check again."),
    (r"gpiod_line_request",
     "openFPGALoader could not have one of the JTAG pins, because a driver holds it (on a Compute Blade the "
     "serial port holds GPIO14, which is also the JTAG TMS wire). The check cannot test JTAG on such a host "
     f"yet: {ISSUES}/127"),
    (r"no device on the (P1 )?JTAG chain|no UARTBone reply",
     "Nothing answered on a cable between the Pi and the board: check that the JTAG and UART cables are seated "
     "and wired as the board's page shows."),
    (r"is not installed",
     "A tool the check needs is not installed: the reason above names it (openFPGALoader, openocd, mpremote)."),
    (r"does not match its manifest|manifest\.json is missing",
     "The installed test bitstreams are damaged: sudo apt install --reinstall fpgas-online-<board>-bitstreams"),
    (r"no FPGA board is configured|conflicting fpga-board settings",
     "Say which board this host has: install one board's package (sudo apt install fpgas-online-<board>), or "
     "set `fpga-board` in /etc/fpgas-verify/*.ini."),
    (r"^no .* found: this host is set up for one|^none of the installed boards",
     "Check the board's power and cables. `sudo fpgas-<board>-debug detect` looks for it again without "
     "running the tests."),
)  # fmt: skip


def slug(board):
    return SLUGS.get(board, board)


def _failed(board):
    return [t for t in board.get("tests", []) if t["result"] != "pass"]


def own_reasons(board):
    """The board's reasons that belong to no one test: its reason without each failed test's part of it."""
    text = board.get("reason", "")
    for t in _failed(board):
        text = text.replace(f"{t['test']} {t['result']}: {t.get('reason', '')}", "", 1)
    return [part for part in (p.strip() for p in text.split("; ")) if part]


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _not_run(board):
    """[(the tests, why)]: the tests not run, those with one reason together."""
    by_reason = {}
    for test, why in (board.get("not_run") or {}).items():
        by_reason.setdefault(why, []).append(test)
    return [(tests, why) for why, tests in by_reason.items()]


def _reasons(report):
    out = [report.get("reason", "")]
    for b in report["boards"]:
        out += [*own_reasons(b), *(t.get("reason", "") for t in _failed(b)), *(b.get("not_run") or {}).values()]
    return [r for r in out if r]


def advice(report):
    """What to do about the faults found. `<board>` is the board the host is set up for, when it is for one."""
    reasons = _reasons(report)
    mode = report.get("mode")
    board = slug(mode) if mode and mode != "auto" else "<board>"
    return [text.replace("<board>", board) for pattern, text in ADVICE if any(re.search(pattern, r) for r in reasons)]


def lines(report, kept_in=None):
    """The closing lines for a report whose result is not "pass"."""
    result = report["result"]
    out = ["", f"RESULT: {result.upper()}: {VERDICT.get(result, result)}."]
    if "reason" in report:
        out.append(f"  {report['reason']}")
    for b in report["boards"]:
        tests = b.get("tests", [])
        failed = _failed(b)
        counts = [_plural(len(tests) - len(failed), "test") + " passed", f"{len(failed)} failed"]
        if b.get("not_run"):
            counts.append(f"{len(b['not_run'])} not run")
        out.append(f"  {b['board']} {b.get('variant') or '-'}: {b['result']} ({', '.join(counts)})")
        out += [f"    fault: {reason}" for reason in own_reasons(b)]
        out += [f"    failed: {t['test']}: {t.get('reason') or t['result']}" for t in failed]
        out += [f"    not run: {', '.join(names)}: {why}" for names, why in _not_run(b)]
        if b.get("tests_skipped"):
            out.append(f"    not run: {', '.join(b['tests_skipped'])}: this board has no such test")
    changes = report.get("state", {}).get("changes", [])
    out += [f"  changed: {change}" for change in changes]
    out.append("What to do:")
    todo = advice(report)
    if changes:
        todo.append("If the change was meant (a board flashed or swapped on purpose), accept it: "
                    "sudo fpgas-verify --update")  # fmt: skip
    for b in report["boards"]:
        if b["result"] != "pass":
            todo.append(f"To look at the {b['board']} board by hand: sudo fpgas-{slug(b['board'])}-debug --help "
                        f"(sudo apt install fpgas-online-{slug(b['board'])}-debug)")  # fmt: skip
    todo.append(f"What each message means: {DOCS}#common-failures")
    for text in todo:  # a URL is never broken
        out += textwrap.wrap(text, WIDTH, initial_indent="  * ", subsequent_indent="    ", break_long_words=False,
                             break_on_hyphens=False)  # fmt: skip
    if kept_in and kept_in != "stdout":
        out.append(f"The whole report, for a program to read (JSON): {kept_in}")
    return out
