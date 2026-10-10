# SPDX-License-Identifier: Apache-2.0
"""The things a diagram can show and where their parts are, in millimetres, loaded from a geometry.toml.

Every table of the file names its source. Nothing here supplies a figure the file lacks."""

import difflib
import math
import pathlib
import re
from dataclasses import dataclass

import tomllib

from .errors import DiagramError

KINDS = ("board", "header", "pin", "socket", "contact", "slot", "standoff", "hole", "pad")
FACES = ("top", "bottom")
PIN_RANGE = re.compile(r"(?P<header>.+)\.pins\.(?P<first>\d+)-(?P<last>\d+)")


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


THING_KEYS = ({"name", "size", "source"}, {"headers", "items", "photos"})  # required, optional
HEADER_KEYS = ({"face", "columns", "rows", "numbering", "pitch", "pin", "pin1", "source"}, {"label"})
ITEM_KEYS = ({"kind", "face", "box", "source"}, {"label", "pin1", "z"})
PHOTO_KEYS = ({"file", "px_per_mm", "origin"}, {"shown"})


def _table(raw, what, keys):
    """`raw` is a table with every required key and no key that is not known. `source` is asked for first."""
    required, optional = keys
    if not isinstance(raw, dict):
        raise DiagramError(f"geometry: {what}: not a table")
    if "source" in required and not (isinstance(raw.get("source"), str) and raw["source"].strip()):
        raise DiagramError(f"geometry: {what}: no source")
    unknown = sorted(set(raw) - required - optional)
    if unknown:
        raise DiagramError(f"geometry: {what}: unknown key {unknown}; the keys are {sorted(required | optional)}")
    for key in sorted(required):
        if key not in raw:
            raise DiagramError(f"geometry: {what}: no {key}")


def _tables(parent, name, what):
    """The tables under `name` in `parent`, by key; none if it has no such key."""
    value = parent.get(name, {})
    if not isinstance(value, dict):
        raise DiagramError(f"geometry: {what}{name} is not a table")
    return value


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _numbers(value, n, what, positive=False):
    """`value` is a list of `n` numbers (all above zero if `positive`): as a tuple."""
    if not (
        isinstance(value, list) and len(value) == n and all(_is_number(v) and (v > 0 or not positive) for v in value)
    ):
        raise DiagramError(f"geometry: {what} {value!r} is not {n} {'positive ' if positive else ''}numbers")
    return tuple(value)


def _positive(value, what):
    if not (_is_number(value) and value > 0):
        raise DiagramError(f"geometry: {what} {value!r} is not a positive number")
    return value


def _whole(value, what, least=None):
    if not (isinstance(value, int) and not isinstance(value, bool) and (least is None or value >= least)):
        more = "" if least is None else f" of {least} or more"
        raise DiagramError(f"geometry: {what} {value!r} is not a whole number{more}")
    return value


def _label(raw, what):
    if not isinstance(raw.get("label", ""), str):
        raise DiagramError(f"geometry: {what}: label {raw['label']!r} is not text")
    return raw.get("label", "")


def _item(size, item_id, kind, face, box, label="", pin1=None, z=0):
    if kind not in KINDS:
        raise DiagramError(f"geometry: {item_id}: kind {kind!r} is not one of {KINDS}")
    if face not in FACES:
        raise DiagramError(f"geometry: {item_id}: face {face!r} is not one of {FACES}")
    if not (box.x0 < box.x1 and box.y0 < box.y1):
        raise DiagramError(f"geometry: {item_id}: {box} is not a box")
    if not Box(0, 0, *size).contains(box):
        raise DiagramError(f"geometry: {item_id}: {box} is outside its thing, {size[0]} x {size[1]} mm")
    if pin1 is not None and not box.contains(Box(*pin1, *pin1)):
        raise DiagramError(f"geometry: {item_id}: pin1 {list(pin1)} is outside its own box, {box}")
    return Item(item_id, kind, face, box, label, pin1, z)


def _header(thing_key, size, key, raw):
    """A pin header's own item and one item per pin, numbered as printed: across each row, or down each column."""
    hid = f"{thing_key}.{key}"
    _table(raw, hid, HEADER_KEYS)
    if raw["numbering"] not in ("across", "down"):
        raise DiagramError(f'geometry: {hid}: numbering must be "across" or "down"')
    cols, rows = _whole(raw["columns"], f"{hid}: columns", 1), _whole(raw["rows"], f"{hid}: rows", 1)
    pitch, pad = _positive(raw["pitch"], f"{hid}: pitch"), _positive(raw["pin"], f"{hid}: pin")
    x1, y1 = _numbers(raw["pin1"], 2, f"{hid}: pin1")
    items, half = {}, pitch / 2
    body = Box(x1 - half, y1 - half, x1 + (cols - 1) * pitch + half, y1 + (rows - 1) * pitch + half)
    items[hid] = _item(size, hid, "header", raw["face"], body, _label(raw, hid), (x1, y1), z=1)
    for r in range(rows):
        for c in range(cols):
            n = (r * cols + c if raw["numbering"] == "across" else c * rows + r) + 1
            cx, cy = x1 + c * pitch, y1 + r * pitch
            pid = f"{hid}.pin.{n}"
            box = Box(cx - pad / 2, cy - pad / 2, cx + pad / 2, cy + pad / 2)
            items[pid] = _item(size, pid, "pin", raw["face"], box, str(n), z=2)
    return items


def _shown(key, size, face, shown, items):
    """A photo that covers only `shown` = [y0, y1] mm of the thing's length: nothing on that face can be placed
    beyond it, because there is nothing to measure it in."""
    if not (isinstance(shown, list) and len(shown) == 2 and all(_is_number(v) for v in shown)) or not (
        0 <= shown[0] < shown[1] <= size[1]
    ):
        raise DiagramError(f"geometry: {key}: photo {face!r}: shown {shown} is not a range of its {size[1]} mm")
    part = Box(0, shown[0], size[0], shown[1])
    for item in items.values():
        if item.kind != "board" and item.face == face and not part.contains(item.box):
            raise DiagramError(
                f"geometry: {item.id}: {item.box} is outside the photographed part of the {face} face, "
                f"y {shown[0]} to {shown[1]} mm"
            )


def _photo(key, size, face, photo, items, photos_dir):
    what = f"{key}: photo {face!r}"
    if face not in FACES:
        raise DiagramError(f"geometry: {what}: a photo is of the top or the bottom")
    _table(photo, what, PHOTO_KEYS)
    if not (isinstance(photo["file"], str) and (photos_dir / photo["file"]).is_file()):
        raise DiagramError(f"geometry: {what}: {photos_dir / str(photo['file'])} does not exist")
    scale = photo["px_per_mm"]
    if not (isinstance(scale, list) and len(scale) == 2 and all(_is_number(v) and v > 0 for v in scale)):
        raise DiagramError(
            f"geometry: {what}: px_per_mm {scale!r} is not two positive numbers, "
            "the scale across the photo and the scale down it"
        )
    _numbers(photo["origin"], 2, f"{what}: origin")
    if "shown" in photo:
        _shown(key, size, face, photo["shown"], items)


def load(geometry_path):
    """The scene a geometry.toml describes. A photo's file is looked for in `photos/` beside the geometry file."""
    geometry_path = pathlib.Path(geometry_path)
    data = tomllib.loads(geometry_path.read_text())
    things = {}
    for key, raw in _tables(data, "things", "").items():
        _table(raw, key, THING_KEYS)
        size = _numbers(raw["size"], 2, f"{key}: size", positive=True)
        if not isinstance(raw["name"], str):
            raise DiagramError(f"geometry: {key}: name {raw['name']!r} is not text")
        items = {key: Item(key, "board", "top", Box(0, 0, *size), raw["name"])}
        for hk, h in _tables(raw, "headers", f"{key}: ").items():
            items.update(_header(key, size, hk, h))
        for ik, it in _tables(raw, "items", f"{key}: ").items():
            iid = f"{key}.{ik}"
            if iid in items:
                raise DiagramError(f"geometry: {iid}: an item and a header share this name")
            _table(it, iid, ITEM_KEYS)
            box = Box(*_numbers(it["box"], 4, f"{iid}: box"))
            pin1 = _numbers(it["pin1"], 2, f"{iid}: pin1") if "pin1" in it else None
            z = _whole(it.get("z", 1), f"{iid}: z")
            items[iid] = _item(size, iid, it["kind"], it["face"], box, _label(it, iid), pin1, z)
        for face, photo in _tables(raw, "photos", f"{key}: ").items():
            _photo(key, size, face, photo, items, geometry_path.parent / "photos")
        things[key] = Thing(key, raw["name"], size, items, raw.get("photos", {}))
    if not things:
        raise DiagramError(f"geometry: {geometry_path}: no things")
    return Scene(things)
