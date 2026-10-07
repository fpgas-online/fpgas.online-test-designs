# SPDX-License-Identifier: Apache-2.0
"""Every drawing has a dark twin for the dark theme of docs.fpgas.online, drawn from palette.py's colours.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import functools
import re

import gen
import pytest
import sheetlib
import steps
import wiring
from wiringlib import palette

OUT = wiring.HERE / "generated"
FURO_DARK_BACKGROUND = "#131416"  # furo.css, body[data-theme=dark] --color-background-primary
COLOUR_ATTRIBUTE = re.compile(r'\b(fill|stroke)="[^"]*"')
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)(\{[^}]*\})?")


@functools.cache
def built():
    return gen.build()


def light_drawings():
    return sorted(n for n in built() if n.endswith(".svg") and not n.endswith("-dark.svg"))


def test_every_drawing_has_a_dark_twin_and_nothing_else_is_dark():
    files = built()
    light = light_drawings()
    assert light, "no drawings built"
    assert {palette.dark_name(n) for n in light} == {n for n in files if n.endswith("-dark.svg")}


def test_every_committed_drawing_has_its_dark_svg_and_png_beside_it():
    for svg in OUT.glob("*.svg"):
        if svg.stem.endswith("-dark"):
            continue
        for twin in (palette.dark_name(svg.name), palette.dark_name(svg.with_suffix(".png").name)):
            assert (OUT / twin).exists(), twin


@pytest.mark.parametrize("name", light_drawings())
def test_the_twins_differ_in_their_colours_only(name):
    """And in the words for the dark sheet only (Sheet.dark_only()), which the light sheet leaves out."""
    light, dark = built()[name], built()[palette.dark_name(name)]
    assert light != dark
    assert COLOUR_ATTRIBUTE.sub("", light) == COLOUR_ATTRIBUTE.sub("", palette.DARK_ONLY.sub("", dark))


@pytest.mark.parametrize("name", ["acorn-cable-cut.svg", "acorn-cable-p1-flag.svg", "acorn-cable-p2-flag.svg"])
def test_a_caption_that_calls_the_wires_black_says_on_the_dark_sheet_that_black_is_drawn_light(name):
    light, dark = built()[name], built()[palette.dark_name(name)]
    assert "are black" in light and "are black" in dark
    assert steps.DRAWN_LIGHT not in light
    assert f'aria-label="{steps.DRAWN_LIGHT}"' in dark


def test_words_for_the_dark_sheet_only_leave_the_light_one():
    sh = sheetlib.Sheet(300, 100)
    sh.text(20, 40, "both", 13)
    with sh.dark_only():
        sh.text(20, 70, "dark only", 13)
    sh.check("test")
    svg = sh.svg()
    assert 'aria-label="dark only"' not in palette.resolve(svg, "light")
    assert 'aria-label="dark only"' in palette.resolve(svg, "dark")
    assert 'aria-label="both"' in palette.resolve(svg, "light")


def photos(svg):
    return re.findall(r'<g transform="[^"]*" fill="none" stroke-width="1.1" stroke-linecap="square">.*?</g>', svg)


@pytest.mark.parametrize("name", ["acorn-wiring-computeblade.svg", "acorn-card-underside.svg"])
def test_photos_keep_their_own_colours_on_the_dark_sheet(name):
    light, dark = built()[name], built()[palette.dark_name(name)]
    assert photos(light) and photos(light) == photos(dark)


def test_the_dark_sheets_paper_is_the_dark_themes_background():
    assert palette.ROLES["paper"][1] == FURO_DARK_BACKGROUND
    for name in light_drawings():
        dark = built()[palette.dark_name(name)]
        assert f'fill="{FURO_DARK_BACKGROUND}"/>' in dark[: dark.index("</defs>") + 200], name


def test_every_wire_colour_of_wiring_toml_has_a_dark_counterpart():
    for name, signal in wiring.SIGNALS.items():
        if "colour" in signal:
            assert signal["colour"].lower() in palette.WIRES, name


def test_every_role_has_a_light_and_a_dark_colour():
    for name, (light, dark, what) in palette.ROLES.items():
        palette.rgb(light), palette.rgb(dark)
        assert what, name


def test_a_colour_outside_the_palette_stops_the_build():
    with pytest.raises(SystemExit, match=r"outside palette\.py"):
        palette.resolve('<rect fill="#123456"/>', "dark")
    with pytest.raises(SystemExit, match=r"outside palette\.py"):
        palette.resolve('<path stroke="white"/>', "light")
    for written in (
        '<path style="stroke:#123456"/>',  # in CSS
        '<path style="stroke:red"/>',  # any style attribute
        "<style>path { fill: #abc }</style>",
        '<stop offset="0" stop-color="#123456"/>',
        '<rect fill="url(#g)" data-colour="#fff"/>',  # a hex value in any attribute
    ):
        with pytest.raises(SystemExit, match=r"outside palette\.py"):
            palette.resolve(written, "dark")
    # a reference to an element by its id is not a colour
    glyph = '<use href="#b12"/><rect fill="@@ink@@"/>'
    assert palette.resolve(glyph, "dark") == f'<use href="#b12"/><rect fill="{palette.ROLES["ink"][1]}"/>'
    with pytest.raises(KeyError):
        palette.resolve('<rect fill="@@no-such-role@@"/>', "dark")
    with pytest.raises(KeyError):
        palette.wire("#123456")
    # a photo's own colours are left alone, and only there
    photo = f'{palette.PHOTO_START}<path stroke="#123456"/>{palette.PHOTO_END}'
    assert palette.resolve(photo, "dark") == '<path stroke="#123456"/>'


def test_no_drawn_colour_is_left_unresolved():
    for name, text in built().items():
        if name.endswith(".svg"):
            assert "@@" not in text and palette.PHOTO_START not in text, name


# ---- contrast on the dark sheet -------------------------------------------------------------------------------
DARK = {name: dark for name, (_light, dark, _what) in palette.ROLES.items()}


@pytest.mark.parametrize("role", ["ink", "muted", "red", "kicker"])
def test_text_colours_reach_7_to_1_on_the_dark_paper(role):
    assert palette.contrast(DARK[role], DARK["paper"]) >= sheetlib.TEXT_ON_PAPER


@pytest.mark.parametrize("light", sorted(palette.WIRES))
def test_every_dark_wire_colour_reads_as_text_and_carries_dark_words(light):
    dark = palette.WIRES[light]
    assert palette.contrast(dark, DARK["paper"]) >= sheetlib.TEXT_ON_PAPER  # a wire, or words in its colour
    assert palette.contrast(dark, DARK["box"]) >= sheetlib.TEXT_SMALL  # a resistor's value in a box
    assert palette.contrast(DARK["on-wire"], dark) >= sheetlib.TEXT_SMALL  # a tag filled with it


def test_the_sheet_refuses_text_without_contrast_on_the_dark_sheet():
    sh = sheetlib.Sheet(200, 100)
    sh.text(20, 40, "ok", 13)
    assert sh.contrast_errors() == []
    sh.text(20, 70, "lost", 13, fill=sheetlib.ON_WIRE)  # dark words straight on the dark paper
    assert [e for e in sh.contrast_errors() if "'lost'" in e]
    with pytest.raises(SystemExit, match="contrast"):
        sh.check("test")


def test_text_on_a_filled_box_is_checked_against_the_box():
    sh = sheetlib.Sheet(200, 100)
    sh.tag(20, 40, "K2", sheetlib.SIGNALS["K2"][0])
    sh.rect(20, 60, 100, 30, fill=palette.role("meter"))
    sh.text(30, 80, "beep", 13, fill=palette.role("on-meter"))
    assert [bg for *_, bg in sh.colours] == [sheetlib.SIGNALS["K2"][0], palette.role("meter")]
    assert sh.contrast_errors() == []


# ---- the Markdown shows the light picture in the light theme and the dark one in the dark --------------------
def test_every_picture_in_the_markdown_is_a_light_and_dark_pair():
    for name, text in built().items():
        if not name.endswith(".md"):
            continue
        found = IMAGE.findall(text)
        for i in range(0, len(found), 2):
            (alt, src, attrs), (dark_alt, dark_src, dark_attrs) = found[i], found[i + 1]
            assert (attrs, dark_attrs) == ("{.only-light}", "{.only-dark}"), (name, src)
            assert dark_alt == alt and dark_src == palette.dark_name(src), (name, src)
            assert f"![{alt}]({src}){attrs}\n![{dark_alt}]({dark_src}){dark_attrs}" in text, (name, src)
            assert src.replace(".png", ".svg") in built(), (name, src)
