# SPDX-License-Identifier: Apache-2.0
"""The things a diagram can show and where their parts are, in millimetres, loaded from a geometry.toml.

Every table of the file names its source. Nothing here supplies a figure the file lacks."""

import difflib
import pathlib
import re
from dataclasses import dataclass

import tomllib

from .errors import DiagramError

KINDS = ("board", "header", "pin", "socket", "contact", "slot", "standoff", "hole", "pad")
FACES = ("top", "bottom")
PIN_RANGE = re.compile(r"(?P<header>.+)\.pins\.(?P<first>\d+)-(?P<last>\d+)")
PAD = 0.64  # the square a header pin is drawn as, mm: the pin's own section, 0.64 mm square (2.54 mm headers)


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def area(self):
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def intersect(self, other):
        box = Box(max(self.x0, other.x0), max(self.y0, other.y0), min(self.x1, other.x1), min(self.y1, other.y1))
        return box if box.x0 < box.x1 and box.y0 < box.y1 else None

    def union(self, other):
        return Box(min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1))

    def grow(self, margin):
        return Box(self.x0 - margin, self.y0 - margin, self.x1 + margin, self.y1 + margin)

    def contains(self, other, slack=0.01):
        return (
            other.x0 >= self.x0 - slack
            and other.y0 >= self.y0 - slack
            and other.x1 <= self.x1 + slack
            and other.y1 <= self.y1 + slack
        )


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    face: str
    box: Box
    label: str = ""
    pin1: tuple | None = None
    z: int = 0


@dataclass(frozen=True)
class Thing:
    key: str
    name: str
    size: tuple
    items: dict
    photos: dict


class Scene:
    def __init__(self, things):
        self.things = things
        self._items = {i.id: i for t in things.values() for i in t.items.values()}

    def item(self, item_id):
        if item_id not in self._items:
            near = difflib.get_close_matches(item_id, self._items, n=3)
            raise DiagramError(f"no item {item_id!r} in the model; nearest: {', '.join(near) or 'none'}")
        return self._items[item_id]

    def select(self, selector):
        m = PIN_RANGE.fullmatch(selector)
        if not m:
            return [self.item(selector)]
        self.item(m["header"])
        first, last = int(m["first"]), int(m["last"])
        if first > last:
            raise DiagramError(f"{selector}: the pins run backwards")
        return [self.item(f"{m['header']}.pin.{n}") for n in range(first, last + 1)]

    def thing_of(self, item_id):
        return self.things[self.item(item_id).id.split(".", 1)[0]]


def _source(table, what):
    if not table.get("source"):
        raise DiagramError(f"geometry: {what}: no source")


def _item(size, item_id, kind, face, box, label="", pin1=None, z=0):
    if kind not in KINDS:
        raise DiagramError(f"geometry: {item_id}: kind {kind!r} is not one of {KINDS}")
    if face not in FACES:
        raise DiagramError(f"geometry: {item_id}: face {face!r} is not one of {FACES}")
    if not (box.x0 < box.x1 and box.y0 < box.y1):
        raise DiagramError(f"geometry: {item_id}: {box} is not a box")
    if not Box(0, 0, *size).contains(box):
        raise DiagramError(f"geometry: {item_id}: {box} is outside its thing, {size[0]} x {size[1]} mm")
    return Item(item_id, kind, face, box, label, pin1, z)


def _header(thing_key, size, key, raw):
    """A pin header's own item and one item per pin, numbered as printed: across each row, or down each column."""
    _source(raw, f"{thing_key}.{key}")
    if raw.get("numbering") not in ("across", "down"):
        raise DiagramError(f'geometry: {thing_key}.{key}: numbering must be "across" or "down"')
    cols, rows, pitch = raw["columns"], raw["rows"], raw["pitch"]
    x1, y1 = raw["pin1"]
    items, half = {}, pitch / 2
    body = Box(x1 - half, y1 - half, x1 + (cols - 1) * pitch + half, y1 + (rows - 1) * pitch + half)
    hid = f"{thing_key}.{key}"
    items[hid] = _item(size, hid, "header", raw["face"], body, raw.get("label", ""), (x1, y1), z=1)
    for r in range(rows):
        for c in range(cols):
            n = (r * cols + c if raw["numbering"] == "across" else c * rows + r) + 1
            cx, cy = x1 + c * pitch, y1 + r * pitch
            pid = f"{hid}.pin.{n}"
            box = Box(cx - PAD / 2, cy - PAD / 2, cx + PAD / 2, cy + PAD / 2)
            items[pid] = _item(size, pid, "pin", raw["face"], box, str(n), z=2)
    return items


def _shown(key, size, face, shown, items):
    """A photo that covers only `shown` = [y0, y1] mm of the thing's length: nothing on that face can be placed
    beyond it, because there is nothing to measure it in."""
    if not (len(shown) == 2 and 0 <= shown[0] < shown[1] <= size[1]):
        raise DiagramError(f"geometry: {key}: photo {face!r}: shown {shown} is not a range of its {size[1]} mm")
    part = Box(0, shown[0], size[0], shown[1])
    for item in items.values():
        if item.kind != "board" and item.face == face and not part.contains(item.box):
            raise DiagramError(
                f"geometry: {item.id}: {item.box} is outside the photographed part of the {face} face, "
                f"y {shown[0]} to {shown[1]} mm"
            )


def load(geometry_path):
    data = tomllib.loads(pathlib.Path(geometry_path).read_text())
    things = {}
    for key, raw in data.get("things", {}).items():
        _source(raw, key)
        size = tuple(raw["size"])
        items = {key: Item(key, "board", "top", Box(0, 0, *size), raw["name"])}
        for hk, h in raw.get("headers", {}).items():
            items.update(_header(key, size, hk, h))
        for ik, it in raw.get("items", {}).items():
            _source(it, f"{key}.{ik}")
            iid = f"{key}.{ik}"
            pin1 = tuple(it["pin1"]) if "pin1" in it else None
            items[iid] = _item(
                size, iid, it["kind"], it["face"], Box(*it["box"]), it.get("label", ""), pin1, it.get("z", 1)
            )
        for face, photo in raw.get("photos", {}).items():
            if face not in FACES or set(photo) - {"shown"} != {"file", "px_per_mm", "origin"}:
                raise DiagramError(
                    f"geometry: {key}: photo {face!r} needs file, px_per_mm and origin, on top or bottom"
                )
            scale = photo["px_per_mm"]
            if not (
                isinstance(scale, list)
                and len(scale) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in scale)
            ):
                raise DiagramError(
                    f"geometry: {key}: photo {face!r}: px_per_mm {scale!r} is not two positive numbers, "
                    "the scale across the photo and the scale down it"
                )
            if "shown" in photo:
                _shown(key, size, face, photo["shown"], items)
        things[key] = Thing(key, raw["name"], size, items, raw.get("photos", {}))
    if not things:
        raise DiagramError(f"geometry: {geometry_path}: no things")
    return Scene(things)
