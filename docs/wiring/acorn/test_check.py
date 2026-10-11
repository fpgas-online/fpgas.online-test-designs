# SPDX-License-Identifier: Apache-2.0
"""The "verifying" pages: each carrier's are for it only, complete in themselves, and say only what is true there."""

import re

import check
import pages as docs_pages
import pytest
import steps
import wiring

CARRIERS = list(wiring.CARRIERS)


def light_images(text):
    """The pictures of Markdown text, each once: the light PNG of every light and dark pair (test_palette.py)."""
    return [i for i in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text) if not i.endswith("-dark.png")]


@pytest.mark.parametrize("key", CARRIERS)
def test_the_page_is_for_one_carrier_only(key):
    c = wiring.CARRIERS[key]
    text = check.page(c)
    assert text.count("<!--") == len(check.pages(c))  # only each page's banner: no carrier mark is left
    if key == "blade":
        # nothing about the two spare wires, which a blade's cable does not carry
        assert (
            "J5 -> GPIO3" not in text
            and "One open wire" not in text
            and "{" not in re.sub(r"\{\.only-(light|dark)\}", "", text).split("```")[0]
        )
        assert "p2-gpio` | none: J5 and H5 are not wired on a Compute Blade" in text
        assert "## What has been run on a Compute Blade" not in text  # the dated record is issue 241, not a page
    else:
        assert "Compute Blade" not in text and "GPIO14 (TMS) is held by" not in text
        assert "One open wire" in text and "J5 and H5 are **crossed**: wires 4 and 5 of the P2 cable" in text
        assert "A Raspberry Pi 5 that boots the fleet's root has them" in text


@pytest.mark.parametrize("key", CARRIERS)
def test_the_page_is_complete_in_itself(key):
    c = wiring.CARRIERS[key]
    text = check.page(c)
    built = set(steps.build_names()) | {check.picture_name(c)}
    images = light_images(text)
    assert images[0] == steps.png(check.picture_name(c))
    for image in images:
        assert "/" not in image and image.replace(".png", ".svg") in built, image  # a picture beside the page
    for connector in wiring.CONNECTORS:  # the cavity pictures are shown again where a failing line is taken to a wire
        assert steps.png(steps.file_name(c, connector)) in images
    # every link leaves the page by a whole address: the page is included under another repository's page
    links = re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text)
    assert links and all(link.startswith("https://") for link in links), links
    assert "sudo apt install fpgas-online-acorn" in text and "sudo fpgas-acorn-verify --no-publish" in text
    assert "see above" not in text.lower() and "—" not in text
    prose = re.sub(r"```.*?```", "", text, flags=re.S)  # a shell comment in a code block is no heading
    assert [h for h in re.findall(r"^(#+) ", prose, re.M) if len(h) < 2] == []  # headings from level 2


@pytest.mark.parametrize("key", CARRIERS)
def test_a_crossed_pair_is_told_by_the_wire_numbers_of_the_cable(key):
    c = wiring.CARRIERS[key]
    pins = wiring.CONNECTORS["P2"]["pins"]
    a, b = pins.index("J2") + 1, pins.index("K2") + 1
    words = check.swap(c, "J2", "K2")
    assert f"wires {a} and {b} of the P2 cable are in each other's cavity" in words
    assert (f"The {c.resistor_value} resistor stays in wire {a} (J2)" in words) == ("J2" in c.resistors)


def test_the_blade_pages_are_for_a_compute_module_5_and_hold_no_record_of_a_run():
    """The pages say which hardware they cover in "What you need"; where and when something was run, on which host
    and by whom, is the record's (issue 241), outside what the tool itself printed."""
    blade, pi5 = wiring.CARRIERS["blade"], wiring.CARRIERS["pi5"]
    for part in (1, 3):
        assert "- a Compute Blade with a Compute Module 5, the Acorn and both cables fitted" in check.pages(blade)[part]
    texts = [*check.pages(blade).values(), *check.pages(pi5).values(), check.about()]
    for text in texts:
        prose = re.sub(r"```.*?```", "", text, flags=re.S)  # a transcript is what the tool printed, host and all
        for record in (
            r"\bpi\d\d\b",
            r"\bps1\b",
            r"\bwelland\b",
            r"\b20\d\d\b",
            r"\bTim\b",
            r"\bCarl\b",
            r"(?<![\w/-])acorn-[a-z]+\b(?!\.)",
        ):
            assert not re.search(record, prose.replace("acorn-check", "").replace("acorn-cable", "")), record
        for unproven in (
            "not yet",
            "by us",
            "not measured",
            "not recorded",
            "not settled",
            "not in this guide",
            "today",
            "our test",
        ):
            assert unproven not in prose, unproven


def test_the_transcripts_and_failure_rows_come_from_the_tool_reference():
    verify = check.RESULTS.read_text()
    command = {check.PASS: "fpgas-verify", check.BLADE_FAIL: "fpgas-verify"}  # as each was run
    for marker, tool in command.items():
        block = check.transcript(marker)
        assert block in verify and block.startswith(f"```text\n$ sudo {tool} --no-publish\n")
    for c in wiring.CARRIERS.values():
        rows = check.failures(c).splitlines()[2:]
        assert len(rows) >= 14 and all(r.startswith("| `") for r in rows)
    with pytest.raises(wiring.WiringError):
        check.transcript("**no such transcript**")
    # the tool's own reference still points at both pages, and keeps the anchor its summary prints
    wiring_page = (check.VERIFY / "acorn-wiring.md").read_text()
    assert "boards/acorn/checks/compute-blade.html" in wiring_page and "boards/acorn/checks/rpi-5.html" in wiring_page
    assert "\n## Common failures\n" in check.COMMON_FAILURES.read_text()
    assert not any("# On a Compute Blade" in page.read_text() for page in check.VERIFY.glob("*.md"))


@pytest.mark.parametrize("key", CARRIERS)
def test_the_picture_names_every_wire_of_both_cables_with_where_it_lands(key):
    c = wiring.CARRIERS[key]
    for sig, (hk, pin) in c.wires.items():
        where = check.landing(c, sig)
        assert where[1] == f"{c.headers[hk].short} pin {pin}"
    assert set(check.USES) == {s for conn in wiring.CONNECTORS.values() for s in conn["pins"]} - {"GND1", "GND2", "VCC"}
    svg = check.picture(c)
    assert svg.startswith("<svg") and check.picture_name(c) in check.build()
    assert list(check.pages(c)) == ([1, "tests", 2, "2b", 3] if key == "blade" else [1, "tests", 2, "2b"])
    assert all(check.name(c, part) in check.build() for part in check.pages(c))
    assert check.ABOUT_NAME in check.build() and check.build()[check.ABOUT_NAME] == check.about()


def test_a_fragment_keeps_only_its_carriers_lines():
    blade, pi5 = (check.fragment("to-the-wire.md", wiring.CARRIERS[k]) for k in ("blade", "pi5"))
    assert "One open wire" in pi5 and "One open wire" not in blade
    # the crossed pair was read on a Pi 5: the blade's page keeps the table and how to read the eight lines
    assert "A crossed pair" in pi5 and "A crossed pair" not in blade and "acorn-olive" not in blade
    assert "A correctly wired pair reads back what was driven" in blade
    assert "<!--" not in blade + pi5


HOW_TO = ["## What you need", "## Steps", "## Check", "## If it fails", "## Next"]


def headings(text):
    """The headings of a page, outside its code blocks (a shell comment is no heading)."""
    return re.findall(r"^#+ .*$", re.sub(r"```.*?```", "", text, flags=re.S), re.M)


@pytest.mark.parametrize("key", CARRIERS)
def test_each_check_page_is_one_type_of_page(key):
    """The split by type (#207): the how-to pages have a how-to's five headings and no others; what the check is,
    is the explanation; which test uses which wire is the reference."""
    c = wiring.CARRIERS[key]
    pages = check.pages(c)
    assert headings(pages[1]) == HOW_TO
    assert headings(pages["tests"]) == ["## Which test uses which wire"]  # the heading the docs pages link
    assert "## What the check is" not in pages[1] and "## Which test uses which wire" not in pages[1]
    steps_of = lambda page: [int(n) for n in re.findall(r"^\*\*(\d+)\.\*\* ", page, re.M)]  # noqa: E731
    assert steps_of(pages[1]) == list(range(1, len(steps_of(pages[1])) + 1)) and len(steps_of(pages[1])) >= 2
    need = pages[1][pages[1].index("## What you need") : pages[1].index("## Steps")].splitlines()[1:]
    assert all(line.startswith("- ") for line in need if line) and 2 <= len([line for line in need if line]) <= 7
    next_links = pages[1][pages[1].index("## Next") :].count("](https://")
    assert 2 <= next_links <= 5
    if key == "blade":
        assert headings(pages[3]) == HOW_TO
        assert steps_of(pages[3]) == list(range(1, 10))


def test_what_the_check_is_is_one_explanation_for_both_carriers():
    about = check.about()
    assert about.count("<!--") == 1 and not re.search(r"^\*\*\d+\.\*\* ", about, re.M)  # no numbered step
    assert len(headings(about)) <= 7 and "## On a Compute Blade" in headings(about)
    for key in CARRIERS:
        assert docs_pages.link(key, "check-tests") in about
        assert check.ABOUT in check.pages(wiring.CARRIERS[key])[1]
    blade_part = about[about.index("## On a Compute Blade") :]
    assert "Do not load a design into a card on a Compute Blade, and do not convert it." in blade_part
    assert check.BLADE_RECORD in blade_part and check.BLADE_JTAG in blade_part
    assert "the check's result on a Compute Blade is `fail`" in blade_part
    # before that section the blade is named once only: in the title of its page of tests and wires
    assert about[: about.index("## On a Compute Blade")].count("Compute Blade") == 1


def test_the_record_of_what_was_run_on_a_blade_is_an_issue_not_a_page():
    assert check.BLADE_RECORD == "https://github.com/fpgas-online/fpgas.online-test-designs/issues/241"
    for text in blade_texts():
        assert "What has been run on a Compute Blade" not in text and "Test 6" not in text and "our test" not in text
        assert "been tried" not in text  # no link promises a record the linked page no longer holds


def test_a_fragment_with_marks_that_do_not_pair_or_are_not_understood_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "FRAGMENTS", tmp_path)
    blade = wiring.CARRIERS["blade"]
    good = "both\n<!-- pi5:begin -->\npi5 only\n<!-- pi5:end -->\n<!-- blade -->blade only\n"
    (tmp_path / "f.md").write_text(good)
    assert check.fragment("f.md", blade) == "both\nblade only\n"
    for bad in (
        "<!-- pi5:begin -->\na\n<!-- blade:begin -->\nb\n<!-- blade:end -->\n<!-- pi5:end -->\n",  # nested
        "<!-- pi5:begin -->\na\n<!-- blade:end -->\n",  # closed by another's end
        "a\n<!-- pi5:end -->\n",  # an end with no begin
        "<!-- pi5:begin -->\na\n",  # never closed
        "<!-- pi-5 -->a\n",  # a mark that is not understood
        "  <!--blade-->a\n",
        "<!-- cm4 -->a\n",  # no such carrier
    ):
        (tmp_path / "f.md").write_text(bad)
        with pytest.raises(wiring.WiringError):
            check.fragment("f.md", blade)


def test_a_caption_cannot_outlive_its_transcript_and_a_swap_stays_on_one_cable():
    with pytest.raises(wiring.WiringError):
        check.transcript(check.PASS, "a host that paragraph does not name")
    with pytest.raises(wiring.WiringError):
        check.swap(wiring.CARRIERS["pi5"], "TCK", "J2")
    blade = wiring.CARRIERS["blade"]
    assert "power-cycle fail" not in check.failures(blade) and "power-cycle fail" in check.failures(
        wiring.CARRIERS["pi5"]
    )
    pi5 = wiring.CARRIERS["pi5"]  # the link to converting is the Pi 5's only: a blade is told not to convert
    assert "[converting a card](https://" in check.failures(pi5) and "acorn-pcie-programming.md]" not in check.failures(
        pi5
    )
    assert "[converting a card]" not in check.failures(blade)


def test_a_blade_page_prints_the_blades_own_advice_and_never_advice_to_convert():
    """The blade's transcript is the one the code prints today (test_verify_conclusion holds it): its advice is the
    blade's, which says not to convert, and nothing in it tells the reader to convert."""
    fenced = [
        b
        for page in check.pages(wiring.CARRIERS["blade"]).values()
        for b in re.findall(r"```text\n(.*?)```", page, re.S)
    ]
    assert fenced  # the blade pages do print transcripts: the check below is not empty
    for block in fenced:
        flat = " ".join(block.split())
        assert "It has to be converted" not in flat and "converted once" not in flat
        assert "acorn-pcie-programming" not in flat and "If it is an Acorn, convert it" not in flat
    assert any("do not load a design into the card or convert it" in " ".join(b.split()) for b in fenced)


def test_a_row_split_by_host_keeps_only_this_carriers_clause():
    row = "| `x` | a card. On a Raspberry Pi 5: convert it. On a Compute Blade: **do not**; not yet |"
    blade, pi5 = wiring.CARRIERS["blade"], wiring.CARRIERS["pi5"]
    assert check.for_carrier(row, blade) == "| `x` | a card. **Do not**; not yet |"
    assert check.for_carrier(row, pi5) == "| `x` | a card. Convert it. |"
    assert check.for_carrier("| `y` | the same on every host |", blade) == "| `y` | the same on every host |"
    with pytest.raises(wiring.WiringError):
        check.for_carrier("| `z` | a card. On a Raspberry Pi 5: convert it. |", blade)
    # and the blade's printed rows never tell its reader to convert a card
    assert "convert it" not in check.failures(blade).replace("or convert it", "")


def test_moving_a_wire_sends_the_cable_through_the_new_cables_checks_before_a_boot():
    """Moving a wire is numbered steps, in this order: power off, card out, move, meter, bench check, fit, boot."""
    for c in wiring.CARRIERS.values():
        body = "\n".join(check.pages(c).values())
        start = body.index("To move a wire, the cable goes through the same checks as a new one before any boot:")
        block = body[start : body.index("\n\n", body.index("\n1. ", start))]
        steps_ = re.findall(r"^(\d)\. (.*)$", block, re.M)
        assert [int(n) for n, _ in steps_] == list(range(1, 8))
        text = [s for _, s in steps_]
        assert text[0] == c.power_off and text[1].startswith("Take the card out and pull both plugs")
        assert text[2] == "Move the wire." and "with the meter" in text[3]
        assert docs_pages.link(c.key, "jtag-2") in text[3] and docs_pages.link(c.key, "bench") in text[4]
        assert "with the card out" in text[4]
        assert docs_pages.link(c.key, "fit") in text[5]
        assert text[6].startswith("Ask the site operator, then boot the blade" if c.key == "blade" else "Boot the Pi")
        assert "run the check again" in text[6]
        assert ("install the packages again" in text[6]) == (c.key == "blade")  # a blade's install is gone after a boot


def test_a_blade_page_says_when_jtag_may_run_before_the_command_that_runs_it():
    """The how-to's last step runs the whole check, which runs `jtag`: the step before it sends the reader to the
    two checks of GPIO14, by their numbers on the page about JTAG."""
    page = check.pages(wiring.CARRIERS["blade"])[1]
    free, driven = check.jtag_steps()
    asked = f"steps {free} and {driven} of {check.BLADE_JTAG}. Step {free} checks that GPIO14 is free"
    assert page.index(asked) < page.index("```bash\nsudo fpgas-acorn-verify --no-publish")
    assert "If either fails, do not run the check in that boot" in page


def blade_texts():
    """Every blade page of the check as generated, and the fragment of the blade's compute-blade.md."""
    blade = wiring.CARRIERS["blade"]
    return [*check.pages(blade).values(), check.fragment("compute-blade.md", blade)]


def test_every_reboot_a_blade_page_asks_for_is_preceded_by_asking_the_site_operator():
    """A reboot ends a visitor's session on a blade, the same harm as a power-off: asking the site operator comes
    first."""
    reboot = re.compile(
        r"\b(?:re)?boot the blade\b|\bthen boot\b|\bboot, and run\b|\band boot\b|\breboot a blade\b", re.I
    )
    seen = 0
    for text in blade_texts():
        for m in reboot.finditer(text):
            before = text[max(0, m.start() - 80) : m.start()].lower()
            seen += 1
            asked = re.search(r"ask(?:ing)? the site operator", before + m.group(0).lower())
            assert asked, text[m.start() - 80 : m.end() + 20]
    assert seen >= 4  # the how-to's install step, the rework line, the JTAG page's undo and its step that boots
    assert check.ASK_FIRST in blade_texts()[0]  # the how-to, where the installs are
    assert "a reboot ends a visitor's session" in blade_texts()[-1].lower()  # the JTAG page says why, once
    assert blade_texts()[-1].count("Ask the site operator, then boot the blade again") == 1


def test_the_two_checks_of_gpio14_have_no_exception():
    page = check.pages(wiring.CARRIERS["blade"])[3]
    free, driven = check.jtag_steps()
    assert (free, driven) == (7, 8)
    block = page[page.index(f"**{free}.** {check.GPIO_FREE}") : page.index(f"**{driven + 1}.** ")]
    flat = " ".join(block.split())
    assert f"**{driven}.** {check.GPIO_DRIVEN}" in block
    assert "unless" not in flat and "if you know" not in flat.lower() and "skip" not in flat.lower()
    assert "Always run this step, on each blade you run JTAG on" in flat and "470 Ω resistor" in flat
    assert f"only if steps {free} and {driven} passed" in page[page.index(f"**{driven + 1}.** ") :].split("\n")[0]
    fails = page[page.index("## If it fails") : page.index("## Next")]
    assert f"- Step {free} shows a consumer" in fails and f"- Step {driven} does not print 0 and then 1" in fails


def test_the_two_checks_of_gpio14_are_quoted_by_their_step_numbers_and_their_page():
    """A page that gives a command that runs `jtag` on a blade says which two steps come first, by number and by a
    link to their page: the numbers are counted from that page, here and in the tool's reference."""
    free, driven = check.jtag_steps()
    quote = f"steps {free} and {driven} of {check.BLADE_JTAG}"
    texts = [*blade_texts(), check.COMMON_FAILURES.read_text()]
    texts += [p.read_text() for p in sorted((wiring.HERE / "generated").glob("acorn-check-blade-*.md"))]
    for text in texts:
        flat = " ".join(text.split())
        assert "last list" not in flat and "Before JTAG runs on a blade" not in flat
        for m in re.finditer(r"steps (\d+) and (\d+) of \[How to make a Compute Blade boot ready for JTAG\]", flat):
            assert (int(m[1]), int(m[2])) == (free, driven), flat[m.start() - 60 : m.end()]
    assert sum(" ".join(t.split()).count(quote) for t in texts) >= 5
    assert quote in check.JTAG_CONDITIONS
