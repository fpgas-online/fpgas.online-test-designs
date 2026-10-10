# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

import gen
import measure_card
import pytest
import steps
import tomllib
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from diagrams import model

HERE = pathlib.Path(__file__).parent
PHOTO = HERE / "photos" / measure_card.PHOTO
PX = measure_card.measure(PHOTO)
GOT = measure_card.measure_mm(PHOTO)
ACORN = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]

HAND_PLACED = 10  # px, 0.43 mm: the old boxes were placed by hand; the measured box is the silkscreen outline


def test_the_two_scales_of_the_committed_photo_agree_within_5_percent():
    x, y = PX["scale_px_per_mm"]
    assert PX["scale_ratio_y_to_x"] == pytest.approx(y / x, abs=0.001)
    assert 0.95 <= y / x <= 1.0 / 0.95


def test_the_y_scale_is_the_contacts_pitch_and_the_x_scale_the_cards_width():
    pitch = (PX["contact_pitch_px"]["P1"] + PX["contact_pitch_px"]["P2"]) / 2
    assert PX["scale_px_per_mm"][1] == pytest.approx(pitch / measure_card.CONTACT_PITCH, abs=0.01)
    assert PX["scale_px_per_mm"][0] == pytest.approx(PX["edges"]["width_px"] / measure_card.CARD_WIDTH, abs=0.001)


def test_a_photo_squeezed_8_percent_along_y_is_refused_naming_both_scales(tmp_path):
    im = Image.open(PHOTO)
    im.resize((im.width, round(im.height * 0.92))).save(tmp_path / "squeezed.png")
    with pytest.raises(SystemExit, match=r"23\.\d+ px/mm across.* 20\.\d+ px/mm along"):
        measure_card.measure(tmp_path / "squeezed.png")


def test_sockets_whose_pitches_differ_by_more_than_2_percent_are_refused(tmp_path):
    im = Image.open(PHOTO).convert("RGB")
    top = PX["sockets"]["P1"][1] - 4  # everything from just above P1 down, stretched 4 % along y
    lower = im.crop((0, top, im.width, im.height))
    out = Image.new("RGB", (im.width, top + round(lower.height * 1.04)), (251, 250, 247))
    out.paste(im.crop((0, 0, im.width, top)), (0, 0))
    out.paste(lower.resize((lower.width, round(lower.height * 1.04))), (0, top))
    out.save(tmp_path / "stretched.png")
    with pytest.raises(SystemExit, match="do not give one scale down the photo"):
        measure_card.measure(tmp_path / "stretched.png")


def test_both_long_edges_are_straight_on_at_least_20_rows_clear_of_the_sockets():
    assert min(PX["edges"]["rows_agreeing"]) >= 20
    assert PX["edges"]["rows"][0] > PX["sockets"]["P1"][3]


def test_geometry_toml_has_what_the_photo_measures():
    assert ACORN["photos"]["bottom"]["px_per_mm"] == GOT["px_per_mm"]
    assert ACORN["photos"]["bottom"]["origin"] == GOT["origin"]
    assert ACORN["photos"]["bottom"]["shown"] == [0, GOT["length_shown"]]
    for key in ("p1", "p2", "pad"):
        assert ACORN["items"][key]["box"] == GOT[key]
    assert ACORN["items"]["p1"]["pin1"] == GOT["p1_pin1"] and ACORN["items"]["p2"]["pin1"] == GOT["p2_pin1"]


def test_the_check_passes_on_the_committed_geometry(capsys):
    measure_card.main(["--check"])
    assert "geometry.toml matches the photo" in capsys.readouterr().out


def test_the_card_is_stored_to_a_tenth_of_a_millimetre():
    figures = [v for key in ("p1", "p2", "pad", "p1_pin1", "p2_pin1") for v in GOT[key]] + [GOT["length_shown"]]
    assert all(round(v, 1) == v for v in figures)


def test_the_photo_shows_no_more_of_the_card_than_it_holds():
    y_scale = PX["scale_px_per_mm"][1]
    assert GOT["length_shown"] <= (PX["height"] - PX["top"]) / y_scale < GOT["length_shown"] + 0.1


def test_pin_1_is_the_measured_contact_with_the_largest_photo_y():
    (sx, sy), (left, top) = ACORN["photos"]["bottom"]["px_per_mm"], ACORN["photos"]["bottom"]["origin"]
    for key, name in (("p1", "P1"), ("p2", "P2")):
        x, y = max(PX["contacts"][name], key=lambda c: c[1])  # the M.2 edge is off the photo's bottom
        assert (x, y) == tuple(PX["contacts"][name][-1])
        # A contact's centre is the middle of its pixel; the photo shows the underside, so x is mirrored.
        want = (measure_card.CARD_WIDTH - (x + 0.5 - left) / sx, (y + 0.5 - top) / sy)
        assert ACORN["items"][key]["pin1"] == pytest.approx(want, abs=0.051)
        x0, y0, x1, y1 = ACORN["items"][key]["box"]
        assert x0 < want[0] < x1 and (y0 + y1) / 2 < want[1] < y1


def test_each_contact_has_its_own_x():
    for name in ("P1", "P2"):
        assert len({x for x, _y in PX["contacts"][name]}) > 1


def test_the_sockets_are_at_the_edge_that_is_on_the_left_of_the_underside_photo():
    # The card's frame is its top face from above: the photo's left edge is x = 22 there.
    scene = model.load(HERE / "geometry.toml")
    for key in ("acorn.p1", "acorn.p2"):
        assert scene.item(key).face == "bottom" and scene.item(key).box.x1 > 21.0
    assert scene.item("acorn.p2").box.y1 <= scene.item("acorn.p1").box.y0  # P2 is nearer the card's far end


def test_a_photo_without_six_contacts_in_each_socket_stops_the_script(tmp_path):
    im = Image.open(PHOTO).convert("RGB")
    im.paste((20, 20, 20), (50, 110, 70, 140))  # P2's first contact painted over
    im.save(tmp_path / "five.png")
    with pytest.raises(SystemExit, match="contacts"):
        measure_card.measure(tmp_path / "five.png")


def test_the_old_socket_boxes_are_within_a_hand_placed_10_px_of_the_silkscreen_outlines():
    for name in ("P1", "P2"):
        for old, measured in zip(gen.ACORN_CW[name], PX["sockets"][name], strict=True):
            assert abs(old - measured) <= HAND_PLACED


def test_the_old_pad_box_is_within_10_px_of_the_gold_at_its_left_right_and_bottom():
    (ox0, _oy0, ox1, oy1), (x0, _y0, x1, y1) = steps.ACORN_PAD, PX["pad"]
    assert abs(ox0 - x0) <= HAND_PLACED and abs(ox1 - x1) <= HAND_PLACED and abs(oy1 - y1) <= HAND_PLACED


def test_the_old_pad_box_starts_above_the_cards_end_and_the_measured_one_does_not():
    assert steps.ACORN_PAD[1] == 0 < PX["top"] <= PX["pad"][1]


def test_geometry_toml_names_the_card_width_and_the_photo_the_script_measures():
    assert ACORN["size"][0] == measure_card.CARD_WIDTH
    assert ACORN["photos"]["bottom"]["file"] == measure_card.PHOTO
