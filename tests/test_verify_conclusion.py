"""The last lines of a check that did not pass (fpgas_online_verify.conclusion), on canned reports.

They are for a person who has not seen fpgas-verify before (issue #125): the verdict in words, each fault and
each failed test with one line of reason, what was not run and why, and what to do next. The first report here
is a real one: a Compute Blade with a CM5 and an Acorn CLE-101 still on SQRL's factory image, as its owner met
it after following docs/verify.md.
"""

import json
import pathlib

from fpgas_online_verify import conclusion, runner
from fpgas_online_verify.boards.acorn import check, links, setup, suite

DATA = pathlib.Path(__file__).parent / "data"
KEPT_IN = "/run/fpgas-online/verify.json"
UNCONVERTED = "unconverted: runs SQRL's factory image, not the fpgas.online design"
GPIOD = ("P1 JTAG: openFPGALoader --detect failed (exit -6) before scanning the JTAG chain: openFPGALoader: "
         "line-request.c:199: gpiod_line_request_set_values_subset: Assertion `request' failed.")  # fmt: skip


def _blade():
    return json.loads((DATA / "compute-blade-cle-101-factory.json").read_text())


def _report(result, boards=(), **more):
    return {"schema_version": 2, "result": result, "checked_at": "2026-10-05T00:00:00+00:00", "mode": "acorn",
            "chosen_by": "configured: acorn", "boards": list(boards), "state": {}, **more}  # fmt: skip


def _acorn(result, tests, **more):
    return {"board": "acorn", "variant": "cle-215+", "result": result,
            "tests": [{"test": name, "result": r, **({"reason": why} if why else {})} for name, r, why in tests],
            **more}  # fmt: skip


def test_the_unconverted_compute_blade_ends_with_what_failed_what_was_not_run_and_what_to_do():
    lines = runner.summary(_blade(), KEPT_IN).splitlines()
    start = lines.index("RESULT: FAIL: a board did not pass.")
    assert lines[start - 1] == ""
    assert lines[start + 1 : start + 7] == [
        "  acorn cle-101: fail (2 tests passed, 1 failed, 7 not run)",
        f"    fault: {UNCONVERTED}",
        f"    failed: jtag: {GPIOD}",
        f"    not run: pcie-bar0, flash, ddr, p2-serial, scratch: {UNCONVERTED}",
        "    not run: p2-uart: the board does not run a known build",
        "    not run: p2-gpio: J5 and H5 are not wired on the Compute Blade setup",
    ]
    assert lines[start + 7] == "What to do:"
    todo = "\n".join(lines[start + 8 :])
    assert "It has to be converted" in todo and conclusion.ACORN_PROGRAMMING in todo
    assert "the serial port holds GPIO14" in todo and f"{conclusion.ISSUES}/127" in todo
    assert "sudo fpgas-acorn-debug --help" in todo and "fpgas-online-acorn-debug" in todo
    assert f"{conclusion.DOCS}#common-failures" in todo
    # the verdict and where the report is are the last things on the terminal
    assert lines[-2:] == [f"The whole report, for a program to read (JSON): {KEPT_IN}", "*" * 78]


def test_the_boards_line_no_longer_joins_every_fault():
    """Each fault is on a line of its own: the board's, then each test's beside the test."""
    lines = runner.summary(_blade()).splitlines()
    at = lines.index("  acorn cle-101: fail")
    assert lines[at + 1] == f"    {UNCONVERTED}"
    assert lines[at + 4] == f"    jtag       fail: {GPIOD}"


def test_a_pass_has_no_closing_lines():
    text = runner.summary(_report("pass", [_acorn("pass", [("pcie-link", "pass", None)])]), KEPT_IN)
    assert "RESULT" not in text and "What to do" not in text and "***" not in text


def test_the_golden_image_says_to_write_the_operational_image_again():
    golden = "running the golden image: the operational slot did not boot"
    board = _acorn("fail", [("pcie-link", "pass", None), ("pcie-bar0", "fail", golden), ("flash", "pass", None)],
                   reason=f"pcie-bar0 fail: {golden}", not_run={"ddr": "the golden image has no DRAM"})  # fmt: skip
    lines = conclusion.lines(_report("fail", [board]), KEPT_IN)
    assert "  acorn cle-215+: fail (2 tests passed, 1 failed, 1 not run)" in lines
    assert f"    failed: pcie-bar0: {golden}" in lines
    assert "    not run: ddr: the golden image has no DRAM" in lines
    assert not [line for line in lines if line.startswith("    fault:")]  # the only reason is the test's own
    assert "Write the operational image again with fpgas-acorn-flash" in " ".join(line.strip() for line in lines)


def test_a_host_that_is_no_acorn_setup_is_told_which_tests_that_stopped():
    why = ("this host (Raspberry Pi 4 Model B Rev 1.4) is not an Acorn setup in wiring.toml: Raspberry Pi 5 Model B "
           "(Raspberry Pi 5), Raspberry Pi Compute Module 4 (Compute Blade)")  # fmt: skip
    unknown = "this host's setup is not known"
    board = _acorn("error", [("pcie-bar0", "pass", None)], reason=why, not_run={"jtag": unknown, "p2-uart": unknown})
    lines = conclusion.lines(_report("error", [board]))
    assert lines[1] == "RESULT: ERROR: the check could not do all of its work; the lines below say what went wrong."
    assert f"    fault: {why}" in lines
    assert "    not run: jtag, p2-uart: this host's setup is not known" in lines
    assert "The tests over PCIe were." in " ".join(line.strip() for line in lines)


def test_a_missing_board_names_the_boards_own_debug_command():
    why = "no Digilent Arty A7 found: this host is set up for one, and nothing else is looked for"
    lines = conclusion.lines({**_report("missing", reason=why), "mode": "arty"}, KEPT_IN)
    assert lines[1:3] == ["RESULT: MISSING: no board was found.", f"  {why}"]
    assert "`sudo fpgas-arty-debug detect`" in " ".join(lines)


def test_with_auto_the_reader_is_told_what_board_stands_for():
    why = "none of the installed boards (arty, tt) was found (auto: USB/PCI IDs)"
    text = " ".join(line.strip() for line in conclusion.lines({**_report("missing", reason=why), "mode": "auto"}))
    assert "`sudo fpgas-<board>-debug detect`" in text and "(<board> is acorn, arty, fomu, netv2 or tt-fpga)" in text


def test_advice_about_one_boards_fault_names_that_board_even_with_auto():
    board = {"board": "tt", "result": "error", "reason": "x.bit does not match its manifest", "tests": []}
    text = " ".join(line.strip() for line in conclusion.lines({**_report("error", [board]), "mode": "auto"}))
    assert "sudo apt install --reinstall fpgas-online-tt-fpga-bitstreams" in text and "<board>" not in text


def test_a_check_that_passed_but_could_not_start_a_service_again_is_not_said_to_show_nothing():
    """runner.run() makes the result an error when a service it stopped does not start: the board still passed."""
    why = "fpgas-tt.service was not started again: Job failed"
    board = {"board": "tt", "result": "pass", "tests": [{"test": "uart", "result": "pass"}]}
    lines = conclusion.lines(_report("error", [board], reason=why))
    assert lines[1:4] == ["RESULT: ERROR: the check could not do all of its work; the lines below say what went wrong.",
                          f"  {why}", "  tt: pass (1 test passed, 0 failed)"]  # fmt: skip
    assert not [line for line in lines if "debug" in line]


def test_a_board_whose_check_stopped_before_any_test_says_no_test_ran():
    board = {"board": "acorn", "result": "error", "reason": "the check crashed: KeyError: 'x'"}
    lines = conclusion.lines(_report("error", [board]))
    assert lines[2:4] == ["  acorn: error (no test ran)", "    fault: the check crashed: KeyError: 'x'"]


def test_a_reason_that_holds_a_semicolon_stays_one_line():
    """testbench.py's JTAG entry is not one of the tests, and its reason joins the scan's faults with "; "."""
    jtag = "jtag fail: no device on the JTAG chain; openFPGALoader exited 1 reading the IDCODE"
    board = {"board": "arty", "variant": "a7-35", "result": "fail", "reason": f"{jtag}; ddr fail: the test exited 1",
             "tests": [{"test": "ddr", "result": "fail", "reason": "the test exited 1"}]}  # fmt: skip
    assert conclusion.own_reasons(board) == [jtag]
    between = {**board, "reason": "before; ddr fail: the test exited 1; after; more"}
    assert conclusion.own_reasons(between) == ["before", "after; more"]


def test_the_tt_boards_commands_are_named_tt_fpga():
    board = {"board": "tt", "variant": None, "result": "fail", "reason": "uart fail: the test exited 1",
             "tests": [{"test": "uart", "result": "fail", "reason": "the test exited 1"}]}  # fmt: skip
    lines = conclusion.lines(_report("fail", [board]))
    assert "  tt: fail (0 tests passed, 1 failed)" in lines
    assert "sudo fpgas-tt-fpga-debug --help" in " ".join(lines)


def test_a_change_says_how_to_accept_it():
    report = _report("changed", [_acorn("pass", [("flash", "pass", None)])])
    report["state"] = {"changes": ["acorn.flash.slots: was 'aaaa', now 'bbbb'"], "file": "/var/lib/x.json"}
    lines = runner.summary(report, KEPT_IN).splitlines()
    assert "RESULT: CHANGED: the board, or what is in its flash, is not what was recorded last time." in lines
    assert "  changed: acorn.flash.slots: was 'aaaa', now 'bbbb'" in lines
    assert "sudo fpgas-verify --update" in "\n".join(lines)
    assert not [line for line in lines if "debug" in line]  # the board itself passed


def test_tests_asked_for_that_a_board_does_not_have_are_listed_as_not_run():
    board = {**_acorn("fail", [("jtag", "fail", "no device on the P1 JTAG chain")]), "tests_skipped": ["uart"]}
    lines = conclusion.lines(_report("fail", [board]))
    assert "    not run: uart: this board has no such test" in lines
    assert "check that the JTAG and UART cables are seated" in " ".join(line.strip() for line in lines)


def test_a_reason_is_one_line_and_the_advice_is_wrapped_without_breaking_a_url():
    lines = conclusion.lines(_blade(), KEPT_IN)
    start = lines.index("What to do:")
    advice = lines[start + 1 : -1]
    assert all(len(line) <= conclusion.WIDTH or "https://" in line for line in advice)
    assert f"    {conclusion.ACORN_PROGRAMMING}" in advice  # whole, on a line of its own
    assert f"    failed: jtag: {GPIOD}" in lines  # not wrapped: a reason can be searched for as it is


def test_a_report_on_stdout_is_not_given_as_a_file():
    assert not [line for line in conclusion.lines(_blade(), "stdout") if "whole report" in line]
    assert not [line for line in conclusion.lines(_blade()) if "whole report" in line]


def test_a_boards_own_reasons_are_its_reason_without_its_tests_parts():
    board = _blade()["boards"][0]
    assert conclusion.own_reasons(board) == [UNCONVERTED]
    assert conclusion.own_reasons({"tests": [], "reason": "one; two"}) == ["one; two"]
    assert conclusion.own_reasons({"tests": []}) == []


def test_every_advice_pattern_matches_a_reason_the_code_gives():
    """Each entry is found by a reason as the check words it. Where the code has the wording as a value it is
    taken from there, so rewording it there without the entry fails here; the rest are copies."""
    reasons = [
        *(check.not_ours({"kind": kind, "ids": "", "subsystem": ""}) for kind in ("sqrl-factory", "vendor-xdma")),
        suite.GOLDEN,
        "this host (x) is not an Acorn setup in wiring.toml: y",
        "the FPGA has not restarted since an earlier boot's check",
        GPIOD,
        links.pins_held(setup.detect("Raspberry Pi Compute Module 5 Rev 1.0"), {14: "1f00030000.serial (uart0)"}),
        "no device on the P1 JTAG chain",
        "openocd is not installed",
        "x does not match its manifest",
        "manifest.json is missing",
        "no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)",
        "no FPGA board is configured",
        "conflicting fpga-board settings: a and b",
        "none of the installed boards (arty, tt) was found (auto: USB/PCI IDs)",
        "no Sqrl Acorn found: this host is set up for one, and nothing else is looked for",
    ]
    for pattern, _ in conclusion.ADVICE:
        assert any(conclusion.re.search(pattern, r) for r in reasons), pattern
    for alternative in [a for pattern, _ in conclusion.ADVICE for a in pattern.split("|")]:
        assert any(conclusion.re.search(alternative, r) for r in reasons), alternative


def test_the_docs_show_what_the_code_prints_for_the_real_report():
    """docs/verify.md's first failing example is this report's summary, line for line."""
    docs = (pathlib.Path(__file__).parents[1] / "docs" / "verify.md").read_text()
    assert runner.summary(_blade(), KEPT_IN).strip("\n") in docs
