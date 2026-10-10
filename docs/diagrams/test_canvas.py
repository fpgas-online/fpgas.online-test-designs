# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import palette
from diagrams.canvas import Sheet


def test_a_sheet_measures_the_text_it_draws():
    sh = Sheet(200, 100)
    assert sh.text(20, 40, "pin 1", 12, "bold") == sh.width("pin 1", 12, "bold") > 0


def test_text_leaving_the_canvas_stops_the_build():
    sh = Sheet(60, 40)
    sh.text(20, 30, "far too long for it", 12)
    with pytest.raises(SystemExit, match="leaves the canvas"):
        sh.check("t")


def test_a_photo_without_a_photo_directory_is_refused():
    with pytest.raises(ValueError, match="no photo directory"):
        Sheet(100, 100).photo("x.jpg", 0, 0, 50)


def test_light_and_dark_differ_only_in_colour():
    sh = Sheet(200, 100)
    sh.text(20, 40, "pin 1", 12)
    light, dark = (palette.resolve(sh.svg(), t) for t in palette.THEMES)
    assert light != dark and len(light) == len(dark)
