# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import frame
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
