"""The last lines of a check that did not pass, for a person who has not seen fpgas-verify before.

The summary above them (runner.summary) is every test in the order it ran, with a failed test's last lines of
output. These lines say it again plainly, and last, so they are what is left on the terminal: the verdict in
words; each board with its faults and its failed tests, one line of reason each; what was not run and why;
and what to do next, chosen from the faults found (ADVICE). The JSON report is for machines and is unchanged.

ADVICE follows docs/verify/common-failures.md's "Common failures": a line there that names something to do has
its entry here.
"""

import re
import textwrap

DOCS = "https://docs.fpgas.online/en/latest/verify"  # the pages of docs/verify/, as the site publishes them
REPO_DOCS = "https://github.com/fpgas-online/fpgas.online-test-designs/blob/main/docs"
ACORN_PROGRAMMING = f"{REPO_DOCS}/hardware/acorn-pcie-programming.md"
ISSUES = "https://github.com/fpgas-online/fpgas.online-test-designs/issues"
# An issue the advice points at is named with what it is about, not by its number alone.
ISSUE_127 = "on a Compute Blade the JTAG test cannot have GPIO14 while the serial port holds it"

VERDICT = {
    "changed": "the board, or what is in its flash, is not what was recorded last time",
    "fail": "a board did not pass",
    "missing": "no board was found",
    "error": "the check could not do all of its work; the lines below say what went wrong",
}

# Board names that are not their package and command names (fpgas-<slug>-debug, fpgas-online-<slug>-debug).
SLUGS = {"tt": "tt-fpga"}
BOARDS = "acorn, arty, fomu, netv2 or tt-fpga"  # what <board> stands for, when the report does not say which
# A Xilinx PCIe card that the Acorn's check found but whose IDs name another board (a PCIe Screamer, a PicoEVB:
# boards/acorn/check.py OTHER_BOARDS) is told to people under this name, not as an Acorn. The report's "board"
# stays the key of the check that found it, which the state file and the registry's identity use.
OTHER_PCIE = "xilinx-pcie"
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
    (r"GPIO14 \(TMS\) is held by [0-9a-f]+\.serial \(.*the JTAG chain cannot be scanned",
     "The serial port has a pin JTAG needs, so the JTAG test could not run. On a Compute Blade the JTAG TMS "
     "wire and the serial port's TX are the same pin (GPIO14): while the serial port is on, JTAG cannot be "
     "tested there. Boot with the header's serial port off: in config.txt enable_uart=0 and no "
     "uart_2ndstage=1, in cmdline.txt no console=serial0. On a netbooted blade these files are on the gateway "
     "and may be shared by several hosts: changing the shared files changes every host that boots from them, "
     "giving the one blade its own copy changes only that blade; which to do is the gateway owner's choice. "
     "With all three changes, on one Compute Blade with a CM5, the pin was free and the JTAG test passed "
     f"(fpgas.online-test-designs issue 127, {ISSUE_127}): {ISSUES}/127"),
    # any other holder: not the serial port's own case above, which has its own words
    (r"^(?!.*GPIO14 \(TMS\) is held by [0-9a-f]+\.serial \().*is held by .*the JTAG chain cannot be scanned",
     "A JTAG pin is in use by a driver or by another program (the reason above names it), so the JTAG test "
     "could not run. Stop what has the pin, or take the pin away from it in the boot configuration, and run "
     "the check again."),
    (r"gpiod_line_request",
     "openFPGALoader could not have one of the JTAG pins, because a driver holds it (on a Compute Blade the "
     "serial port holds GPIO14, which is also the JTAG TMS wire). The check cannot test JTAG on such a host "
     f"yet (fpgas.online-test-designs issue 127, {ISSUE_127}): {ISSUES}/127"),
    (r"no device on the (P1 )?JTAG chain|no UARTBone reply",
     "Nothing answered on a cable between the Pi and the board: check that the JTAG and UART cables are seated "
     "and wired as the board's page shows."),
    (r"did not say which Tiny Tapeout board it is",
     "The demo board could not be asked whether it carries an FPGA or a Tiny Tapeout chip, so nothing was "
     "loaded into it. The reason above says what stopped the read; if rpi-hwid is not installed, install it "
     f"(sudo apt install python3-rpi-hwid, from https://github.com/mithro/rpi-hwid): {DOCS}"
     "/tt-fpga.html#which-tiny-tapeout-board-it-is"),
    (r"the u\w+ ribbon \(to HAT J[ABC]\): (?![^;]*held)|ribbons are on each other's HAT ports"
     r"|turned round and one position over",
     "A ribbon cable between the demo board's Pmod connectors and the Pi's Pmod HAT is not where it should be. "
     "The reason names the ribbon (by the demo board's ui_in, uio or uo_out Pmod, and the HAT port it should "
     "go to: ui_in to JA, uio to JB, uo_out to JC) and its Pmod and HAT pins. Seat it, move it to its port, or "
     f"turn it the right way round, and run the check again: {DOCS}/tt-fpga.html#the-wiring-test"),
    (r"the readings fit no single open wire",
     "The wiring test's readings fit no single wrong wire or ribbon: two neighbouring wires of a ribbon are most "
     "likely bridged. Look at the ribbon it names, around the HAT pins it saw joined; its READINGS: lines say what "
     f"each signal reached. Then run the check again: {DOCS}/tt-fpga.html#the-wiring-test"),
    (r"is held high on the demo board",
     "One of the demo board's ui_in lines is held high: a DIP switch that is on ties its line to 3.3 V. Set all "
     f"the DIP switches off and run the check again: {DOCS}/tt-fpga.html#the-wiring-test"),
    (r"is held low on the demo board|is held against the pulls on the demo board|that line is held low"
     r"|holds its line",
     "A line of the demo board's Pmods is held by something other than the check: a short (to ground, or to "
     "another wire), or a chip output that a wrong ribbon joins to it. The check does not drive such a line. Look "
     f"at the ribbon and the pins named for a short: {DOCS}/tt-fpga.html#the-wiring-test"),
    (r"the loopback cannot be confirmed",
     "The wiring test could not use the chip's factory test, because too few of its lines behaved: most often "
     "two ribbons are on each other's HAT ports, or one is turned round. Check that ui_in goes to HAT JA, uio to "
     f"JB and uo_out to JC, each the right way round; if they are, the chip: {DOCS}/tt-fpga.html#the-wiring-test"),
    (r"and the board runs SDK|no SDK release is recorded as supporting",
     "The Tiny Tapeout SDK on the demo board is not a release known to work with the chip it carries, so the "
     "board could not select a project on that chip. The board's firmware is installed by whoever looks after "
     "the board (the check writes nothing to it). If that release does support the chip, the check's table "
     f"lacks it: {ISSUES}"),
    (r"is not running the Tiny Tapeout firmware",
     "The demo board's microcontroller is in its USB boot loader. Power-cycle the board; if it comes back the "
     "same, its firmware has to be installed again by whoever looks after the board."),
    (r"is not installed",
     "A tool the check needs is not installed: the reason above names it."),
    (r"does not match its manifest|manifest\.json is missing",
     "The installed test bitstreams are damaged: sudo apt install --reinstall fpgas-online-<board>-bitstreams"),
    (r"no FPGA board is configured|conflicting fpga-board settings",
     "Say which board this host has: install one board's package (sudo apt install fpgas-online-<board>), or "
     "set `fpga-board` in /etc/fpgas-verify/*.ini."),
    (r"is off USB until it is power-cycled",
     "The Fomu may still be plugged in and working: the last check that found it loaded its test design, which "
     "has no USB, and a reboot does not bring its boot loader back. If it is plugged in, power-cycle the Pi "
     "(switch its power off and on, or its PoE port) and run the check again. If it was unplugged, that is why."),
    (r"^no .* found: this host is set up for one|^none of the installed boards",
     "Check the board's power and cables. `sudo fpgas-<board>-debug detect` looks for it again without "
     "running the tests."),
)  # fmt: skip

# An Acorn on a Compute Blade (the report's `setup`, wiring.toml's carrier name) is not to be converted yet: the only
# load into a card on a blade lost its PCIe endpoint. Where the report names that setup, the conversion advice above
# is replaced; where it names no setup, the warning is added to it, as the host may be a blade.
BLADE = "Compute Blade"
VERIFYING_3 = "https://docs.fpgas.online/en/latest/boards/acorn/building/compute-blade/verifying-3.html"
NOT_ON_A_BLADE = (
    "On a Compute Blade, do not load a design into the card or convert it: that is not in the guide yet. The "
    "only attempt (pi20 at ps1, 7 October 2026) lost the card's PCIe endpoint (a bus rescan did not bring it "
    "back, and a root-complex re-probe failed), and the reboot after it was followed by about two hours of "
    f"restarts, cause not known: {VERIFYING_3}"
)
ON_A_BLADE = {
    r"unconverted: runs SQRL's factory image": "The Acorn still runs the image it was sold with, not the "
    "fpgas.online one, so only its PCIe link and its JTAG could be tested. " + NOT_ON_A_BLADE,
    r"unconverted: runs the vendor XDMA sample": "The board runs Xilinx's XDMA sample design, not the fpgas.online "
    "one. " + NOT_ON_A_BLADE,
    r"running the golden image": "The Acorn fell back to its golden image: the operational image in its flash did "
    "not start. " + NOT_ON_A_BLADE,
}


def _for_setup(pattern, text, setup):
    """An entry's advice for the board's setup: the blade's own where the report says it is a blade, both where it
    names no setup, and the entry's as it is on any other setup."""
    if pattern not in ON_A_BLADE:
        return text
    if setup == BLADE:
        return ON_A_BLADE[pattern]
    if setup is None:
        return f"{text} {NOT_ON_A_BLADE}"
    return text


def slug(board):
    return SLUGS.get(board, board)


def _failed(board):
    return [t for t in board.get("tests", []) if t["result"] != "pass"]


def own_reasons(board):
    """The board's reasons that belong to no one test: its reason without each failed test's part of it.

    One line for each stretch of the reason between two tests' parts. A stretch is not split further: a reason
    can itself hold "; " (a JTAG scan's faults), and half of one would not say what it is about."""
    parts = [board.get("reason", "")]
    fragments = [f"{t['test']} {t['result']}: {t.get('reason', '')}" for t in _failed(board)]
    # a test the board needs and the check does not have (testbench.py's `pending`) is on its "not run" line
    fragments += [f"{test} not run: {why}" for test, why in (board.get("not_run") or {}).items()]
    for fragment in fragments:
        for i, part in enumerate(parts):
            if fragment in part:
                parts[i : i + 1] = part.split(fragment, 1)
                break
    return [part for part in (p.strip().removeprefix(";").removesuffix(";").strip() for p in parts) if part]


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def shown(board):
    """(name, variant) a person is told for one board's report: the other board a card's IDs name is
    xilinx-pcie with what the IDs say it is; every other board is its check's name and its variant."""
    title = (board.get("found") or {}).get("title")
    if title:
        return OTHER_PCIE, title
    return board["board"], board.get("variant")


def _not_run(board):
    """[(the tests, why)]: the tests not run, those with one reason together."""
    by_reason = {}
    for test, why in (board.get("not_run") or {}).items():
        by_reason.setdefault(why, []).append(test)
    return [(tests, why) for why, tests in by_reason.items()]


def _reasons(report):
    """[(the board it is about or None, the reason)]: the report's own, then each board's."""
    out = [(None, report.get("reason", ""))]
    for b in report["boards"]:
        mine = [*own_reasons(b), *(t.get("reason", "") for t in _failed(b)), *(b.get("not_run") or {}).values()]
        out += [(shown(b)[0], r) for r in mine]
    return [(board, r) for board, r in out if r]


def advice(report):
    """What to do about the faults found. `<board>` in an entry is the board its reason is about, or the one
    the host is set up for; when the report names neither, the reader is told what it stands for."""
    reasons = _reasons(report)
    mode = report.get("mode")
    out = []
    for pattern, text in ADVICE:
        about = [board for board, r in reasons if re.search(pattern, r)]
        if not about:
            continue
        board = about[0] or (mode if mode and mode != "auto" else None)
        if board == OTHER_PCIE and "<board>" in text:  # an Acorn tool is not for another board, nor is one ours
            continue
        setup = next((b.get("setup") for b in report["boards"] if b["board"] == board), None)
        text = _for_setup(pattern, text, setup)
        if "<board>" in text:
            text = text.replace("<board>", slug(board)) if board else f"{text} (<board> is {BOARDS})"
        out.append(text)
    return out


def lines(report, kept_in=None):
    """The closing lines for a report whose result is not "pass"."""
    result = report["result"]
    out = ["", f"RESULT: {result.upper()}: {VERDICT.get(result, result)}."]
    if "reason" in report:
        out.append(f"  {report['reason']}")
    for b in report["boards"]:
        tests = b.get("tests", [])
        failed = _failed(b)
        counts = [_plural(len(tests) - len(failed), "test") + " passed", f"{len(failed)} failed"] if tests else []
        if b.get("not_run"):
            counts.append(f"{len(b['not_run'])} not run")
        name = " ".join(filter(None, shown(b)))
        out.append(f"  {name}: {b['result']} ({', '.join(counts) or 'no test ran'})")
        out += [f"    fault: {reason}" for reason in own_reasons(b)]
        out += [f"    failed: {t['test']}: {t.get('reason') or t['result']}" for t in failed]
        out += [f"    not run: {', '.join(names)}: {why}" for names, why in _not_run(b)]
        if b.get("tests_skipped"):
            out.append(f"    not run: {', '.join(b['tests_skipped'])}: this board has no such test")
        out += [f"    warning (not why it did not pass): {w}" for w in b.get("warnings", [])]
    changes = report.get("state", {}).get("changes", [])
    out += [f"  changed: {change}" for change in changes]
    out.append("What to do:")
    todo = advice(report)
    if changes:
        todo.append("If the change was meant (a board flashed or swapped on purpose), accept it: "
                    "sudo fpgas-verify --update")  # fmt: skip
    for b in report["boards"]:
        if b["result"] != "pass" and shown(b)[0] != OTHER_PCIE:  # no debug tool is ours for another board
            todo.append(f"To look at the {b['board']} board yourself: sudo fpgas-{slug(b['board'])}-debug --help "
                        f"(sudo apt install fpgas-online-{slug(b['board'])}-debug)")  # fmt: skip
    todo.append(f"What each message means: {DOCS}/common-failures.html#common-failures")
    for text in todo:  # a URL is never broken
        out += textwrap.wrap(text, WIDTH, initial_indent="  * ", subsequent_indent="    ", break_long_words=False,
                             break_on_hyphens=False)  # fmt: skip
    if kept_in and kept_in != "stdout":
        out.append(f"The whole report, for a program to read (JSON): {kept_in}")
    return out
