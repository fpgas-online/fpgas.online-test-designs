# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import frame, model, views
from diagrams.errors import DiagramError
from diagrams.model import Box

WHOLE = Box(0, 0, 10, 20)


def make(turn=0, face="top", box=WHOLE, scale=2.0):
    return frame.Frame(box, (10.0, 20.0), face, turn, scale, (0.0, 0.0))


def test_no_turn_maps_millimetres_to_pixels():
    assert make().to_px(1, 2) == (2.0, 4.0) and make().px_size == (20.0, 40.0)


def test_a_quarter_turn_clockwise_puts_the_top_left_corner_at_the_top_right():
    f = make(turn=90)
    assert f.px_size == (40.0, 20.0)
    assert f.to_px(0, 0) == pytest.approx((40.0, 0.0))
    assert f.to_px(10, 20) == pytest.approx((0.0, 20.0))


def test_half_a_turn_and_three_quarters():
    assert make(turn=180).to_px(0, 0) == pytest.approx((20.0, 40.0))
    assert make(turn=270).to_px(0, 0) == pytest.approx((0.0, 20.0))


def test_the_bottom_face_is_mirrored_left_to_right():
    assert make(face="bottom").to_px(1, 2) == pytest.approx((18.0, 4.0))


def test_a_box_stays_a_box_whatever_the_turn():
    for turn in (0, 90, 180, 270):
        x0, y0, x1, y1 = make(turn=turn).box_px(Box(1, 2, 3, 5))
        assert x0 < x1 and y0 < y1 and (x1 - x0) * (y1 - y0) == pytest.approx(2 * 3 * 4)


def test_a_cropped_frame_draws_only_its_box():
    f = make(box=Box(2, 4, 6, 10))
    assert f.px_size == (8.0, 12.0) and f.to_px(2, 4) == (0.0, 0.0)


def test_visible_fraction():
    item = Box(0, 0, 10, 10)
    assert frame.visible_fraction(item, Box(0, 0, 20, 20), []) == pytest.approx(1.0)
    assert frame.visible_fraction(item, Box(5, 0, 20, 20), []) == pytest.approx(0.5, abs=0.02)
    assert frame.visible_fraction(item, Box(0, 0, 20, 20), [Box(0, 0, 10, 4)]) == pytest.approx(0.6, abs=0.02)
    assert frame.visible_fraction(item, Box(50, 50, 60, 60), []) == 0.0


@pytest.mark.parametrize("turn, want", [(0, (6.0, 2.0)), (90, (10.0, 6.0)), (180, (2.0, 10.0)), (270, (2.0, 2.0))])
def test_the_bottom_face_of_a_crop_at_each_turn(turn, want):
    # A 10 x 20 mm thing; the crop is x 2..6, y 4..10 (4 x 6 mm). Seen from below the crop's x = 6 side is on
    # the left, so the point (3, 5) is 3 mm from the left and 1 mm down: (3, 1), then turned, at 2 px/mm.
    f = make(turn=turn, face="bottom", box=Box(2, 4, 6, 10))
    assert f.to_px(3, 5) == pytest.approx(want)
    assert f.px_size == ((12.0, 8.0) if turn in (90, 270) else (8.0, 12.0))


def test_a_box_on_the_bottom_face_of_a_turned_crop():
    f = make(turn=90, face="bottom", box=Box(2, 4, 6, 10))
    assert f.box_px(Box(3, 5, 5, 6)) == pytest.approx((8.0, 2.0, 10.0, 6.0))


GEOMETRY = """
[things.b]
name = "B"
size = [10.0, 20.0]
source = "a drawing"

[things.b.headers.h]
face = "top"
columns = 2
rows = 3
numbering = "across"
pitch = 2.0
pin = 0.5
pin1 = [2.0, 3.0]
source = "a drawing"

[things.b.items.x]
kind = "pad"
face = "top"
box = [4, 8, 6, 14]
source = "a drawing"
"""


def scene(tmp_path):
    (tmp_path / "geometry.toml").write_text(GEOMETRY)
    return model.load(tmp_path / "geometry.toml")


def view(turn, crop=(), width=240):
    return views.View("v", "b", "top", turn, crop, (), {}, None, width)


def test_a_views_frame_is_scaled_to_its_width_across_the_picture_whatever_the_turn(tmp_path):
    # The crop is the item (2 x 6 mm) and views.MARGIN (3 mm) round it: 8 x 12 mm, drawn 240 px wide.
    s = scene(tmp_path)
    upright = frame.view_frame(s, view(0, ("b.x",)))
    assert upright.box == Box(1, 5, 9, 17)
    assert upright.scale == pytest.approx(30.0) and upright.px_size == pytest.approx((240.0, 360.0))
    turned = frame.view_frame(s, view(90, ("b.x",)))
    assert turned.scale == pytest.approx(20.0) and turned.px_size == pytest.approx((240.0, 160.0))
    assert frame.view_frame(s, view(90, ("b.x",)), width_px=120).scale == pytest.approx(10.0)


def test_pin_1_of_a_header_on_a_turned_thing_lands_where_it_is_worked_out_by_hand(tmp_path):
    # The whole 10 x 20 mm thing, 400 px wide. Pin 1 is 2 mm in and 3 mm down.
    s = scene(tmp_path)
    x, y = s.item("b.h").pin1
    # A quarter turn clockwise: the picture is 20 mm across, 20 px/mm; pin 1 is 3 mm from the right, 2 mm down.
    assert frame.view_frame(s, view(90, width=400)).to_px(x, y) == pytest.approx((340.0, 40.0))
    # Three quarters: 3 mm from the left, 2 mm up from the bottom of a picture 10 mm high.
    assert frame.view_frame(s, view(270, width=400)).to_px(x, y) == pytest.approx((60.0, 160.0))
    # Upright: 10 mm across, 40 px/mm; and from an origin that is not the corner.
    assert frame.view_frame(s, view(0, width=400), origin=(5.0, 7.0)).to_px(x, y) == pytest.approx((85.0, 127.0))
    box = frame.view_frame(s, view(90, width=400)).box_px(s.item("b.h.pin.1").box)
    assert ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) == pytest.approx((340.0, 40.0))


def test_a_frame_of_no_known_face_or_turn_cannot_be_made():
    with pytest.raises(DiagramError, match="face 'side'"):
        make(face="side")
    for turn in (45, -90, 360, "90"):
        with pytest.raises(DiagramError, match="turn"):
            make(turn=turn)
