# SPDX-License-Identifier: Apache-2.0
"""The cable picture shows the wiring's cables, reads on any page and on paper, and loads nothing.

Run: uv run --no-project --with pytest --with fonttools==4.65.0 pytest docs/wiring/tt-fpga
"""

import copy
import re

import gen
import picture
import pytest
import wiring
from wiringlib import palette

W = wiring.WIRING
BUILT = gen.build()
# the light SVGs, by name; each has its dark twin in BUILT
SVGS = {n: t for n, t in BUILT.items() if n.endswith(".svg") and not n.endswith("-dark.svg")}
FURO_DARK_BACKGROUND = "#131416"  # furo.css, body[data-theme=dark] --color-background-primary
COLOUR_ATTRIBUTE = re.compile(r'\b(fill|stroke)="[^"]*"')


def labels(svg):
    """The words drawn on a picture (each is kept in an aria-label; the glyphs themselves are outlines)."""
    return re.findall(r'aria-label="([^"]*)"', svg)


def test_there_is_a_picture_for_the_whole_wiring_and_one_for_each_page_that_picks_headers_out():
    assert set(SVGS) == {f"{name}.svg" for name in (*picture.PICTURES, picture.DISPLAY)}
    assert "tt-fpga-pmod-cables.svg" in SVGS


def test_each_cable_is_drawn_from_its_header_to_its_port_and_pin_1_is_marked():
    words = labels(SVGS["tt-fpga-pmod-cables.svg"])
    for key, port in W.cables.items():
        assert f"{W.headers[key]['name']} to {port}" in words
        assert port in words and W.headers[key]["name"] in words
    assert words.count("pin 1 to pin 1") == len(W.cables)
    assert "pin 1" in words  # the key says what the gold pin is
    assert "USB-C cable" in words and "a USB port of the Pi" in words


def test_the_picture_follows_the_wiring_when_a_cable_moves():
    d = copy.deepcopy(wiring.DATA)
    d["cables"]["input"], d["cables"]["bidir"] = "JB", "JA"
    words = labels(picture.draw(wiring.build(d), "tt-fpga-pmod-cables"))
    assert "INPUT to JB" in words and "BIDIR to JA" in words and "INPUT to JA" not in words


def test_the_shared_gpios_are_said_on_the_picture_from_the_hat_table():
    words = labels(SVGS["tt-fpga-pmod-cables.svg"])
    assert "JA pins 2, 3, 4 and JB pins 2, 3, 4 are the same Raspberry Pi GPIOs: 10, 9, 11." in words
    assert "one GPIO, two ports" in words


def test_it_brings_its_own_background_light_and_its_dark_twin_the_dark_themes():
    for name, svg in SVGS.items():
        root = re.match(r'<svg[^>]*width="(\d+)" height="(\d+)"', svg)
        assert f'<rect width="{root[1]}" height="{root[2]}" fill="#fbfaf7"/>' in svg, name
        dark = BUILT[palette.dark_name(name)]
        assert f'<rect width="{root[1]}" height="{root[2]}" fill="{FURO_DARK_BACKGROUND}"/>' in dark, name


def test_it_loads_nothing_so_it_renders_from_its_raw_url():
    for name, svg in BUILT.items():
        if not name.endswith(".svg"):
            continue
        assert set(re.findall(r'href="([^"]*)"', svg)) <= {h for h in re.findall(r'href="(#[^"]*)"', svg)}, name
        assert "data:" not in svg and "<image" not in svg and "<text" not in svg and "@font-face" not in svg, name


def test_it_is_legible_printed_on_a4():
    """Printed 180 mm wide (the text width of an A4 page) the smallest text is at least 2.5 mm high."""
    assert picture.SMALLEST * 180 / picture.W >= 2.5
    root = re.match(r"<svg[^>]*>", SVGS["tt-fpga-pmod-cables.svg"]).group(0)
    assert f'width="{picture.W}"' in root and f'height="{picture.H}"' in root
    assert picture.H / picture.W < 0.8  # wider than tall: at 180 mm wide it takes less than half a sheet


def test_a_picture_that_picks_headers_out_still_names_every_cable():
    words = labels(SVGS["tt-fpga-pmod-cables-uo.svg"])
    assert "Tiny Tapeout FPGA demo board to Pmod HAT: the OUTPUT header" in words
    assert {"INPUT to JA", "BIDIR to JB", "OUTPUT to JC"} <= set(words)
    assert words.count("pin 1 to pin 1") == 1  # only the cable the picture is about


def test_every_picture_says_in_words_that_the_gold_square_is_a_number_not_a_place():
    """Where pin 1 is on a board has not been read off one, so the square must not be taken for a place."""
    for name, svg in SVGS.items():
        if name == "tt-fpga-display.svg":  # not a picture of cables: no pin 1 on it
            continue
        words = labels(svg)
        for line in picture.PIN_1_SHORT:
            assert line.format(power="3.3 V") in words, (name, line)


def test_the_warning_about_a_cable_turned_round_is_worked_out_from_the_numbering():
    assert picture.turned_round(W) == [1, 7]  # where pins 12 and 6, the 3.3 V pins, land
    d = copy.deepcopy(wiring.DATA)
    d["pmod"].update(signal_pins=[2, 3, 4, 5, 8, 9, 10, 11], ground_pins=[6, 12], power_pins=[1, 7])
    with pytest.raises(SystemExit, match="it no longer does"):
        picture.pin_1_warning(wiring.build(d))


def test_the_display_picture_letters_each_segment_with_the_bit_that_lights_it_and_does_not_place_a():
    words = labels(SVGS["tt-fpga-display.svg"])
    for seg, wire in zip(W.display["segments"], W.of_group(W.display["group"]), strict=True):
        assert seg in words or (seg == "dot" and "decimal point" in words and "dot" in words)
        assert wire.signal in words
    assert "Where a is, and which way round the ring runs, is not recorded." in words


# ---- the dark twin of every picture, for the dark theme of docs.fpgas.online --------------------------------------
def test_every_picture_has_a_dark_twin_and_nothing_else_is_dark():
    assert {palette.dark_name(n) for n in SVGS} == {n for n in BUILT if n.endswith("-dark.svg")}


@pytest.mark.parametrize("name", sorted(SVGS))
def test_the_twins_differ_in_their_colours_only(name):
    light, dark = SVGS[name], BUILT[palette.dark_name(name)]
    assert light != dark
    assert COLOUR_ATTRIBUTE.sub("", light) == COLOUR_ATTRIBUTE.sub("", dark)


def test_no_colour_is_left_a_token_and_every_colour_is_the_palettes():
    for name, svg in BUILT.items():
        if name.endswith(".svg"):
            assert "@@" not in svg, name
    for svg in picture.build().values():  # the drawing itself: every colour a token
        palette.resolve(svg, "dark")  # stops on any colour outside the palette


def test_every_group_colour_of_wiring_toml_has_a_dark_counterpart():
    for name, group in W.groups.items():
        assert group["colour"].lower() in palette.WIRES, name


def test_every_committed_picture_has_its_dark_svg_and_png_beside_it():
    out = wiring.HERE / "generated"
    for svg in out.glob("*.svg"):
        if not svg.stem.endswith("-dark"):
            for twin in (palette.dark_name(svg.name), palette.dark_name(svg.with_suffix(".png").name)):
                assert (out / twin).exists(), twin


def test_pin_1_stays_gold_and_the_warning_box_gold_edged_on_the_dark_picture():
    gold = palette.ROLES["gold"]
    assert gold[0] == gold[1]  # the same gold in both themes
    dark = BUILT[palette.dark_name("tt-fpga-pmod-cables.svg")]
    caution = palette.ROLES["caution-fill"][1]
    assert f'fill="{caution}" stroke="{gold[1]}"' in dark
    # the number on pin 1 and the words on the gold tag are dark on the gold in both themes
    assert palette.contrast(palette.ROLES["on-gold"][1], gold[1]) >= 4.5


def test_text_on_a_translucent_fill_is_checked_against_that_fill_over_the_paper():
    from wiringlib.canvas import Sheet

    sh = Sheet(200, 100)
    teal = palette.wire("#0f766e")
    sh.rect(10, 10, 180, 80, fill=teal, opacity=16)
    sh.text(20, 50, "on the band", 15)
    (*_, bg) = sh.colours[0]
    assert bg == palette.wash(teal, 16) and 'fill-opacity="0.16"' in sh.svg()
    assert palette.value(bg, "light") == "#d5e5e1"  # 16 % of #0f766e over the light paper
    assert palette.value(bg, "dark") == "#1d3232"  # 16 % of its dark counterpart over the dark paper
    assert sh.contrast_errors() == []
