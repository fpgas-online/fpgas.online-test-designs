# SPDX-License-Identifier: Apache-2.0
"""The two "Checking an Acorn" pages: each is for one carrier, complete in itself, and says only what is true there."""

import re

import check
import pytest
import steps
import wiring

CARRIERS = list(wiring.CARRIERS)


@pytest.mark.parametrize("key", CARRIERS)
def test_the_page_is_for_one_carrier_only(key):
    c = wiring.CARRIERS[key]
    text = check.page(c)
    assert "<!--" not in text.split("\n", 1)[1]  # no carrier mark is left in the page
    if key == "blade":
        # nothing about the two spare wires, which a blade's cable does not carry
        assert "J5 -> GPIO3" not in text and "acorn-sycamore" not in text and "{" not in text.split("```")[0]
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
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
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


def test_the_transcripts_and_failure_rows_come_from_the_tool_reference():
    verify = check.VERIFY.read_text()
    for marker in (check.PASS, check.BLADE_FAIL):
        block = check.transcript(marker)
        assert block in verify and block.startswith("```text\n$ sudo fpgas-verify --no-publish")
    for c in wiring.CARRIERS.values():
        rows = check.failures(c).splitlines()[2:]
        assert len(rows) >= 14 and all(r.startswith("| `") for r in rows)
    with pytest.raises(wiring.WiringError):
        check.transcript("**no such transcript**")
    # the tool's own reference still points at both pages, and keeps the anchor its summary prints
    assert "boards/acorn/building/compute-blade/verifying.html" in verify and "boards/acorn/building/rpi-5/verifying.html" in verify
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


def test_a_fragment_keeps_only_its_carriers_lines():
    blade, pi5 = (check.fragment("to-the-wire.md", wiring.CARRIERS[k]) for k in ("blade", "pi5"))
    assert "One open wire" in pi5 and "One open wire" not in blade
    assert "A crossed pair" in blade and "A crossed pair" in pi5
    assert "<!--" not in blade + pi5
