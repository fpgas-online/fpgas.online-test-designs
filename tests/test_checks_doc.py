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


def test_the_dashboards_two_other_columns_have_sections_too():
    assert {"Boot check", "Check ran"} <= set(headings())


def test_a_planned_test_with_no_description_writes_nothing(monkeypatch):
    board = next(iter(gen.board_api.installed().values()))
    monkeypatch.setattr(type(board), "about", lambda self, variant, found=None: {})
    with pytest.raises(gen.GapError, match="is planned and has no description"):
        gen.page()
