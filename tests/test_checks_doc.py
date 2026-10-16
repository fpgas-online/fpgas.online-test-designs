"""docs/verify/checks.md, the page the fpgas.online dashboards link each check's name to (fpgas.online-site#140), is
what scripts/gen_checks_doc.py writes from the board modules, and has a section for every check any board plans."""

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gen_checks_doc", REPO / "scripts" / "gen_checks_doc.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def headings():
    return re.findall(r"^## (.+)$", gen.PAGE.read_text(), re.M)


def test_the_committed_page_is_what_the_board_modules_say():
    assert gen.main(["--check"]) == 0, "run: uv run python scripts/gen_checks_doc.py"


def test_every_check_any_board_plans_has_its_own_section():
    planned = set()
    for board in gen.board_api.installed().values():
        for variant in gen.variants_of(board):
            planned.update(board.planned(variant))
            planned.update(board.planned(variant, gen.ASKED))
    assert planned and planned <= set(headings())


def section(check):
    return gen.PAGE.read_text().split(f"\n## {check}\n", 1)[1].split("\n## ", 1)[0]


def test_each_check_section_says_its_group_on_the_dashboards():
    for check in headings():
        if check in gen.checks.GROUP_OF:
            assert f"Group on the dashboards: `{gen.checks.GROUP_OF[check]}`." in section(check), check


def test_the_page_says_what_each_group_holds():
    assert set(gen.checks.GROUP_ABOUT) == set(gen.checks.GROUPS)
    assert all(f"| `{g}` | {gen.checks.GROUP_ABOUT[g]} |" in gen.PAGE.read_text() for g in gen.checks.GROUPS)


def test_the_dashboards_two_other_columns_have_sections_too():
    assert {"Boot check", "Check ran"} <= set(headings())


@pytest.mark.parametrize("name", sorted(gen.board_api.installed()))
def test_a_planned_test_with_no_description_writes_nothing(monkeypatch, tmp_path, name):
    """Any board whose description of a planned test is missing stops the generator before the page is written."""
    board = gen.board_api.installed()[name]
    monkeypatch.setattr(type(board), "about", lambda self, variant, found=None: {})
    monkeypatch.setattr(gen, "PAGE", tmp_path / "checks.md")
    with pytest.raises(gen.GapError, match="is planned and has no description"):
        gen.main([])
    assert not (tmp_path / "checks.md").exists()


def test_every_acorn_test_and_fact_test_says_what_it_runs():
    """The Acorn rows carry the suite's own line for the test, the fact tests what they read: never one generic line
    for all of them (the review of #354)."""
    text = gen.PAGE.read_text()
    details = gen.acorn_details()
    for test in gen.acorn_suite.SELECTABLE:
        assert details.get(test) and gen.linked(details[test].rstrip(".")) in text, test
    for board in gen.board_api.installed().values():
        for test, spec in getattr(board, "fact_tests", {}).items():
            assert spec["reads"] in text, (board.title, test)


def test_the_index_names_every_section_the_dashboards_link():
    """#357: the "Checks:" line at the top links every section, Boot check and Check ran too."""
    index = next(line for line in gen.PAGE.read_text().splitlines() if line.startswith("Checks: "))
    anchors = re.findall(r"\]\(#([^)]+)\)", index)
    slugs = [h.lower().replace(" ", "-") for h in headings()]
    assert anchors[:2] == ["boot-check", "check-ran"] and sorted(anchors) == sorted(slugs)


def test_a_file_the_acorn_rows_name_links_to_it_in_this_repository():
    """#357: links.py, bist.py, expected.toml and check.power_cycle_verdict are links to the files, and a name that is
    no file here stops the generator rather than being left plain or guessed."""
    text = gen.PAGE.read_text()
    acorn = "../../verify/src/fpgas_online_verify/boards/acorn/"
    for name, path in [("links.py", f"{acorn}links.py"), ("bist.py", f"{acorn}bist.py"),
                       ("expected.toml", "../../docs/wiring/acorn/expected.toml"),
                       ("check.power_cycle_verdict", f"{acorn}check.py")]:  # fmt: skip
        assert f"[`{name}`]({path})" in text, name
        assert (gen.PAGE.parent / path).resolve().is_file(), path
    assert gen.linked("read by fpgas-verify.toml and e.g. so on") == "read by fpgas-verify.toml and e.g. so on"
    with pytest.raises(gen.GapError, match=r"'nowhere\.py', which is 0 files"):
        gen.linked("see nowhere.py")


def test_each_check_says_what_to_do_when_it_fails_from_common_failures():
    """#357: every check's section ends with what to do when it fails: the common-failures rows that quote its own
    message ("`<check> fail: …`"), copied whole, and where the messages any check can give are."""
    text = gen.PAGE.read_text()
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    failures, _ = gen.failure_rows([s.split("\n", 1)[0] for s in sections])
    for section in sections:
        name, body = section.split("\n", 1)
        if name in ("Boot check", "Check ran"):
            continue
        assert "When it fails:" in body and gen.ANY_CHECK in body, name
        for row in failures.get(name, []):
            assert row in body, (name, row)
    assert {"jtag", "header", "wiring", "spram", "flash", "ddr", "pcie-link", "p2-serial"} <= set(failures)


def test_a_common_failures_row_naming_a_check_the_page_lacks_stops_the_generator(monkeypatch, tmp_path):
    rows = gen.FAILURES.read_text().replace("`jtag fail: the JTAG chain has", "`jtagg fail: the JTAG chain has")
    (tmp_path / "common-failures.md").write_text(rows)
    monkeypatch.setattr(gen, "FAILURES", tmp_path / "common-failures.md")
    with pytest.raises(gen.GapError, match="'jtagg', which has no section here"):
        gen.page()
