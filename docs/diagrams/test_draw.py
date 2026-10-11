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


def muted_items():
    """(view id, item id) for every muted item of every committed view that has a highlight."""
    out = []
    for view_id, view in VIEWS.items():
        if view.highlight:
            out += [pytest.param(view_id, i, id=f"{view_id}:{i}") for i in facts(view_id)["muted"]]
    return out


def test_every_kind_of_item_is_muted_somewhere_in_the_committed_views():
    kinds = {SCENE.item(i.values[1]).kind for i in muted_items()}
    assert {"header", "pin", "socket", "slot", "pad"} <= kinds


@pytest.mark.parametrize(("view_id", "item_id"), muted_items())
def test_a_muted_item_is_a_grey_outline_and_its_name_of_whatever_kind(view_id, item_id):
    """Issue 267: a muted part is a grey outline and its name, nothing else: no colour token but render-muted
    and no fill other than none, in its own group and in its label's."""
    svg = draw.render(SCENE, VIEWS[view_id])[0]
    drawn = groups(svg, item_id)
    assert drawn, f"{item_id} is muted but not drawn"
    for g in drawn:
        assert tokens(g) <= {"render-muted"}, f"{item_id}: {tokens(g)}"
        for e in g.iter():
            fill = e.get("fill")
            if fill is not None and e.tag not in (f"{SVG}g", f"{SVG}text"):  # a name's text is grey; shapes are not
                assert fill == "none", f"{item_id}: a muted {e.tag} is filled with {fill}"


def pin1_of(svg, inset):
    """The ids of the connectors that carry a pin 1 marker in the picture (inset False) or in its inset."""
    root = ET.fromstring(svg)
    parent = {c: p for p in root.iter() for c in p}
    out = []
    for e in root.iter():
        if e.get("data-pin1-of"):
            p, within = e, False
            while p in parent:
                p = parent[p]
                within = within or p.get("data-inset") == "1"
            if within == inset:
                out.append(e.get("data-pin1-of"))
    return out


def test_pin_1_is_marked_only_on_the_connectors_drawn_at_full_strength():
    for view_id, marked in (("acorn.bottom.p1", ["acorn.p1"]), ("acorn.bottom.p2", ["acorn.p2"])):
        svg, f = draw.render(SCENE, VIEWS[view_id])
        assert f["pin1"] == marked
        assert pin1_of(svg, inset=False) == marked
        assert pin1_of(svg, inset=True) == marked  # the muted socket's triangle is left off the inset too


def test_a_muted_connector_shown_whole_has_no_pin_1_marker():
    both = dataclasses.replace(VIEWS["acorn.bottom.p1"], crop=("acorn.p1", "acorn.p2"))
    svg, f = draw.render(SCENE, both)
    assert "acorn.p2" in f["muted"] and f["pin1"] == ["acorn.p1"]
    assert "acorn.p2" not in pin1_of(svg, inset=False)
    assert "acorn.p2" not in pin1_of(svg, inset=True)


def test_a_view_about_nothing_marks_pin_1_of_every_connector_shown_and_so_does_its_inset():
    svg = draw.render(SCENE, VIEWS["acorn.bottom.sockets"])[0]
    assert sorted(pin1_of(svg, inset=False)) == sorted(pin1_of(svg, inset=True)) == ["acorn.p1", "acorn.p2"]


def inset_picture():
    """A picture of the hat's pins-19-26 view with nothing drawn on it: what _inset_place reads. Returns it and
    the inset's size and the frame's corners, in px."""
    view = VIEWS["pi5-hat.top.pins-19-26"]
    thing = SCENE.things[view.thing]
    fr = draw._make_frame(thing, view, views.crop_box(SCENE, view))
    pic = draw.Picture(None, fr, view, [])
    fx0, fy0 = draw.BORDER, draw.BORDER
    fx1, fy1 = fx0 + fr.px_size[0], fy0 + fr.px_size[1]
    return pic, thing, (fx0, fy0, fx1, fy1)


def around(x, y, side):
    """A box of `side` px centred on (x, y)."""
    return (x - side / 2, y - side / 2, x + side / 2, y + side / 2)


def test_the_inset_is_refused_where_every_corner_would_cover_more_than_a_tenth_of_what_is_shown():
    pic, thing, (fx0, fy0, fx1, fy1) = inset_picture()
    side = 2 * draw.INSET  # an inset on one covers about a quarter of it: more than a tenth, far less than all
    pad = draw.INSET_GAP + draw.INSET_PAD
    targets = [around(x, y, side) for x in (fx0 + pad, fx1 - pad) for y in (fy0 + pad, fy1 - pad)]
    with pytest.raises(DiagramError, match="no corner has room for the inset"):
        draw._inset_place(pic, thing, targets, [])


def test_the_inset_takes_another_corner_when_the_farthest_covers_more_than_a_tenth_of_what_is_shown():
    pic, thing, (fx0, fy0, fx1, fy1) = inset_picture()
    side = 2 * draw.INSET
    pad = draw.INSET_GAP + draw.INSET_PAD
    top_left, bottom_right = around(fx0 + pad, fy0 + pad, side), around(fx1 - pad, fy1 - pad, side)
    box, _ = draw._inset_place(pic, thing, [top_left, bottom_right], [])
    # the corners at the top left and the bottom right each cover a quarter of a target; the other two are free
    at_left, at_top = box[0] == fx0 + draw.INSET_GAP, box[1] == fy0 + draw.INSET_GAP
    assert at_left != at_top  # top right or bottom left
    assert all(draw._area(draw._cut(box, t)) <= draw.INSET_COVER * draw._area(t) for t in (top_left, bottom_right))
