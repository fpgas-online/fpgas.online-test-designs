# SPDX-License-Identifier: Apache-2.0
import dataclasses
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import canvas, draw, model, palette, views
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
SCENE = model.load(ACORN / "geometry.toml")
VIEWS = views.load(ACORN / "views.toml", SCENE)
SVG = "{http://www.w3.org/2000/svg}"


def facts(view_id, scene=SCENE):
    return draw.render(scene, VIEWS[view_id])[1]


def with_item(item):
    """SCENE with one item replaced."""
    key = item.id.split(".", 1)[0]
    thing = SCENE.things[key]
    return model.Scene({**SCENE.things, key: dataclasses.replace(thing, items={**thing.items, item.id: item})})


def tokens(element):
    """Every colour token on `element` and everything inside it."""
    found = set()
    for e in element.iter():
        for name in ("fill", "stroke"):
            m = palette.TOKEN.fullmatch(e.get(name, ""))
            if m:
                found.add(m.group(1))
    return found


def groups(svg, item_id):
    """The item's drawn group and the group of its label, if it has one."""
    root = ET.fromstring(svg)
    return [g for g in root.iter(f"{SVG}g") if g.get("id") == item_id or g.get("data-label-of") == item_id]


def test_every_committed_view_draws_and_resolves_in_both_themes():
    for view in VIEWS.values():
        svg, _ = draw.render(SCENE, view)
        for theme in palette.THEMES:
            assert "@@" not in palette.resolve(svg, theme)


def test_a_whole_thing_view_has_no_inset_and_mutes_nothing():
    f = facts("pi5-hat.top")
    assert not f["inset"] and not f["muted"] and "hat.header" in f["items"] and "hat.m2-slot" in f["items"]


def test_a_crop_has_an_inset_and_draws_only_what_meets_the_frame():
    f = facts("pi5-hat.top.pins-19-26")
    assert f["inset"]
    assert "hat.header.pin.19" in f["items"] and "hat.m2-slot" not in f["items"]


def test_highlight_mutes_everything_else_but_the_board():
    f = facts("pi5-hat.top.pins-19-26")
    assert set(f["highlight"]) == {f"hat.header.pin.{n}" for n in range(19, 27)}
    assert "hat.header.pin.17" in f["muted"] and "hat" not in f["muted"]
    assert not set(f["highlight"]) & set(f["muted"])


def test_a_highlighted_connector_shows_its_pin_1():
    assert "hat.header" in facts("pi5-hat.top.header")["pin1"]
    assert "acorn.p1" in facts("acorn.bottom.p1")["pin1"]


def test_the_frame_grows_to_hold_pin_1_of_a_highlighted_socket():
    view = VIEWS["acorn.bottom.p1"]
    _, f = draw.render(SCENE, view)
    assert f["frame_mm"][0] <= SCENE.item("acorn.p1").pin1[0] <= f["frame_mm"][2]
    assert f["frame_mm"][1] <= SCENE.item("acorn.p1").pin1[1] <= f["frame_mm"][3]


def test_the_frame_grows_past_the_board_to_hold_a_pin_1_marker_the_crop_cuts_off():
    # P1 moved to the card's long edge, pin 1 at that edge: the crop stops at the card, so the marker beside
    # pin 1 is off it until the frame grows.
    p1 = SCENE.item("acorn.p1")
    edge = dataclasses.replace(p1, box=model.Box(16.4, 13.6, 22.0, 23.2), pin1=(21.9, 18.4))
    scene = with_item(edge)
    assert views.crop_box(scene, VIEWS["acorn.bottom.p1"]).x1 == 22.0
    svg, f = draw.render(scene, VIEWS["acorn.bottom.p1"])
    assert f["frame_mm"][2] > 22.0 and "acorn.p1" in f["pin1"]
    root = ET.fromstring(svg)
    w, h = float(root.get("width")), float(root.get("height"))
    marker = next(e for e in root.iter() if e.get("data-pin1-of") == "acorn.p1")
    xs = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", marker.find(f"{SVG}path").get("d"))]
    assert all(draw.BORDER <= x <= w - draw.BORDER for x in xs[0::2])
    assert all(draw.BORDER <= y <= h - draw.BORDER for y in xs[1::2])


def test_the_picture_is_as_wide_as_the_view_asks_plus_its_border():
    assert facts("pi5-hat.top")["size"][0] == 700 + 2 * draw.BORDER


def test_a_label_of_more_than_four_words_is_refused():
    scene = with_item(dataclasses.replace(SCENE.item("hat.m2-slot"), label="the slot the card goes in"))
    with pytest.raises(DiagramError, match="more than four words"):
        draw.render(scene, VIEWS["pi5-hat.top.m2-slot"])


def test_a_label_with_no_room_beside_its_item_is_refused_naming_it():
    scene = with_item(dataclasses.replace(SCENE.item("acorn.p1"), label="Pico EZmate socket one"))
    narrow = dataclasses.replace(VIEWS["acorn.bottom.p1"], crop=(), width=100)  # the whole card: no inset
    with pytest.raises(DiagramError, match=r"label 'Pico EZmate socket one'"):
        draw.render(scene, narrow)


def test_a_view_too_small_for_its_inset_is_refused():
    tiny = dataclasses.replace(VIEWS["pi5-hat.top.pins-19-26"], width=120)
    with pytest.raises(DiagramError, match=r"inset|leaves|overlaps"):
        draw.render(SCENE, tiny)


def test_a_highlighted_item_less_than_half_in_the_frame_is_refused():
    off = dataclasses.replace(VIEWS["acorn.bottom.p2"], highlight=("acorn.p1",))
    with pytest.raises(DiagramError, match=r"view acorn\.bottom\.p2: less than half of acorn\.p1 shows"):
        draw.render(SCENE, off)


def test_the_two_themes_differ_only_in_colour():
    svg, _ = draw.render(SCENE, VIEWS["pi5-hat.top.header"])
    light, dark = (palette.resolve(svg, t) for t in palette.THEMES)

    def strip(s):
        return re.sub(r"#[0-9a-fA-F]{3,6}", "#", s)

    assert strip(light) == strip(dark) and light != dark


@pytest.mark.parametrize("shown, other", [("acorn.p1", "acorn.p2"), ("acorn.p2", "acorn.p1")])
def test_a_socket_view_colours_only_its_socket(shown, other):
    view_id = f"acorn.bottom.{shown.split('.')[1]}"
    svg, f = draw.render(SCENE, VIEWS[view_id])
    assert f["highlight"] == [shown] and other in f["muted"] and shown not in f["muted"]
    assert f["labels"] == [SCENE.item(shown).label]
    assert f["muted_labels"] == [SCENE.item(other).label]
    drawn = groups(svg, other)
    assert len(drawn) == 2  # the socket, and its name
    assert set().union(*(tokens(g) for g in drawn)) == {"render-muted"}
    assert {"render-part", "mark"} <= set().union(*(tokens(g) for g in groups(svg, shown)))


def test_a_view_about_both_sockets_mutes_neither():
    both = dataclasses.replace(VIEWS["acorn.bottom.sockets"], highlight=("acorn.p1", "acorn.p2"))
    f = draw.render(SCENE, both)[1]
    assert set(f["highlight"]) == {"acorn.p1", "acorn.p2"}
    assert "acorn.p1" not in f["muted"] and "acorn.p2" not in f["muted"]
    assert sorted(f["labels"]) == ["P1", "P2"] and not f["muted_labels"]


def test_a_view_with_no_highlight_mutes_nothing_and_marks_nothing():
    svg, f = draw.render(SCENE, VIEWS["acorn.bottom.sockets"])
    assert not f["highlight"] and not f["muted"] and not f["muted_labels"]
    assert sorted(f["labels"]) == ["P1", "P2"] and {"acorn.p1", "acorn.p2"} <= set(f["pin1"])
    assert "@@mark@@" not in svg.split('data-inset="1"')[0] and "@@render-muted@@" not in svg.split('data-inset="1"')[0]


def test_muted_parts_are_grey_lines_that_show_on_the_board_and_their_names_read_on_both_themes():
    muted, board = palette.role("render-muted"), palette.role("render-board")
    for theme in palette.THEMES:
        grey, ground = palette.value(muted, theme), palette.value(board, theme)
        r, g, b = palette.rgb(grey)
        assert max(r, g, b) - min(r, g, b) <= 0x14, "a muted part is grey, not a colour"
        assert palette.contrast(grey, ground) >= 3.0  # a non-text mark (WCAG 1.4.11)
        assert palette.contrast(grey, ground) >= canvas.TEXT_SMALL  # its name, drawn on the board
        part = palette.value(palette.role("render-part"), theme)
        assert palette.contrast(part, ground) >= 3.0
