# SPDX-License-Identifier: Apache-2.0
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"))

import measure_card
import measure_hat
import pytest
from PIL import Image

from diagrams import match, model

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
GEOMETRY = ACORN / "geometry.toml"
PHOTOS = ACORN / "photos"
SCENE = model.load(GEOMETRY)

# What a photo must show at an item's box. The slot is there when the box's mean luminance differs from the ring 1 mm
# round it by at least PART levels; a pin's solder pad and the plated pad are there when the box is brighter than
# its ring (the header's own box likewise: its pads in black board). A socket's box is the silkscreen outline
# measure_card measured, so it is held to that outline, not to its fill: the band along the box's edge must be at
# least OUTLINE levels brighter than the board beside it, on at least one side of the line (a line is brighter
# than the board on one side or the other; a side cut away by the card's edge does not count). All four sides must
# pass. The thin ones, unmoved: P1's inner long side (about 16, the cable lies over it) and P2's far end (about 16).
# A known limit: a socket moved 0.5 mm along its length still passes (P1's end, 16.4 outside); the position test
# (geometry within half the 0.1 mm storage step of the boxes measure_card measured) is what holds that.
PART = 12
RING_MM = 1.0
OUTLINE = 12  # the same 12 levels as PART: the outline is white silkscreen on black board
BAND_MM = 0.25  # the line is about 0.22 mm wide on the photo (5 px where clean: P2's far side, P1's M.2 side)
INSIDE_MM = (0.25, 0.75)  # inside the box, clear of the line and its blur
OUTSIDE_MM = (0.5, 1.0)  # outside it, likewise


def photographed():
    """Every (thing, item) whose face has a photo, the board item itself excluded."""
    return [
        pytest.param(thing, item, id=item.id)
        for thing in SCENE.things.values()
        for item in thing.items.values()
        if item.kind != "board" and item.face in thing.photos
    ]


def measure(thing, item, photos_dir=PHOTOS):
    """(measured, needed, kind): the item's contrast in its photo and what its kind needs of it."""
    photo = thing.photos[item.face]
    with Image.open(photos_dir / photo["file"]) as raw:
        image = raw.convert("L")
    sx, sy = photo["px_per_mm"]
    # Compared only on the board, and on the part of its length the photo shows.
    y0, y1 = photo.get("shown", [0, thing.size[1]])
    part = model.Item(thing.key, "board", item.face, model.Box(0, y0, thing.size[0], y1))
    board = match.item_px(thing, part)
    if item.kind == "socket":
        sides = match.outline_sides(
            image, match.item_px(thing, item), (sx, sy), BAND_MM, INSIDE_MM, OUTSIDE_MM, clip_px=board
        )
        best = {side: max(v for v in pair if v is not None) for side, pair in sides.items()}
        weakest = min(best, key=best.get)
        return best[weakest], OUTLINE, f"socket {weakest} side (inside, outside) {sides[weakest]}"
    got = match.contrast_inside(image, match.item_px(thing, item), (RING_MM * sx, RING_MM * sy), clip_px=board)
    if item.kind in ("pin", "pad", "header"):
        return got, 0.0, item.kind
    if item.kind == "slot":
        return abs(got), PART, item.kind
    pytest.fail(f"no photo test for kind {item.kind}")


@pytest.mark.parametrize(("thing", "item"), photographed())
def test_the_items_box_lies_on_its_feature_in_the_photo(thing, item):
    got, needed, kind = measure(thing, item)
    if kind.startswith("socket"):
        assert got >= needed, f"{item.id}: the outline's {kind} is only {got:.1f} above the board beside it < {needed}"
    elif kind in ("pin", "pad", "header"):
        assert got > needed, f"{item.id}: the {kind} is not brighter than the board round it ({got:.1f})"
    else:
        assert got >= needed, f"{item.id}: the {kind} differs from the board round it by {got:.1f} < {needed}"


def test_a_kind_with_no_photo_test_fails_the_run():
    thing = SCENE.things["hat"]
    odd = model.Item("hat.x", "standoff", "top", model.Box(1, 1, 2, 2))
    with pytest.raises(pytest.fail.Exception, match="no photo test for kind standoff"):
        measure(thing, odd)


def test_overlay_is_the_size_of_the_photo():
    for key, face in (("hat", "top"), ("acorn", "bottom")):
        with Image.open(PHOTOS / SCENE.things[key].photos[face]["file"]) as photo:
            size = photo.size
        assert match.overlay(SCENE, key, face, PHOTOS).size == size


def test_pin_1_of_the_hat_header_lands_where_measure_hat_found_it():
    px = measure_hat.measure(PHOTOS / SCENE.things["hat"].photos["top"]["file"])
    x0, y0, x1, y1 = match.item_px(SCENE.things["hat"], SCENE.item("hat.header.pin.1"))
    assert (x0 + x1) / 2 == pytest.approx(px["columns"][0] + 0.5, abs=0.5)
    assert (y0 + y1) / 2 == pytest.approx(px["row"] + 0.5, abs=0.5)


def test_the_slot_lands_on_the_box_measure_hat_found():
    px = measure_hat.measure(PHOTOS / SCENE.things["hat"].photos["top"]["file"])
    got = match.item_px(SCENE.things["hat"], SCENE.item("hat.m2-slot"))
    assert got == pytest.approx(px["m2_slot"], abs=1.0)


@pytest.mark.parametrize("name", ["p1", "p2", "pad"])
def test_each_card_box_lands_on_the_box_measure_card_found(name):
    """geometry.toml keeps the card to 0.1 mm, so a box lies within half of that step, in pixels, of what was
    measured (the pad and each socket)."""
    px = measure_card.measure(PHOTOS / measure_card.PHOTO)
    want = px["pad"] if name == "pad" else px["sockets"][name.upper()]
    got = match.item_px(SCENE.things["acorn"], SCENE.item(f"acorn.{name}"))
    sx, sy = SCENE.things["acorn"].photos["bottom"]["px_per_mm"]
    for have, wanted, scale in zip(got, want, (sx, sy, sx, sy), strict=True):
        assert have == pytest.approx(wanted, abs=0.05 * scale + 0.01)


def mutated(tmp_path, thing, table, key, shift):
    """A copy of geometry.toml and its photos in tmp_path, with `key` of [things.<thing>.<table>] moved by
    `shift` (dx, dy) or, for a box, its two y ends by shift[1]."""
    (tmp_path / "photos").mkdir()
    for name in {p["file"] for t in SCENE.things.values() for p in t.photos.values()}:
        shutil.copy(PHOTOS / name, tmp_path / "photos" / name)
    lines, inside, out = GEOMETRY.read_text().splitlines(), False, []
    for line in lines:
        if line.startswith("["):
            inside = line == f"[things.{thing}.{table}]"
        if inside and line.startswith(f"{key} = ["):
            values = [float(v) for v in line.split("[")[1].rstrip("]").split(",")]
            step = shift * (len(values) // 2) if len(values) == 4 else shift
            values = [round(v + step[i % 2], 2) for i, v in enumerate(values)]
            line = f"{key} = {values}"
        out.append(line)
    (tmp_path / "geometry.toml").write_text("\n".join(out) + "\n")
    return model.load(tmp_path / "geometry.toml")


@pytest.mark.parametrize("shift", [(-1.27, 0), (0, 1.27)], ids=["across", "down"])
def test_moving_the_hat_header_by_half_a_pitch_fails_the_pin_test(tmp_path, shift):
    scene = mutated(tmp_path, "hat", "headers.header", "pin1", shift)
    thing = scene.things["hat"]
    pins = [i for i in thing.items.values() if i.kind == "pin"]
    failing = [i.id for i in pins if measure(thing, i, tmp_path / "photos")[0] <= 0]
    assert "hat.header.pin.1" in failing
    assert len(failing) > len(pins) // 2


@pytest.mark.parametrize("shift", [(0, 1.0), (0, -1.0), (-0.5, 0)], ids=["along", "back", "across"])
@pytest.mark.parametrize("name", ["p1", "p2"])
def test_moving_a_card_socket_fails_its_test(tmp_path, name, shift):
    scene = mutated(tmp_path, "acorn", f"items.{name}", "box", shift)
    thing = scene.things["acorn"]
    got, needed, _ = measure(thing, thing.items[f"acorn.{name}"], tmp_path / "photos")
    assert got < needed
