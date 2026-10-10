# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
import tomllib

from diagrams import model
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
GEOMETRY = ACORN / "geometry.toml"


def write(tmp_path, text):
    path = tmp_path / "geometry.toml"
    path.write_text(text)
    (tmp_path / "photos").mkdir(exist_ok=True)
    (tmp_path / "photos" / "b.jpg").write_bytes(b"")  # the photo the PHOTO table names; only its presence is checked
    return path


THING = """
[things.b]
name = "B"
size = [10.0, 20.0]
source = "a drawing"
"""


def centre(box):
    return ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)


def test_the_hat_header_is_where_geometry_toml_says_pin_by_pin():
    raw = tomllib.loads(GEOMETRY.read_text())["things"]["hat"]["headers"]["header"]
    (x, y), pitch = raw["pin1"], raw["pitch"]
    scene = model.load(GEOMETRY)
    assert scene.item("hat.header").pin1 == (x, y)
    assert centre(scene.item("hat.header.pin.1").box) == pytest.approx((x, y))
    assert centre(scene.item("hat.header.pin.2").box) == pytest.approx((x + pitch, y))  # across: 2 is beside 1
    assert centre(scene.item("hat.header.pin.3").box) == pytest.approx((x, y + pitch))
    assert centre(scene.item("hat.header.pin.40").box) == pytest.approx((x + pitch, y + 19 * pitch))  # 20 rows down
    body = scene.item("hat.header").box
    assert (body.x0, body.y0) == pytest.approx((x - pitch / 2, y - pitch / 2))
    assert (body.x1, body.y1) == pytest.approx((x + 1.5 * pitch, y + 19.5 * pitch))


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


PHOTO = '[things.b.photos.bottom]\nfile = "b.jpg"\npx_per_mm = [10.0, 9.5]\norigin = [0, 0]\nshown = [0, 12.5]\n'
ITEM = '[things.b.items.x]\nkind = "pad"\nface = "{face}"\nbox = [1, {y0}, 3, {y1}]\nsource = "s"\n'


def test_a_photo_may_say_how_much_of_the_things_length_it_shows(tmp_path):
    scene = model.load(write(tmp_path, THING + PHOTO + ITEM.format(face="bottom", y0=10, y1=12.5)))
    assert scene.things["b"].photos["bottom"]["shown"] == [0, 12.5]


def test_an_item_beyond_what_its_faces_photo_shows_is_refused(tmp_path):
    with pytest.raises(DiagramError, match=r"b\.x.*outside the photographed part"):
        model.load(write(tmp_path, THING + PHOTO + ITEM.format(face="bottom", y0=10, y1=13)))


def test_an_item_on_the_other_face_is_not_held_to_that_photo(tmp_path):
    model.load(write(tmp_path, THING + PHOTO + ITEM.format(face="top", y0=10, y1=13)))


def test_a_shown_range_that_is_not_part_of_the_thing_is_refused(tmp_path):
    for bad in ("[0, 25.0]", "[5, 5]", "[0]"):
        with pytest.raises(DiagramError, match="shown"):
            model.load(write(tmp_path, THING + PHOTO.replace("[0, 12.5]", bad)))


@pytest.mark.parametrize("bad", ["10.0", "[10.0]", "[10.0, 0]", "[10.0, -9.5]", '[10.0, "9.5"]', "[1, 2, 3]"])
def test_a_photos_scale_is_two_positive_numbers_across_and_down(tmp_path, bad):
    with pytest.raises(DiagramError, match=r"b: photo 'bottom': px_per_mm"):
        model.load(write(tmp_path, THING + PHOTO.replace("[10.0, 9.5]", bad)))


HEADER = """
[things.b.headers.h]
face = "top"
columns = 3
rows = 4
numbering = "down"
pitch = 2.0
pin = 0.5
pin1 = [2.0, 3.0]
source = "a drawing; 0.5 mm square pins"
"""


def test_a_header_must_say_how_wide_its_pins_are(tmp_path):
    with pytest.raises(DiagramError, match=r"b\.h: no pin"):
        model.load(write(tmp_path, THING + HEADER.replace("pin = 0.5\n", "")))


def test_a_pins_box_is_as_wide_as_the_header_says():
    pin = tomllib.loads(GEOMETRY.read_text())["things"]["hat"]["headers"]["header"]["pin"]
    scene = model.load(GEOMETRY)
    for n in (1, 2, 40):
        box = scene.item(f"hat.header.pin.{n}").box
        assert (box.x1 - box.x0, box.y1 - box.y0) == pytest.approx((pin, pin))


def test_a_header_numbered_down_runs_down_each_column_in_turn(tmp_path):
    scene = model.load(write(tmp_path, THING + HEADER))  # 3 columns x 4 rows, 2.0 mm apart, pin 1 at (2.0, 3.0)
    want = {1: (2.0, 3.0), 2: (2.0, 5.0), 4: (2.0, 9.0), 5: (4.0, 3.0), 8: (4.0, 9.0), 9: (6.0, 3.0), 12: (6.0, 9.0)}
    for n, at in want.items():
        assert centre(scene.item(f"b.h.pin.{n}").box) == pytest.approx(at)
    assert len(scene.select("b.h.pins.1-12")) == 12


ITEM_X = '[things.b.items.x]\nkind = "pad"\nface = "top"\nbox = [1, 1, 3, 3]\nsource = "s"\n'


def cut(text, line):
    assert text.count(line) == 1
    return text.replace(line, "")


@pytest.mark.parametrize(
    "text, message",
    [
        (THING + 'colour = "red"\n', r"b: unknown key \['colour'\]; the keys are .*name.*size"),
        (THING + HEADER + 'gender = "pin"\n', r"b\.h: unknown key \['gender'\]; the keys are .*pitch"),
        (THING + ITEM_X + 'colour = "red"\n', r"b\.x: unknown key \['colour'\]; the keys are .*kind"),
        (THING + PHOTO + "turn = 90\n", r"b: photo 'bottom': unknown key \['turn'\]; the keys are .*file"),
        (cut(THING, 'name = "B"\n'), "b: no name"),
        (cut(THING, "size = [10.0, 20.0]\n"), "b: no size"),
        (THING + cut(ITEM_X, 'kind = "pad"\n'), r"b\.x: no kind"),
        (THING + cut(ITEM_X, 'face = "top"\n'), r"b\.x: no face"),
        (THING + cut(ITEM_X, "box = [1, 1, 3, 3]\n"), r"b\.x: no box"),
        (THING + cut(HEADER, "pitch = 2.0\n"), r"b\.h: no pitch"),
        (THING + cut(HEADER, 'face = "top"\n'), r"b\.h: no face"),
        (THING + cut(HEADER, "pin1 = [2.0, 3.0]\n"), r"b\.h: no pin1"),
        (THING + cut(PHOTO, 'file = "b.jpg"\n'), "b: photo 'bottom': no file"),
        (THING + cut(PHOTO, "origin = [0, 0]\n"), "b: photo 'bottom': no origin"),
        (THING + ITEM_X.replace("[1, 1, 3, 3]", "[1, 1, 3]"), r"b\.x: box \[1, 1, 3\] is not 4 numbers"),
        (THING + ITEM_X.replace("[1, 1, 3, 3]", '[1, 1, 3, "3"]'), r"b\.x: box .* is not 4 numbers"),
        (THING + ITEM_X.replace("[1, 1, 3, 3]", "7"), r"b\.x: box 7 is not 4 numbers"),
        (THING.replace("[10.0, 20.0]", "[10.0]"), r"b: size \[10\.0\] is not 2 positive numbers"),
        (THING.replace("[10.0, 20.0]", "[10.0, -1]"), "b: size .* is not 2 positive numbers"),
        (THING.replace("[10.0, 20.0]", '"big"'), "b: size 'big' is not 2 positive numbers"),
        (THING + PHOTO.replace("[0, 0]", "[0]"), r"b: photo 'bottom': origin \[0\] is not 2 numbers"),
        (THING + PHOTO.replace('"b.jpg"', '"c.jpg"'), r"b: photo 'bottom': .*photos.c\.jpg does not exist"),
        (THING + PHOTO.replace("photos.bottom", "photos.side"), "b: photo 'side': a photo is of the top or the bottom"),
        (THING + ITEM_X + "pin1 = [4, 2]\n", r"b\.x: pin1 \[4, 2\] is outside its own box"),
        (THING + ITEM_X + "pin1 = [2]\n", r"b\.x: pin1 \[2\] is not 2 numbers"),
        (THING + ITEM_X.replace('source = "s"', 'source = ""'), r"b\.x: no source"),
        (THING + ITEM_X.replace('source = "s"', "source = 3"), r"b\.x: no source"),
        (THING.replace('source = "a drawing"', 'source = ["a drawing"]'), "b: no source"),
        (THING + HEADER + ITEM_X.replace("items.x", "items.h"), r"b\.h: an item and a header share this name"),
        (THING + HEADER + ITEM_X.replace("items.x", 'items."h.pin.3"'), r"b\.h\.pin\.3: .*share this name"),
        (THING + HEADER.replace("columns = 3", "columns = 0"), r"b\.h: columns 0 is not a whole number of 1 or more"),
        (THING + HEADER.replace("rows = 4", "rows = 4.5"), r"b\.h: rows 4\.5 is not a whole number of 1 or more"),
        (THING + HEADER.replace("pitch = 2.0", "pitch = 0"), r"b\.h: pitch 0 is not a positive number"),
        (THING + HEADER.replace("pin = 0.5", 'pin = "thin"'), r"b\.h: pin 'thin' is not a positive number"),
        (THING + HEADER.replace('"down"', '"snake"'), r"b\.h: numbering"),
        (THING + ITEM_X + 'z = "high"\n', r"b\.x: z 'high' is not a whole number"),
        (THING + ITEM_X + "label = 3\n", r"b\.x: label 3 is not text"),
        ("[things]\nb = 3\n", "b: not a table"),
        (THING + "[things.b.items]\nx = 3\n", r"b\.x: not a table"),
    ],
)
def test_a_malformed_geometry_is_refused_naming_the_table_and_the_key(tmp_path, text, message):
    with pytest.raises(DiagramError, match="geometry: " + message):
        model.load(write(tmp_path, text))


def test_the_well_formed_tables_those_cases_start_from_load(tmp_path):
    scene = model.load(write(tmp_path, THING + HEADER + ITEM_X + "pin1 = [2, 2]\nz = 3\n" + PHOTO))
    assert scene.item("b.x").pin1 == (2, 2) and scene.item("b.x").z == 3
