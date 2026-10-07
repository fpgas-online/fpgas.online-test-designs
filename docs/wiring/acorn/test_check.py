# SPDX-License-Identifier: Apache-2.0
"""The "verifying" pages: each carrier's are for it only, complete in themselves, and say only what is true there."""

import re

import check
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
            and "acorn-sycamore" not in text
            and "{" not in re.sub(r"\{\.only-(light|dark)\}", "", text).split("```")[0]
        )
        assert "p2-gpio` | none: J5 and H5 are not wired on a Compute Blade" in text
        assert (
            "What has been run on a Compute Blade" in text and "No Compute Blade has passed the whole check yet" in text
        )
    else:
        assert "What has been run on a Compute Blade" not in text and "GPIO14 (TMS) is held by" not in text
        assert "acorn-sycamore" in text and "J5 and H5 are **crossed**: wires 4 and 5 of the P2 cable" in text
        assert "there is nothing to install" in text


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


def test_the_blade_pages_stop_the_check_on_the_cm4_blades_where_it_is_typed_and_run_again():
    pages = check.pages(wiring.CARRIERS["blade"])
    assert "Not on pi14 at ps1 or pi18 at ps1 yet." in pages[1]
    assert "not on pi14 or pi18 at ps1 yet" in pages[2]
    for text in check.pages(wiring.CARRIERS["pi5"]).values():
        assert "pi14" not in text


def test_the_transcripts_and_failure_rows_come_from_the_tool_reference():
    verify = check.VERIFY.read_text()
    command = {check.PASS: "fpgas-verify", check.BLADE_FAIL: "fpgas-acorn-verify"}  # as each was run
    for marker, tool in command.items():
        block = check.transcript(marker)
        assert block in verify and block.startswith(f"```text\n$ sudo {tool} --no-publish\n")
    for c in wiring.CARRIERS.values():
        rows = check.failures(c).splitlines()[2:]
        assert len(rows) >= 14 and all(r.startswith("| `") for r in rows)
    with pytest.raises(wiring.WiringError):
        check.transcript("**no such transcript**")
    # the tool's own reference still points at both pages, and keeps the anchor its summary prints
    assert (
        "boards/acorn/building/compute-blade/verifying-1.html" in verify
        and "boards/acorn/building/rpi-5/verifying-1.html" in verify
    )
    assert "\n### Common failures\n" in verify and "#### On a Compute Blade" not in verify


@pytest.mark.parametrize("key", CARRIERS)
def test_the_picture_names_every_wire_of_both_cables_with_where_it_lands(key):
    c = wiring.CARRIERS[key]
    for sig, (hk, pin) in c.wires.items():
        where = check.landing(c, sig)
        assert where[1] == f"{c.headers[hk].short} pin {pin}"
    assert set(check.USES) == {s for conn in wiring.CONNECTORS.values() for s in conn["pins"]} - {"GND1", "GND2", "VCC"}
    svg = check.picture(c)
    assert svg.startswith("<svg") and check.picture_name(c) in check.build()
    assert list(check.pages(c)) == ([1, 2, "2b", 3] if key == "blade" else [1, 2, "2b"])
    assert all(check.name(c, part) in check.build() for part in check.pages(c))


def test_a_fragment_keeps_only_its_carriers_lines():
    blade, pi5 = (check.fragment("to-the-wire.md", wiring.CARRIERS[k]) for k in ("blade", "pi5"))
    assert "One open wire" in pi5 and "One open wire" not in blade
    assert "A crossed pair" in blade and "A crossed pair" in pi5
    assert "<!--" not in blade + pi5


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
    assert "[converting a card](https://" in check.failures(
        blade
    ) and "acorn-pcie-programming.md]" not in check.failures(blade)
