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


def _view(view_id, raw, sequences, scene):
    if not ID.fullmatch(view_id):
        raise DiagramError(f"view {view_id!r}: an id is lower-case words joined by dots and hyphens")
    if set(raw) - KEYS:
        raise DiagramError(f"view {view_id}: unknown key {sorted(set(raw) - KEYS)}; a view holds no words of its own")
    seq = raw.get("sequence")
    if seq is not None and seq not in sequences:
        raise DiagramError(f"view {view_id}: no sequence {seq!r}")
    base = sequences.get(seq, {})
    merged = {**base, **raw}
    for key in ("thing", "face"):
        if key not in merged:
            raise DiagramError(f"view {view_id}: no {key}")
    if merged["thing"] not in scene.things:
        raise DiagramError(f"view {view_id}: no thing {merged['thing']!r} in the model")
    if merged["face"] not in model.FACES:
        raise DiagramError(f"view {view_id}: face {merged['face']!r} is not top or bottom")
    if merged.get("turn", 0) not in (0, 90, 180, 270):
        raise DiagramError(f"view {view_id}: turn {merged['turn']} is not 0, 90, 180 or 270")
    view = View(
        view_id,
        merged["thing"],
        merged["face"],
        merged.get("turn", 0),
        tuple(raw.get("crop", ())),
        tuple(raw.get("highlight", ())),
        dict(raw.get("callouts", {})),
        seq,
        raw.get("width", 700),
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
    for key, raw in sequences.items():
        if set(raw) - SEQUENCE_KEYS:
            raise DiagramError(f"sequence {key}: unknown key {sorted(set(raw) - SEQUENCE_KEYS)}")
    out, stems = {}, {}
    for view_id, raw in data.get("views", {}).items():
        view = _view(view_id, raw, sequences, scene)
        stem = file_stem(view_id).lower()
        if stem in stems:
            raise DiagramError(f"views {stems[stem]!r} and {view_id!r} would be the same file")
        stems[stem] = view_id
        out[view_id] = view
    for key in sequences:
        points = [(v.face, v.turn) for v in out.values() if v.sequence == key]
        changes = sum(1 for a, b in zip(points, points[1:], strict=False) if a != b)
        if changes > 1:
            raise DiagramError(f"sequence {key} changes its viewpoint twice; once is the most a reader can follow")
    return out
