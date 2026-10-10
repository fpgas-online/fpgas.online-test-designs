# SPDX-License-Identifier: Apache-2.0
"""Where a point of a thing lands in a picture, for a face, a turn and a crop; and how much of an item shows."""

from dataclasses import dataclass

from . import views
from .errors import DiagramError
from .model import FACES, Box

GRID = 0.1  # mm: the grid visible_fraction counts on
TURNS = (0, 90, 180, 270)  # degrees clockwise


@dataclass(frozen=True)
class Frame:
    box: Box
    size: tuple
    face: str
    turn: int
    scale: float
    origin: tuple

    def __post_init__(self):
        if self.face not in FACES:
            raise DiagramError(f"a frame's face {self.face!r} is not one of {FACES}")
        if self.turn not in TURNS:
            raise DiagramError(f"a frame's turn {self.turn!r} is not one of {TURNS}")

    def _seen(self, x, y):
        """A point of the thing as seen from `face`, unturned, relative to the frame's own top left, in mm."""
        b = self.box
        if self.face == "bottom":
            return (self.size[0] - x) - (self.size[0] - b.x1), y - b.y0
        return x - b.x0, y - b.y0

    def to_px(self, x, y):
        u, v = self._seen(x, y)
        w, h = self.box.x1 - self.box.x0, self.box.y1 - self.box.y0
        u, v = {0: (u, v), 90: (h - v, u), 180: (w - u, h - v), 270: (v, w - u)}[self.turn]
        return self.origin[0] + u * self.scale, self.origin[1] + v * self.scale

    def box_px(self, box):
        (ax, ay), (bx, by) = self.to_px(box.x0, box.y0), self.to_px(box.x1, box.y1)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    @property
    def px_size(self):
        w, h = (self.box.x1 - self.box.x0) * self.scale, (self.box.y1 - self.box.y0) * self.scale
        return (h, w) if self.turn in (90, 270) else (w, h)


def view_frame(scene, view, origin=(0.0, 0.0), width_px=None):
    """The frame of a view, scaled so that the picture is `width_px` wide (the view's own width by default)."""
    box = views.crop_box(scene, view)
    w, h = box.x1 - box.x0, box.y1 - box.y0
    across = h if view.turn in (90, 270) else w
    return Frame(box, scene.things[view.thing].size, view.face, view.turn, (width_px or view.width) / across, origin)


def visible_fraction(item_box, frame_box, covers):
    inside = item_box.intersect(frame_box)
    if inside is None:
        return 0.0
    nx, ny = max(1, round((item_box.x1 - item_box.x0) / GRID)), max(1, round((item_box.y1 - item_box.y0) / GRID))
    seen = 0
    for j in range(ny):
        y = item_box.y0 + (j + 0.5) * (item_box.y1 - item_box.y0) / ny
        for i in range(nx):
            x = item_box.x0 + (i + 0.5) * (item_box.x1 - item_box.x0) / nx
            in_frame = frame_box.x0 <= x <= frame_box.x1 and frame_box.y0 <= y <= frame_box.y1
            if in_frame and not any(c.x0 <= x <= c.x1 and c.y0 <= y <= c.y1 for c in covers):
                seen += 1
    return seen / (nx * ny)
