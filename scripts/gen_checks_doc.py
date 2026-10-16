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
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify" / "src"))  # the checkout's fpgas-verify, as tests/conftest.py does

from fpgas_online_verify import board as board_api  # noqa: E402
from fpgas_online_verify import checks, host_tests  # noqa: E402
from fpgas_online_verify.boards.acorn import suite as acorn_suite  # noqa: E402
from fpgas_online_verify.testbench import TestBoard  # noqa: E402

PAGE = REPO / "docs" / "verify" / "checks.md"
FAILURES = REPO / "docs" / "verify" / "common-failures.md"
# A message of one test's own, quoted in a common-failures row as the board's reason gives it: "`<test> fail: …`".
TEST_MESSAGE = re.compile(r"`([a-z0-9-]+) (?:fail|error): ")
ANY_CHECK = (
    "The messages any check can give (a design that would not load, a test that did not finish, a tool or package "
    "missing, a planned test that has no boot-check test yet) are in "
    "[common failures](common-failures.md#common-failures)."
)
ISSUE = "https://github.com/fpgas-online/fpgas.online-test-designs/issues/{}"
# Acorn's power-cycle test runs only when the check is asked for it (power_cycle_check in fpgas-verify.toml).
ASKED = {"power_cycle_check": True}


BOARD_VARIANTS = {}  # board title -> its variants, as collect() found them


class GapError(Exception):
    """A planned test the board modules say nothing about: the page would have a hole, so nothing is written."""


def acorn_details():
    """{test: what the Acorn check does for it}, from the table in the Acorn suite's docstring: its own words, with the
    conditions it states ("on a Pi 5 / CM5", "on a setup whose cable carries them")."""
    out, test = {}, None
    for line in (acorn_suite.__doc__ or "").splitlines():
        m = re.match(r"^  ([a-z0-9-]+)  +(\S.*)$", line)
        if m:
            test = m[1]
            out[test] = m[2].strip()
        elif test and re.match(r"^ {6,}\S", line):
            out[test] += " " + line.strip()
        else:
            test = None
    return out


ACORN_DIR = pathlib.Path(acorn_suite.__file__).resolve().parent
# A file the Acorn suite's text names ("links.py", "expected.toml") or a module's attribute
# ("check.power_cycle_verdict"), not part of a longer name or path ("fpgas-verify.toml" is the Pi's configuration,
# not a file of this repository).
NAMED_FILE = re.compile(r"(?<![\w./-])([a-z_][a-z0-9_]*)\.(py|toml)\b")
NAMED_ATTR = re.compile(r"(?<![\w./-])([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b(?!\.)")


def repo_files():
    return subprocess.run(
        ["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()


def repo_path(name):
    """This repository's path of a file the Acorn suite names: in the Acorn module's own directory, else the one file
    of that name in the repository. None or two candidates stop the generator: a link is never guessed."""
    own = ACORN_DIR / name
    if own.is_file():
        return own.relative_to(REPO).as_posix()
    found = [f for f in repo_files() if pathlib.PurePosixPath(f).name == name]
    if len(found) != 1:
        raise GapError(
            f"the Acorn suite names {name!r}, which is {len(found)} files of this repository: link it by path"
        )
    return found[0]


def linked(text):
    """`text` with each file it names linked to that file in this repository (the page is docs/verify/checks.md), and
    each Acorn module's attribute it names (check.power_cycle_verdict) linked to its module."""

    def file_link(m):
        return f"[`{m[0]}`](../../{repo_path(m[0])})"

    def attr_link(m):
        module = ACORN_DIR / f"{m[1]}.py"
        if m[2] in ("py", "toml") or not module.is_file():
            return m[0]
        return f"[`{m[0]}`](../../{module.relative_to(REPO).as_posix()})"

    return NAMED_ATTR.sub(attr_link, NAMED_FILE.sub(file_link, text))


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
        issue = f"[#{untested[test]}]({ISSUE.format(untested[test])})"
        if checks.UNTESTED_FAILS:
            return f"not run yet ({issue}): until it is, the board fails its check with this test as not run"
        return f"not run yet ({issue}): the board can still pass"
    if test in derived:
        sources = ", ".join(f"[`{s}`](#{s})" for s in derived[test][0])
        return f"derived from {sources}"
    if not isinstance(board, TestBoard):
        detail = acorn_details().get(test)
        if not detail:
            raise GapError(f"{board.title}: the Acorn suite's docstring has no line for {test!r}")
        return linked(detail.rstrip(".")) + (f"; {acorn_suite.OPT_IN.split(': ', 1)[1]}" if only_when_asked else "")
    if variant is None:
        return "the tests of the board's own variant (the rows above), once the board has said which it is"
    script = board.script_tests.get(test)
    if script and variant in script["variants"]:  # a script on the board's port; nothing is loaded
        return f"runs [`{script['script']}`](../../{host_tests.SCRIPTS[script['script']]}); loads nothing"
    spec = board.tests.get(test)
    if spec and spec.get("script"):
        return f"loads its test design, then runs [`{spec['script']}`](../../{host_tests.SCRIPTS[spec['script']]})"
    if test in board.fact_tests:
        reads = board.fact_tests[test].get("reads")
        if not reads:
            raise GapError(f"{board.title}: the fact test {test!r} does not say what it reads")
        return f"judges what the check read: {reads}"
    if test == "jtag" and variant in board.idcodes:
        return "reads the JTAG IDCODE and device DNA; loads nothing"
    if test == board.closing_test:
        closing = getattr(board, "closing_runs", None)
        if not closing:
            raise GapError(f"{board.title}: the closing step {test!r} does not say what it runs")
        return closing
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
    order = list(dict.fromkeys(order))
    # a check some board is not for and no board plans still has its section: its "Not for" lines
    return rows, not_for, order + [c for c in not_for if c not in order]


def failure_rows(checks_on_page):
    """({check: [row]}, the table's header lines): the rows of common-failures.md's table that quote a check's own
    message ("`<check> fail: …`"), copied whole, so the reader has what to do where they are. A row naming a check this
    page has no section for stops the generator: it is a misspelt name, or a check no board plans."""
    lines = FAILURES.read_text().splitlines()
    try:
        start = lines.index("| It says | Meaning, and what to do |")
    except ValueError:
        raise GapError(f"{FAILURES.name} has no table headed 'It says | Meaning, and what to do'") from None
    header = lines[start : start + 2]
    out = {}
    for line in lines[start + 2 :]:
        if not line.startswith("| "):
            break
        named = list(dict.fromkeys(TEST_MESSAGE.findall(line.split(" | ", 1)[0])))
        for check in named:
            if check not in checks_on_page:
                raise GapError(f"{FAILURES.name} quotes a message of {check!r}, which has no section here")
            out.setdefault(check, []).append(line)
    return out, header


def variants_text(board_variants, variants):
    """The variants a row is for: "every" for a board that plans the same for all, "not yet known" for a board whose
    check has not settled its variant."""
    if variants == [None]:
        return "every" if board_variants == [None] else "not yet known"
    return ", ".join(f"`{v}`" if v else "not yet known" for v in variants)


def page():
    rows, not_for, order = collect()
    failures, failures_header = failure_rows(order)
    out = [
        "# Each check, what it tests",
        "",
        "<!-- Generated by scripts/gen_checks_doc.py from fpgas-verify's board modules. Do not edit: change the "
        "board module, then run `uv run python scripts/gen_checks_doc.py`. -->",
        "",
        "For anyone who clicked a check's name on an fpgas.online dashboard, or who runs fpgas-verify on an Arty A7, "
        "NeTV2, Fomu EVT, TT FPGA demo board or Acorn: a section for every check, named as the dashboards name it, "
        "with, for each board type that gets it, what it checks and what the check runs, and the board types it is "
        "not for and why. How the whole check runs is on [what the check tests on each board](tests.md) and "
        "[what an Acorn check tests](acorn.md#acorn).",
        "",
        "Checks: [Boot check](#boot-check), [Check ran](#check-ran), "
        + ", ".join(f"[`{c}`](#{c})" for c in order)
        + ".",
        "",
        "## Boot check",
        "",
        "The check fpgas-verify runs at every boot of a Pi with an FPGA board: it finds the board, runs every check "
        "below that the board's type gets, in order, and reports one result for the boot: `pass` (every check "
        "passed), `fail` (a check failed), `error` (the check could not finish), or `missing` (it found no board). "
        "The dashboards show it as the Boot check column; a board is offered to visitors only after a `pass`. "
        "[Reading the result](reading-the-result.md) says what each result means, and "
        "[common failures](common-failures.md#common-failures) what to do about each message.",
        "",
        "## Check ran",
        "",
        "When the boot check of the boot the Pi is running reported its result (its `fpga-verified` event). A Pi "
        "checks again at its next boot; until then this time does not change.",
        "",
    ]
    for check in order:
        out += [f"## {check}", "", "| Board | Variants | What it checks | What the check runs |", "|---|---|---|---|"]
        for (title, text, ran), variants in rows.get(check, []):
            out.append(f"| {title} | {variants_text(BOARD_VARIANTS[title], variants)} | {text} | {ran} |")
        nots = not_for.get(check, {})
        if nots:
            out += ["", "Not for:", ""]
            for (title, why), variants in nots.items():
                which = variants_text(BOARD_VARIANTS[title], variants)
                out.append(f"* {title}" + ("" if which == "every" else f" ({which})") + f": {why}")
        out += ["", "When it fails:", ""]
        if failures.get(check):
            out += [*failures_header, *failures[check], ""]
        else:
            out += ["Its reason is the last line its test printed.", ""]
        out += [ANY_CHECK, ""]
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
