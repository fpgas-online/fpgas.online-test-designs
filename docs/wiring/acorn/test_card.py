# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

import measure_card
import pytest
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from diagrams import model

HERE = pathlib.Path(__file__).parent
PHOTO = HERE / "photos" / "acorn-cw.jpg"
GOT = measure_card.measure_mm(PHOTO)


def test_the_contacts_of_both_sockets_are_1_2_mm_apart_at_the_scale_the_cards_width_gives():
    for name in ("P1", "P2"):
        assert GOT["contact_pitch_mm"][name] == pytest.approx(1.20, rel=0.05)


def test_both_long_edges_are_straight_on_at_least_20_rows_clear_of_the_sockets():
    px = measure_card.measure(PHOTO)
    assert min(px["edges"]["rows_agreeing"]) >= 20
    assert px["edges"]["rows"][0] > px["sockets"]["P1"][3]


def test_geometry_toml_has_what_the_photo_measures():
    acorn = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]
    assert acorn["photos"]["bottom"]["px_per_mm"] == GOT["px_per_mm"]
    assert acorn["photos"]["bottom"]["origin"] == GOT["origin"]
    assert acorn["photos"]["bottom"]["shown"] == [0, GOT["length_shown"]]
    for key in ("p1", "p2", "pad"):
        assert acorn["items"][key]["box"] == GOT[key]
    assert acorn["items"]["p1"]["pin1"] == GOT["p1_pin1"] and acorn["items"]["p2"]["pin1"] == GOT["p2_pin1"]


def test_the_check_passes_on_the_committed_geometry(capsys):
    measure_card.main(["--check"])
    assert "geometry.toml matches the photo" in capsys.readouterr().out


def test_pin_1_is_at_the_end_of_each_socket_nearest_the_m2_edge():
    acorn = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]["items"]
    for key in ("p1", "p2"):
        x0, y0, x1, y1 = acorn[key]["box"]
        assert acorn[key]["pin1"][1] > (y0 + y1) / 2  # the M.2 edge is at the larger y in this frame
        assert x0 < acorn[key]["pin1"][0] < x1


def test_the_sockets_are_at_the_edge_that_is_on_the_left_of_the_underside_photo():
    # The card's frame is its top face from above: the photo's left edge is x = 22 there.
    scene = model.load(HERE / "geometry.toml")
    for key in ("acorn.p1", "acorn.p2"):
        assert scene.item(key).face == "bottom" and scene.item(key).box.x1 > 21.0
    assert scene.item("acorn.p2").box.y1 < scene.item("acorn.p1").box.y0  # P2 is nearer the card's far end


def test_a_photo_without_six_contacts_in_each_socket_stops_the_script(tmp_path):
    from PIL import Image

    im = Image.open(PHOTO).convert("RGB")
    im.paste((20, 20, 20), (50, 110, 70, 140))  # P2's first contact painted over
    im.save(tmp_path / "five.png")
    with pytest.raises(SystemExit, match="contacts"):
        measure_card.measure(tmp_path / "five.png")
