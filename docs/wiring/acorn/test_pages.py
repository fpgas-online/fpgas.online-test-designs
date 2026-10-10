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
# reads, in words or in a picture (where a quote is written &quot;). "Fitting" and "bench check" are also plain
# words for a task, so as page names they are looked for in quotes; "What has been run on a Compute Blade" is
# still a heading of its own page, so it is looked for where it is called a page.
QUOTE = r'(?:"|&quot;)'
OLD_NAMES = re.compile(
    r"(?i:\bverifying [0-9]b?\b)"
    r"|\b(?:JTAG|UART) connector [12]\b"
    rf"|{QUOTE}(?:Fitting|[Bb]ench check|the bench check){QUOTE}"
    rf"|(?i:the page {QUOTE}?what has been run on a Compute Blade)"
)
# Words that send the reader to a page without saying which: a link from pages.py says it.
VAGUE = re.compile(
    rf"(?i)the page before|the page after|\b(?:previous|next|first|second|third|last|other) page\b"
    rf"|the page {QUOTE}|\bpage {QUOTE}"
    r"|\bsee (?:above|below)\b"
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


def test_the_check_s_explanation_is_one_page_for_both_carriers_and_its_reference_is_one_for_each():
    """The split of the check pages by type (#207): the how-to keeps its page; what the check is, is one
    explanation for both carriers; which test uses which wire is a reference for each."""
    assert (
        pages.link("pi5", "check-about")
        == pages.link("blade", "check-about")
        == ("[The Acorn check](https://docs.fpgas.online/en/latest/boards/acorn/checks/about.html)")
    )
    assert pages.link("pi5", "check-tests") == (
        "[Acorn tests and their wires on a Raspberry Pi 5]"
        "(https://docs.fpgas.online/en/latest/boards/acorn/checks/rpi-5-tests.html)"
    )
    assert pages.title("blade", "check-tests") == "Acorn tests and their wires on a Compute Blade"
    assert pages.url("blade", "check-tests").endswith("/checks/compute-blade-tests.html")
    assert [key for key, page in pages.every() if page == "check-about"] == [next(iter(pages.CARRIERS))]


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


@pytest.mark.parametrize(
    "words",
    [
        'the page "verifying 1"', "as verifying 2b says", "Verifying 3", 'of "JTAG connector 2" do',
        "step 2 of &quot;UART connector 1&quot;.", 'as "Fitting" does', "as &quot;Fitting&quot; does",
        'run "the bench check"', "run &quot;the bench check&quot;", '"Bench check"',
        'The page "what has been run on a Compute Blade" says', "the page What has been run on a Compute Blade",
    ],
)  # fmt: skip
def test_the_pattern_finds_every_old_name_as_it_was_written(words):
    assert OLD_NAMES.search(words)


@pytest.mark.parametrize(
    "words",
    [
        "This is a bench check; the housings come off again", "## What has been run on a Compute Blade",
        "Fitting the cables on a Raspberry Pi 5, actions 1 to 3", "the JTAG connector on the card",
        "verifying the result",
    ],
)  # fmt: skip
def test_the_pattern_leaves_the_plain_words_alone(words):
    assert not OLD_NAMES.search(words)


def test_no_fragment_sends_the_reader_to_a_page_without_saying_which():
    """In the generated pages and the words they are made from: "the page before this one", 'the page "..."'."""
    files = _texts()  # the pictures and the two shared verify pages too
    left = [(f.name, m.group(0)) for f in files for m in VAGUE.finditer(f.read_text())]
    assert left == []


# The fragments that say "the bench check" as a task and need not link its page: the page of the bench check itself;
# the whole procedure on one page, which has the bench check in it; and the bare list of fitting actions, whose
# words are also drawn in the fitting pictures, where nothing can link (the fitting page links the bench check in
# its "What you need").
BENCH_IS_HERE = ("acorn-build-{key}-bench.md", "acorn-cables-{key}.md", "acorn-fit-{key}.md")


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_a_fragment_that_names_the_bench_check_links_its_page(key):
    here = {name.format(key=key) for name in BENCH_IS_HERE}
    named = 0
    for f in sorted(GENERATED.glob(f"acorn-*{key}*.md")):
        text = f.read_text()
        if "bench check" not in text.lower() or f.name in here:
            continue
        assert pages.url(key, "bench") in text, f.name
        named += 1
    assert named >= 2  # the fitting page and the page from a failing line to the wire


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
    mine = {pages.url(key, page) for k, page in pages.every() if k == key or page in pages.SHARED}
    for f in sorted(GENERATED.glob(f"acorn-*-{key}-*.md")) + sorted(GENERATED.glob(f"acorn-{key}-*.md")):
        for _, address in DOCS_LINK.findall(f.read_text()):
            assert address.split("#")[0] in mine, (f.name, address)


# What a reader page may not say during or after the docs rework: that something is unproven, untried or to come.
# The unknown is an item of the carrier's bench-run issue (steps.BENCH_RUN), and the page's one line names it.
UNPROVEN = re.compile(
    r"(?i)\bnot yet\b|\bby us\b|\bnot (?:been )?(?:measured|verified|recorded|tried|checked|seen|run)\b"
    r"|\btaken (?:as given|to be)\b|\bwe have not\b|\bunverified\b|\bTODO\b|\bas read on\b|\bFuture:"
    r"|\bis not written here\b|\bSources:"
)
# A person named in what ships: a role is named instead ("the site operator").
PERSON = re.compile(r"\b(?:Tim|Carl)\b")
# A record of where and when something was done: a host of a site, a site, a date. The fact stays; the record is
# the review's, or the bench-run issue's.
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
RECORD = re.compile(rf"\bpi\d{{2}}\b|\bps1\b|\bwelland\b|\b\d{{1,2}} (?:{MONTHS}) 20\d\d\b|\b20\d\d-\d\d-\d\d\b")


def _build_texts(key):
    """The building pages of carrier `key`, the parts list, the fitting list, the whole procedure, and every
    picture they show (the pictures' drawn words)."""
    names = [f"acorn-build-{key}-*.md", f"acorn-cables-{key}.md", f"acorn-fit-{key}.md", f"acorn-{key}-*.md"]
    files = [f for pattern in names for f in sorted(GENERATED.glob(pattern))]
    shown = {m for f in files for m in re.findall(r"\]\(([a-z0-9-]+)\.png\)", f.read_text())}
    return files + [GENERATED / f"{name}.svg" for name in sorted(shown)]


def _words(f):
    """A page's text, or the words drawn in a picture."""
    text = f.read_text()
    return "\n".join(re.findall(r'aria-label="([^"]*)"', text)) if f.suffix == ".svg" else text


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_a_building_page_or_its_picture_says_nothing_unproven_and_names_no_person(key):
    files = _build_texts(key)
    assert len(files) > 20 and any(f.suffix == ".svg" for f in files)
    left = [(f.name, m.group(0), _words(f)[max(0, m.start() - 50) : m.end() + 30]) for f in files
            for m in UNPROVEN.finditer(_words(f))]  # fmt: skip
    assert left == []
    assert [(f.name, m.group(0)) for f in files for m in PERSON.finditer(_words(f))] == []
    assert [(f.name, m.group(0)) for f in files for m in RECORD.finditer(_words(f))] == []


@pytest.mark.parametrize(
    "words",
    [
        "Not yet run by us on this hardware", "has not been measured by us", "not recorded by us",
        "(designed so, not yet measured)", "is taken as given", "taken to be ground", "we have not tried your meter",
        "not tried by us", "is not written here",
        "The shell being ground is not measured on this host", "Sources: the wiki", "Future: more",
    ],
)  # fmt: skip
def test_the_unproven_pattern_finds_the_sentences_the_pages_had(words):
    assert UNPROVEN.search(words)


@pytest.mark.parametrize(
    "words",
    ["This procedure is waiting for its bench run: [issue #218](x).", "it must not beep", "the card is not fitted",
     "Photos: Waveshare (PoE M.2 HAT+ (B))", "run the check"],
)  # fmt: skip
def test_the_unproven_pattern_leaves_plain_instructions_alone(words):
    assert not UNPROVEN.search(words)


@pytest.mark.parametrize("words", ["on pi20 at ps1", "at welland", "read on 7 October 2026", "2026-10-07", "ask Carl"])
def test_the_record_and_person_patterns_find_hosts_sites_dates_and_names(words):
    assert RECORD.search(words) or PERSON.search(words)


@pytest.mark.parametrize("words", ["a Raspberry Pi 5", "pins 19 to 26", "the P1 cable", "GPIO14", "2 mm heat-shrink"])
def test_the_record_pattern_leaves_the_hardware_s_names_alone(words):
    assert not RECORD.search(words) and not PERSON.search(words)
