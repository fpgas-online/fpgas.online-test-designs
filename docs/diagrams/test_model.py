# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import model
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
GEOMETRY = ACORN / "geometry.toml"


def write(tmp_path, text):
    path = tmp_path / "geometry.toml"
    path.write_text(text)
    return path


THING = """
[things.b]
name = "B"
size = [10.0, 20.0]
source = "a drawing"
"""


def test_the_committed_geometry_loads_and_has_the_hat_header():
    scene = model.load(GEOMETRY)
    pin1, pin2, pin40 = (scene.item(f"hat.header.pin.{n}") for n in (1, 2, 40))
    assert scene.item("hat.header").pin1 == pytest.approx(
        ((pin1.box.x0 + pin1.box.x1) / 2, (pin1.box.y0 + pin1.box.y1) / 2)
    )
    assert pin2.box.x0 - pin1.box.x0 == pytest.approx(2.54)  # across: 2 is beside 1
    assert pin40.box.y0 - pin2.box.y0 == pytest.approx(19 * 2.54)  # 20 rows down


def test_a_pin_range_selects_those_pins():
    scene = model.load(GEOMETRY)
    got = [i.id.rsplit(".", 1)[1] for i in scene.select("hat.header.pins.19-26")]
    assert got == [str(n) for n in range(19, 27)]


def test_an_unknown_id_is_refused_with_the_nearest_ids():
    with pytest.raises(DiagramError, match=r"hat\.m2-slto.*hat\.m2-slot"):
        model.load(GEOMETRY).item("hat.m2-slto")


def test_a_table_without_a_source_is_refused(tmp_path):
    text = THING.replace('source = "a drawing"\n', "")
    with pytest.raises(DiagramError, match="b: no source"):
        model.load(write(tmp_path, text))


def test_an_item_outside_its_thing_is_refused(tmp_path):
    text = THING + '[things.b.items.x]\nkind = "pad"\nface = "top"\nbox = [8, 0, 12, 4]\nsource = "s"\n'
    with pytest.raises(DiagramError, match=r"b\.x.*outside"):
        model.load(write(tmp_path, text))


def test_an_unknown_kind_or_face_is_refused(tmp_path):
    text = THING + '[things.b.items.x]\nkind = "blob"\nface = "top"\nbox = [1, 1, 2, 2]\nsource = "s"\n'
    with pytest.raises(DiagramError, match="kind"):
        model.load(write(tmp_path, text))


def test_box_arithmetic():
    a, b = model.Box(0, 0, 4, 4), model.Box(2, 2, 6, 6)
    assert a.intersect(b) == model.Box(2, 2, 4, 4) and a.intersect(model.Box(5, 5, 6, 6)) is None
    assert a.union(b) == model.Box(0, 0, 6, 6) and a.grow(1) == model.Box(-1, -1, 5, 5)
    assert a.area() == 16 and a.contains(model.Box(1, 1, 3, 3)) and not a.contains(b)
