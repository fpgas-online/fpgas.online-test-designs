"""Write docs/verify/checks.md: a section per check fpgas-verify's boards plan, so that each check's name on the
fpgas.online dashboards links its own documentation (fpgas.online-site#140; Tim, 16 Oct 2026: "Why doesn't the check
link take you to the docs for the specific check and just dumps you at a top level page?").

Everything on the page comes from the board modules themselves (Board.planned, about, untested, derived,
not_applicable, and each test's host script), never from a hand-kept list: a check a board plans gets a section, a
planned test with no description stops the generator, and tests/test_checks_doc.py fails when the committed page is
not what this writes.

    uv run python scripts/gen_checks_doc.py           # write the page
    uv run python scripts/gen_checks_doc.py --check   # exit 1 if the committed page is out of date
"""

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify" / "src"))  # the checkout's fpgas-verify, as tests/conftest.py does

from fpgas_online_verify import board as board_api  # noqa: E402
from fpgas_online_verify import host_tests  # noqa: E402
from fpgas_online_verify.testbench import TestBoard  # noqa: E402

PAGE = REPO / "docs" / "verify" / "checks.md"
ISSUE = "https://github.com/fpgas-online/fpgas.online-test-designs/issues/{}"
# Acorn's power-cycle test runs only when the check is asked for it (power_cycle_check in fpgas-verify.toml).
ASKED = {"power_cycle_check": True}


BOARD_VARIANTS = {}  # board title -> its variants, as collect() found them


class GapError(Exception):
    """A planned test the board modules say nothing about: the page would have a hole, so nothing is written."""


def variants_of(board):
    """Every variant a board module names, in its own order; [None] for a board that plans the same for all."""
    if not isinstance(board, TestBoard):
        return [None]
    out = list(board.variants)
    for spec in (*board.fact_tests.values(), *board.script_tests.values()):
        out += list(spec["variants"])
    for table in (board.not_yet, board.cannot, board.derives, board.abouts_by_variant):
        out += list(table)
    return list(dict.fromkeys(out))


def runs(board, variant, test, untested, derived, only_when_asked):
    """What the check runs for `test`, in Markdown: its host script, what it is derived from, or why it does not run."""
    if test in untested:
        return f"not run yet: [#{untested[test]}]({ISSUE.format(untested[test])})"
    if test in derived:
        sources = ", ".join(f"[`{s}`](#{s})" for s in derived[test][0])
        return f"derived from {sources}"
    if not isinstance(board, TestBoard):
        text = "the Acorn suite ([what an Acorn check tests](acorn.md#acorn))"
        return text + (" when the check is asked for it (`power_cycle_check`)" if only_when_asked else "")
    if variant is None:
        return "what the board's variant calls for, once the check knows it"
    script = board.script_tests.get(test)
    if script and variant in script["variants"]:  # a script on the board's port; nothing is loaded
        return f"runs [`{script['script']}`](../../{host_tests.SCRIPTS[script['script']]}); loads nothing"
    spec = board.tests.get(test)
    if spec and spec.get("script"):
        return f"loads its test design, then runs [`{spec['script']}`](../../{host_tests.SCRIPTS[spec['script']]})"
    if test in board.fact_tests:
        return "reads what the board says of itself; loads nothing"
    if test == "jtag" and variant in board.idcodes:
        return "reads the JTAG IDCODE and device DNA; loads nothing"
    if test == board.closing_test:
        return "the last step, after every test"
    raise GapError(f"{board.title} {variant}: no way to say what runs for {test!r}")


def collect():
    """({check: [row]}, {check: [(board title, why not)]}, the checks in order). A row is (board, variants, what it
    checks, what runs)."""
    rows, not_for, order = {}, {}, []
    for board in board_api.installed().values():
        BOARD_VARIANTS[board.title] = variants_of(board)
        for variant in variants_of(board):
            planned = board.planned(variant)
            asked = [t for t in board.planned(variant, ASKED) if t not in planned]
            about = board.about(variant)
            untested, derived = board.untested(variant), board.derived(variant)
            for test in [*planned, *asked]:
                text = about.get(test)
                if not text:
                    raise GapError(f"{board.title} {variant}: {test!r} is planned and has no description")
                key = (board.title, text, runs(board, variant, test, untested, derived, test in asked))
                order.append(test)
                found = next((r for r in rows.setdefault(test, []) if r[0] == key), None)
                if found:
                    found[1].append(variant)
                else:
                    rows[test].append((key, [variant]))
            for check, why in board.not_applicable(variant).items():
                not_for.setdefault(check, {}).setdefault((board.title, why), []).append(variant)
    return rows, not_for, list(dict.fromkeys(order))


def variants_text(board_variants, variants):
    """The variants a row is for: "every" for a board that plans the same for all, "not yet known" for a board whose
    check has not settled its variant."""
    if variants == [None]:
        return "every" if board_variants == [None] else "not yet known"
    return ", ".join(f"`{v}`" if v else "not yet known" for v in variants)


def page():
    rows, not_for, order = collect()
    out = [
        "# Each check, what it tests",
        "",
        "<!-- Generated by scripts/gen_checks_doc.py from fpgas-verify's board modules. Do not edit: change the "
        "board module, then run `uv run python scripts/gen_checks_doc.py`. -->",
        "",
        "A section for every check fpgas-verify runs on a board, named as the fpgas.online dashboards name it: for "
        "each board type that gets the check, what it checks and what the check runs. How the whole check runs, and "
        "the details of each test, are on [what the check tests on each board](tests.md) and "
        "[what an Acorn check tests](acorn.md#acorn).",
        "",
        "Checks: " + ", ".join(f"[`{c}`](#{c})" for c in order) + ".",
        "",
        "## Boot check",
        "",
        "The check fpgas-verify runs at every boot of a Pi with an FPGA board: it finds the board, runs every check "
        "below that the board's type gets, in order, and reports one result for the boot: `pass` (every check "
        "passed), `fail` (a check failed), `error` (the check could not finish), or `missing` (it found no board). "
        "The dashboards show it as the Boot check column; a board is offered to visitors only after a `pass`. "
        "[Reading the result](reading-the-result.md) says what each result means.",
        "",
        "## Check ran",
        "",
        "When the boot check of the boot the Pi is running reported its result (its `fpga-verified` event). A Pi "
        "checks again at its next boot; until then this time does not change.",
        "",
    ]
    for check in order:
        out += [f"## {check}", "", "| Board | Variants | What it checks | What the check runs |", "|---|---|---|---|"]
        for (title, text, ran), variants in rows[check]:
            out.append(f"| {title} | {variants_text(BOARD_VARIANTS[title], variants)} | {text} | {ran} |")
        nots = not_for.get(check, {})
        if nots:
            out += ["", "Not for:", ""]
            for (title, why), variants in nots.items():
                which = variants_text(BOARD_VARIANTS[title], variants)
                out.append(f"* {title}" + ("" if which == "every" else f" ({which})") + f": {why}")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed page is out of date")
    args = parser.parse_args(argv)
    text = page()
    if args.check:
        if not PAGE.is_file() or PAGE.read_text() != text:
            print(
                f"{PAGE.relative_to(REPO)} is out of date: run uv run python scripts/gen_checks_doc.py", file=sys.stderr
            )
            return 1
        return 0
    PAGE.write_text(text)
    print(f"wrote {PAGE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
