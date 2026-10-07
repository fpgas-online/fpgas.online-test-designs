# SPDX-License-Identifier: Apache-2.0
"""The cable picture shows the wiring's cables, reads on any page and on paper, and loads nothing.

Run: uv run --no-project --with pytest --with fonttools==4.65.0 pytest docs/wiring/tt-fpga
"""

import copy
import re

import picture
import pytest
import wiring

W = wiring.WIRING
SVGS = picture.build()


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


def test_it_brings_its_own_background_so_it_reads_on_a_light_and_a_dark_page():
    for name, svg in SVGS.items():
        root = re.match(r'<svg[^>]*width="(\d+)" height="(\d+)"', svg)
        assert f'<rect width="{root[1]}" height="{root[2]}" fill="#fbfaf7"/>' in svg, name


def test_it_loads_nothing_so_it_renders_from_its_raw_url():
    for name, svg in SVGS.items():
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
        assert "The gold square is pin NUMBER 1 of the Pmod numbering. It is not a place on the board." in words, name
        assert (
            "Find pin 1 on each connector by its marking before plugging a cable in. "
            "A 2x6 cable turned round puts 3.3 V on signal pins."
        ) in words, name


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
