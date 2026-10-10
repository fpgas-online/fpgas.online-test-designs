# SPDX-License-Identifier: Apache-2.0
"""The page table (pages.py), and that every generated fragment names another page only through it.

Run: uv run --no-project --with pytest pytest docs/wiring/acorn/test_pages.py
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import pages
import wiring

GENERATED = wiring.HERE / "generated"
# The names the pages had before docs.fpgas.online's re-nest: none may be left in what the generator writes or
# reads, in words or in a picture.
OLD_NAMES = re.compile(
    r"verifying [0-9]b?\b|\b(?:JTAG|UART) connector [12]\b|\"Fitting\"|\"[Bb]ench check\"|\"the bench check\""
    r"|[Ww]hat has been run on a Compute Blade\""
)
# A link into the three parts of the Acorn tree the table covers (the other Acorn pages are not this table's).
DOCS_LINK = re.compile(
    r"\[([^\]]+)\]\((https://docs\.fpgas\.online/en/latest/boards/acorn/(?:setup|checks|troubleshooting)/[^)\s]+)\)"
)


def test_the_carriers_are_the_wiring_s_and_named_as_it_names_them():
    assert {key: name for key, (_, name) in pages.CARRIERS.items()} == {
        key: c.name for key, c in wiring.CARRIERS.items()
    }


def test_every_title_is_unique_and_within_the_docs_limit():
    titles = [pages.title(key, page) for key, page in pages.every()]
    assert len(set(titles)) == len(titles)
    assert [t for t in titles if len(t) > pages.MAX_TITLE] == []
    addresses = [pages.url(key, page) for key, page in pages.every()]
    assert len(set(addresses)) == len(addresses)
    assert all(a.startswith(pages.BASE) and a.endswith(".html") for a in addresses)


def test_a_how_to_page_s_title_starts_how_to_and_the_others_do_not():
    how_to = {"jtag-1", "jtag-2", "uart-1", "uart-2", "bench", "fit", "check-1", "check-3"}
    for key, page in pages.every():
        assert pages.title(key, page).startswith("How to ") == (page in how_to), (key, page)


def test_the_titles_and_addresses_are_the_ones_the_docs_pages_have():
    """Spot checks against the list agreed with the docs repository (its re-nest of the Acorn tree)."""
    assert pages.link("pi5", "jtag-2") == (
        "[How to fill the JTAG cable's housing (Raspberry Pi 5)]"
        "(https://docs.fpgas.online/en/latest/boards/acorn/setup/rpi-5/jtag-housing.html)"
    )
    assert pages.url("blade", "check-1") == "https://docs.fpgas.online/en/latest/boards/acorn/checks/compute-blade.html"
    assert pages.title("blade", "check-3") == "How to make a Compute Blade boot ready for JTAG"
    assert pages.url("blade", "check-3").endswith("/checks/compute-blade-jtag.html")
    assert pages.url("pi5", "check-2b").endswith("/troubleshooting/rpi-5-other-messages.html")
    assert pages.title("pi5", "overview") == "The two cables on a Raspberry Pi 5"
    assert pages.title("blade", "parts") == "Parts and tools for the Compute Blade cables"


def test_a_page_a_carrier_does_not_have_is_refused():
    with pytest.raises(pages.NoSuchPage):
        pages.link("pi5", "check-3")
    with pytest.raises(pages.NoSuchPage):
        pages.link("pi5", "verifying-1")
    with pytest.raises(pages.NoSuchPage):
        pages.link("arty", "fit")


def _texts():
    """Every file the generator writes as text or a drawing, and every file of words it reads."""
    docs = wiring.HERE.parents[1]
    files = [*sorted(GENERATED.glob("*.md")), *sorted(GENERATED.glob("*.svg"))]
    files += [*sorted((wiring.HERE / "check").glob("*.md")), wiring.HERE / "wiring.toml"]
    files += [docs / "verify" / "common-failures.md", docs / "verify" / "reading-the-result.md"]
    return files


def test_no_old_page_name_is_left_in_words_or_in_a_picture():
    left = [(f.name, m.group(0)) for f in _texts() for m in OLD_NAMES.finditer(f.read_text())]
    assert left == []


def test_every_link_into_the_acorn_docs_is_a_page_of_the_table_with_its_title():
    known = {pages.url(key, page): pages.title(key, page) for key, page in pages.every()}
    seen = 0
    for f in _texts():
        for shown, address in DOCS_LINK.findall(f.read_text()):
            assert known.get(address.split("#")[0]) == shown, (f.name, shown, address)
            seen += 1
    assert seen >= 30  # the build guide's order of work alone links eight pages for each carrier


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_a_carrier_s_fragments_link_only_that_carrier_s_pages(key):
    mine = {pages.url(key, page) for k, page in pages.every() if k == key}
    for f in sorted(GENERATED.glob(f"acorn-*-{key}-*.md")) + sorted(GENERATED.glob(f"acorn-{key}-*.md")):
        for _, address in DOCS_LINK.findall(f.read_text()):
            assert address.split("#")[0] in mine, (f.name, address)
