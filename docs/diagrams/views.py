# SPDX-License-Identifier: Apache-2.0
"""The views a views.toml declares, checked against the model: a view that cannot be drawn is refused here."""

import pathlib
import re
from dataclasses import dataclass

import tomllib

from . import model
from .errors import DiagramError

ID = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
KEYS = {"thing", "face", "turn", "crop", "highlight", "callouts", "sequence", "width"}
SEQUENCE_KEYS = {"thing", "face", "turn"}
MARGIN = 3.0  # mm of the thing shown round a crop's items
WIDTH, NARROWEST = 700, 100  # px: a view's width when it gives none, and the least it may give


@dataclass(frozen=True)
class View:
    id: str
    thing: str
    face: str
    turn: int
    crop: tuple
    highlight: tuple
    callouts: dict
    sequence: str | None
    width: int


def file_stem(view_id):
    """The name of a view's files, without the extension: its id. Ids are lower case (ID), so two ids never
    name one file on a file system that does not tell A from a."""
    return view_id


def crop_box(scene, view):
    """The box, in the thing's frame, that a view's crop names: its items' union and a margin, kept on the thing."""
    thing = scene.things[view.thing]
    whole = model.Box(0, 0, *thing.size)
    if not view.crop:
        return whole
    boxes = [i.box for s in view.crop for i in scene.select(s)]
    box = boxes[0]
    for b in boxes[1:]:
        box = box.union(b)
    return box.grow(MARGIN).intersect(whole)


def _ids(view_id, raw, key):
    value = raw.get(key, [])
    if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        raise DiagramError(f"view {view_id}: {key} {value!r} is not a list of item ids")
    return tuple(value)


def _callouts(view_id, raw):
    value = raw.get("callouts", {})
    if not isinstance(value, dict):
        raise DiagramError(f"view {view_id}: callouts {value!r} is not a table of item id = number")
    for item, n in value.items():
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
            raise DiagramError(
                f"view {view_id}: callouts: {item} = {n!r} is not a whole number of 1 or more; "
                "a view holds no words of its own"
            )
    return dict(value)


def _view(view_id, raw, sequences, scene):
    if not ID.fullmatch(view_id):
        raise DiagramError(f"view {view_id!r}: an id is lower-case words joined by dots and hyphens")
    if not isinstance(raw, dict):
        raise DiagramError(f"view {view_id}: not a table")
    if set(raw) - KEYS:
        raise DiagramError(f"view {view_id}: unknown key {sorted(set(raw) - KEYS)}; a view holds no words of its own")
    seq = raw.get("sequence")
    if seq is not None and not (isinstance(seq, str) and seq in sequences):
        raise DiagramError(f"view {view_id}: no sequence {seq!r}")
    base = sequences.get(seq, {})
    merged = {**base, **raw}
    for key in ("thing", "face"):
        if key not in merged:
            raise DiagramError(f"view {view_id}: no {key}")
    if not (isinstance(merged["thing"], str) and merged["thing"] in scene.things):
        raise DiagramError(f"view {view_id}: no thing {merged['thing']!r} in the model")
    if not (isinstance(merged["face"], str) and merged["face"] in model.FACES):
        raise DiagramError(f"view {view_id}: face {merged['face']!r} is not top or bottom")
    turn = merged.get("turn", 0)
    if not (isinstance(turn, int) and not isinstance(turn, bool) and turn in (0, 90, 180, 270)):
        raise DiagramError(f"view {view_id}: turn {turn!r} is not 0, 90, 180 or 270")
    width = raw.get("width", WIDTH)
    if not (isinstance(width, int) and not isinstance(width, bool) and width >= NARROWEST):
        raise DiagramError(f"view {view_id}: width {width!r} is not a whole number of {NARROWEST} or more")
    view = View(
        view_id,
        merged["thing"],
        merged["face"],
        turn,
        _ids(view_id, raw, "crop"),
        _ids(view_id, raw, "highlight"),
        _callouts(view_id, raw),
        seq,
        width,
    )
    try:
        named = [i for s in (*view.crop, *view.highlight, *view.callouts) for i in scene.select(s)]
    except DiagramError as e:
        raise DiagramError(f"view {view_id}: {e}") from None
    for item in named:
        if item.id.split(".", 1)[0] != view.thing:
            raise DiagramError(f"view {view_id}: {item.id} is not part of {view.thing}")
        if item.face != view.face and item.kind != "board":
            raise DiagramError(f"view {view_id}: {item.id} is on the {item.face} face, not on the face shown")
    frame = crop_box(scene, view)
    for s in view.highlight:
        for item in scene.select(s):
            if not frame.contains(item.box):
                raise DiagramError(f"view {view_id}: highlighted {item.id} is outside the crop")
    return view


def load(views_path, scene):
    data = tomllib.loads(pathlib.Path(views_path).read_text())
    sequences = data.get("sequences", {})
    if not isinstance(sequences, dict):
        raise DiagramError(f"{views_path}: sequences is not a table")
    for key, raw in sequences.items():
        if not isinstance(raw, dict):
            raise DiagramError(f"sequence {key}: not a table")
        if set(raw) - SEQUENCE_KEYS:
            raise DiagramError(f"sequence {key}: unknown key {sorted(set(raw) - SEQUENCE_KEYS)}")
    declared = data.get("views")
    if not (isinstance(declared, dict) and declared):
        raise DiagramError(f"{views_path}: no views")
    out = {view_id: _view(view_id, raw, sequences, scene) for view_id, raw in declared.items()}
    for key in sequences:
        points = [(v.face, v.turn) for v in out.values() if v.sequence == key]
        changes = sum(1 for a, b in zip(points, points[1:], strict=False) if a != b)
        if changes > 1:
            raise DiagramError(f"sequence {key} changes its viewpoint twice; once is the most a reader can follow")
    return out
