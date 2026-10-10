# Diagram Views, Family A (Engine and Boards) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A board-neutral view engine that renders named views (crop, highlight, orientation, theme, inset) of the Acorn card and the Waveshare PoE M.2 HAT+ (B) from one model, with a manifest pages can reference by id.

**Architecture:** A new package `docs/diagrams/` holds the canvas and palette (lifted unchanged from `docs/wiring/acorn/`), a scene model (objects, items, millimetre geometry with sources), a view loader, the frame and visibility arithmetic, the drawing of the render layer, and a build command with a stale check. Board data (`geometry.toml`, `views.toml`) sits beside `wiring.toml`. The existing generator keeps working and its output stays byte for byte the same.

**Tech Stack:** Python 3.12 run with `uv run`; Pillow 12.3.0 and fontTools 4.65.0 (the existing pins); pytest; ruff; headless Chrome for PNGs (`render.py`'s method). No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-10-diagram-views-design.md`

**As built (tasks 1 to 5):** review changed some interfaces after this plan was written. Where they differ, the code is right: a photo's `px_per_mm` is two numbers, `[across, down]`; a header table carries `pin` (the width of a pin, with its source) in place of `model.PAD`; the card's figures are stored to 0.1 mm; `measure_card.measure_mm` returns both scales and no `contact_pitch_mm`; `Frame` refuses an unknown face or turn; a views file with no views is refused. Tasks 6 to 9 are to be read against the code.

## Global Constraints

- Python only through `uv run`; never `python -c`; no file in the system temp directory (use `./tmp/`, git-ignored, and remove it); never redirect stderr to `/dev/null`.
- Every colour is a `palette.py` token; a hex colour in drawing code stops the build (existing rule).
- A view holds no title and no sentence: a label is at most four words and is the item's name as printed on the part.
- Geometry in `geometry.toml` is in millimetres, and every table has a `source`. A figure nobody has measured is not written; the code never substitutes a default.
- Fail fast and loud: every rule failure raises `DiagramError` naming the view id and the rule. No fallback drawing, no "unknown" label.
- `uv run docs/wiring/acorn/gen.py --check` must print `generated/ is up to date` after every task (the old pictures do not change).
- Lint: `uv run --no-project --with ruff ruff check docs/diagrams docs/wiring/acorn` and `ruff format --check` on the same paths; line length and style as `pyproject.toml` sets them.
- Tests run as CI runs them: `uv run --no-project --python 3.12 --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/diagrams docs/wiring/acorn`.
- No names of people in any file. Dates day-first or ISO 8601.
- Commits are small (one task step group each), never over 400 added lines or 15 files: generated PNGs are committed separately from code, a few per commit. Stage and commit in separate commands. Each message ends with the two attribution lines the session gives.
- Nothing is pushed and no pull request is opened by a task; the session lead does that after the last task.

## Review Focus

1. A crop naming an item on the other face of the object (P1 is on the card's bottom face; a `face = "top"` view cropping to it). Expected: the build stops and says the item is not on the face shown. Test in Task 4.
2. A crop so tight that the label of a highlighted item or the pin 1 marker falls outside the frame. Expected: the frame grows to hold the marker; if a label still does not fit, the build stops naming the label. Test in Task 6.
3. A `turn` of 90 or 270 on a non-square object: width and height swap, and every item box, pin 1 point and the inset turn with it. Expected: pin 1 is on the turned position, checked numerically. Test in Task 4.
4. Two views with ids that differ only in case, which would be one file on a case-folding file system. Expected: an upper-case id is refused at load. Test in Task 3.
5. `views.toml` or `geometry.toml` edited without regenerating. Expected: `build.py --check` fails naming each stale view, including a view removed from the file whose PNG is still there. Test in Task 7.

---

## File Structure

| File | Responsibility |
|---|---|
| `docs/diagrams/__init__.py` | Empty; makes the package importable |
| `docs/diagrams/palette.py` | Moved from `docs/wiring/acorn/palette.py`, unchanged |
| `docs/diagrams/canvas.py` | `Sheet`, `Font` and the text and contrast checks, moved from `sheetlib.py`; takes the photo directory as a parameter |
| `docs/diagrams/fonts/` | Moved from `docs/wiring/acorn/fonts/` |
| `docs/diagrams/errors.py` | `DiagramError` |
| `docs/diagrams/model.py` | `Box`, `Item`, `Thing`, `Scene`; loads a `geometry.toml` |
| `docs/diagrams/views.py` | `View`, `Sequence`; loads and validates a `views.toml` against a scene |
| `docs/diagrams/frame.py` | Face and turn transform, crop frame, visible fraction, inset placement |
| `docs/diagrams/draw.py` | Draws a view's render layer on a `Sheet`: outline, items, muting, pin 1 marker, labels, inset |
| `docs/diagrams/build.py` | Command: every view to SVG (in memory), PNG pair, `views.json`; `--check` |
| `docs/diagrams/test_*.py` | One test file per module above |
| `docs/wiring/acorn/sheetlib.py`, `palette.py` | Become re-exports of the moved code |
| `docs/wiring/acorn/geometry.toml` | The Acorn card and the HAT in millimetres, each table with its source |
| `docs/wiring/acorn/measure_card.py` | Measures the card photo: scale from the card's 22.00 mm width, checked against the sockets' 1.20 mm contact pitch; the two socket boxes |
| `docs/wiring/acorn/views.toml` | The views of family A |
| `docs/wiring/acorn/generated/views/` | `<id>.png`, `<id>-dark.png`, `views.json` |
| `.github/workflows/wiring.yml` | Lints and tests `docs/diagrams` too; runs `build.py --check` |

---

### Task 1: Lift the canvas and palette into `docs/diagrams/`

**Files:**
- Create: `docs/diagrams/__init__.py`, `docs/diagrams/canvas.py`, `docs/diagrams/errors.py`, `docs/diagrams/test_canvas.py`
- Move: `docs/wiring/acorn/palette.py` to `docs/diagrams/palette.py`; `docs/wiring/acorn/fonts/` to `docs/diagrams/fonts/`
- Modify: `docs/wiring/acorn/sheetlib.py`, `docs/wiring/acorn/palette.py` (re-exports), `docs/wiring/acorn/README.md` (the `fonts/` and `palette.py` rows), `.github/workflows/wiring.yml`

**Interfaces:**
- Produces: `diagrams.canvas.Sheet(w, h, photos=None)` with the methods `sheetlib.Sheet` has today (`width`, `add`, `rect`, `text`, `tag`, `photo`, `check`, `svg`, `dark_only`); `diagrams.canvas.FONTS`; `diagrams.palette` (all of today's names); `diagrams.errors.DiagramError(Exception)`.

- [ ] **Step 1: Write the failing test**

`docs/diagrams/test_canvas.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from diagrams import palette
from diagrams.canvas import Sheet


def test_a_sheet_measures_the_text_it_draws():
    sh = Sheet(200, 100)
    assert sh.text(20, 40, "pin 1", 12, "bold") == sh.width("pin 1", 12, "bold") > 0


def test_text_leaving_the_canvas_stops_the_build():
    sh = Sheet(60, 40)
    sh.text(20, 30, "far too long for it", 12)
    with pytest.raises(SystemExit, match="leaves the canvas"):
        sh.check("t")


def test_a_photo_without_a_photo_directory_is_refused():
    with pytest.raises(ValueError, match="no photo directory"):
        Sheet(100, 100).photo("x.jpg", 0, 0, 50)


def test_light_and_dark_differ_only_in_colour():
    sh = Sheet(200, 100)
    sh.text(20, 40, "pin 1", 12)
    light, dark = (palette.resolve(sh.svg(), t) for t in palette.THEMES)
    assert light != dark and len(light) == len(dark)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --no-project --python 3.12 --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/diagrams -q`
Expected: collection error, `No module named 'diagrams'`.

- [ ] **Step 3: Move the code**

```bash
mkdir -p docs/diagrams && touch docs/diagrams/__init__.py
git mv docs/wiring/acorn/palette.py docs/diagrams/palette.py
git mv docs/wiring/acorn/fonts docs/diagrams/fonts
git mv docs/wiring/acorn/sheetlib.py docs/diagrams/canvas.py
```

Edit `docs/diagrams/canvas.py`:
- remove `import wiring`, and the names `OUT`, `W`, `H`, `SIGNALS`, `GREY`, `P1_PINS`, `P2_PINS`, `label_of` (they are the Acorn's and go back to `sheetlib.py` below);
- change `import palette` / `from palette import role, wire` to `from . import palette` / `from .palette import role`;
- `Sheet.__init__(self, w, h, photos=None)` stores `self.photos = photos` (no default size);
- in `Sheet.photo`, open `self.photos / name`, and before that: `if self.photos is None: raise ValueError("Sheet.photo: no photo directory given")`.

`docs/diagrams/errors.py`:

```python
# SPDX-License-Identifier: Apache-2.0
class DiagramError(Exception):
    """A model, a view or a drawing rule that does not hold: the build stops with this."""
```

New `docs/wiring/acorn/palette.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The palette is docs/diagrams/palette.py; this name is kept for the Acorn generator's imports."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from diagrams.palette import *  # noqa: E402, F403
from diagrams.palette import ROLES, WIRES, _tokens  # noqa: E402, F401
```

New `docs/wiring/acorn/sheetlib.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The Acorn sheets' canvas: docs/diagrams/canvas.py's Sheet at the sheets' size, with the Acorn's signals."""

import pathlib

import palette  # noqa: F401  (puts docs/ on the path)
import wiring
from diagrams import canvas
from diagrams.canvas import (  # noqa: F401
    BODY, BOX, FAINT, FONTS, GOLD, INK, LIGHT_SHORT, MUTED, ON_WIRE, PAPER, RED, TEXT_ON_PAPER, TEXT_SMALL,
)  # fmt: skip
from palette import wire

HERE = pathlib.Path(__file__).parent
OUT = HERE / "generated"
W, H = 1600, 900
GREY = wire("#9aa0a8")  # a wire that is cut back and is not VCC
SIGNALS = {k: (wire(v["colour"]), v.get("drive"), v["what"]) for k, v in wiring.SIGNALS.items() if k != "VCC"}
P1_PINS = wiring.CONNECTORS["P1"]["pins"]
P2_PINS = wiring.CONNECTORS["P2"]["pins"]


def label_of(sig):
    return wiring.SIGNALS[sig]["label"]


class Sheet(canvas.Sheet):
    def __init__(self, w=W, h=H):
        super().__init__(w, h, photos=HERE / "photos")
```

In `wiring.yml`, add `docs/diagrams` to both ruff lines and to the pytest line, and add `docs/diagrams/**` to the workflow's `paths` filters if it has them.

- [ ] **Step 4: Run everything**

Run the test command of Global Constraints, then `uv run --python 3.12 docs/wiring/acorn/gen.py --check`.
Expected: all tests pass (185 existing + 4 new); `generated/ is up to date`. If `--check` reports any SVG stale, the move changed output: find the difference with `git diff --stat` after `gen.py`, fix the move, and restore `generated/` with `git checkout HEAD -- docs/wiring/acorn/generated`.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --with ruff ruff check docs/diagrams docs/wiring/acorn
uv run --no-project --with ruff ruff format --check docs/diagrams docs/wiring/acorn
git add docs/diagrams docs/wiring/acorn .github/workflows/wiring.yml
git commit -m "diagrams: the canvas and palette move to docs/diagrams, the Acorn sheets unchanged"
```

---

### Task 2: The model and `geometry.toml` for the HAT

**Files:**
- Create: `docs/diagrams/model.py`, `docs/diagrams/test_model.py`, `docs/wiring/acorn/geometry.toml`
- Modify: `docs/wiring/acorn/measure_hat.py` (also returns millimetre figures), `docs/wiring/acorn/test_wiring.py` (one test)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Box:           # millimetres in the thing's frame: x right, y down, origin at the top left of its top face
    x0: float; y0: float; x1: float; y1: float
    def area(self) -> float
    def intersect(self, other: "Box") -> "Box | None"
    def union(self, other: "Box") -> "Box"
    def grow(self, margin: float) -> "Box"
    def contains(self, other: "Box", slack: float = 0.01) -> bool

@dataclass(frozen=True)
class Item:
    id: str            # "hat.header.pin.19"
    kind: str          # "board" | "header" | "pin" | "socket" | "contact" | "slot" | "standoff" | "hole" | "pad"
    face: str          # "top" | "bottom"
    box: Box
    label: str = ""    # as printed on the part; "" for none
    pin1: tuple[float, float] | None = None    # for a connector: the centre of its pin 1
    z: int = 0         # drawing order within the thing

@dataclass(frozen=True)
class Thing:
    key: str           # "hat"
    name: str          # "Waveshare PoE M.2 HAT+ (B)"
    size: tuple[float, float]      # width, height in mm
    items: dict[str, Item]         # by id, including the board itself as "<key>"
    photos: dict[str, dict]        # face -> {"file", "px_per_mm", "origin": [x, y]} where a photo exists

class Scene:
    things: dict[str, Thing]
    def item(self, item_id: str) -> Item        # DiagramError on an unknown id, naming the nearest ids
    def select(self, selector: str) -> list[Item]   # an id, or "hat.header.pins.19-26" for a pin range

def load(geometry_path: pathlib.Path) -> Scene
```

`geometry.toml` shape (the loader refuses a table without `source`, an item outside its thing, a `kind` or `face` not in the lists above, and a header whose pins do not fit its box):

```toml
[things.hat]
name = "Waveshare PoE M.2 HAT+ (B)"
size = [56.0, 85.0]        # from measure_hat.py: see source
source = "the maker's dimension drawing (wiring.toml [carriers.pi5.hat] drawing): 85.00 mm long, mounting holes 58.00 x 49.00 mm, 3.50 mm from the pin 1 end; measured in the photo by measure_hat.py"

[things.hat.photos.top]
file = "hat-plus-b-ccw.jpg"
px_per_mm = 8.177
origin = [0, 0]            # the photo pixel of the thing's (0, 0), from measure_hat.py

[things.hat.headers.header]
face = "top"
label = ""
columns = 2
rows = 20
numbering = "across"
pitch = 2.54
pin1 = [0.0, 0.0]          # from measure_hat.py
source = "Raspberry Pi 40-pin header, 2.54 mm; position measured in the photo by measure_hat.py"

[things.hat.items.m2-slot]
kind = "slot"
face = "top"
box = [0, 0, 0, 0]         # from measure_hat.py
source = "measured in the photo by measure_hat.py (the grey socket moulding)"
```

The zeros shown above are **not** to be committed: Step 3 replaces every one with the figure `measure_hat.py --mm` prints, and the test of Step 1 fails while they differ.

- [ ] **Step 1: Write the failing tests**

`docs/diagrams/test_model.py`:

```python
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
    assert pin2.box.x0 - pin1.box.x0 == pytest.approx(2.54)       # across: 2 is beside 1
    assert pin40.box.y0 - pin2.box.y0 == pytest.approx(19 * 2.54)  # 20 rows down


def test_a_pin_range_selects_those_pins():
    scene = model.load(GEOMETRY)
    assert [i.id.rsplit(".", 1)[1] for i in scene.select("hat.header.pins.19-26")] == [str(n) for n in range(19, 27)]


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
```

Add to `docs/wiring/acorn/test_wiring.py`:

```python
def test_the_hat_in_geometry_toml_is_what_measure_hat_measures():
    import tomllib

    hat = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["hat"]
    got = measure_hat.measure_mm(HERE / "photos" / wiring.CARRIERS["pi5"].hat.photo)
    assert hat["size"] == got["size"]
    assert hat["photos"]["top"]["px_per_mm"] == got["px_per_mm"] and hat["photos"]["top"]["origin"] == got["origin"]
    assert hat["headers"]["header"]["pin1"] == got["pin1"]
    assert hat["items"]["m2-slot"]["box"] == got["m2_slot"]
```

(`HERE`, `measure_hat` and `wiring` are already imported in that file; if `measure_hat` is imported under another name there, use that name.)

- [ ] **Step 2: Run to see them fail**

Run: the test command, `-q docs/diagrams/test_model.py docs/wiring/acorn/test_wiring.py`
Expected: `No module named 'diagrams.model'`; `measure_hat has no attribute measure_mm`.

- [ ] **Step 3: `measure_hat.measure_mm` and the figures**

In `measure_hat.py`, have `measure()` also return the raw values it already computes (`"board_px": (left, top, right, bottom)` where `left` is found as `right` is, scanning from x = 0 along the row `round(row0)`), and add:

```python
def measure_mm(path):
    """The HAT in millimetres, origin at the top left corner of the board in the photo: what geometry.toml holds."""
    m = measure(path)
    s = m["scale_px_per_mm"]
    left, top, right, bottom = m["board_px"]

    def mm(px, origin):
        return round((px - origin) / s, 2)

    x0, y0, x1, y1 = m["m2_slot"]
    return {
        "size": [mm(right, left), mm(bottom, top)],
        "px_per_mm": s,
        "origin": [left, top],
        "pin1": [mm(m["columns"][0], left), mm(m["row"], top)],
        "m2_slot": [mm(x0, left), mm(y0, top), mm(x1, left), mm(y1, top)],
    }
```

and a `--mm` flag in `main` that prints `measure_mm()`'s values one per line as `key = value`. Run `uv run docs/wiring/acorn/measure_hat.py --mm` and write the printed figures into `geometry.toml` in place of the zeros. `measure_hat.py --check` must still pass (`board_px` is not in `STORED`).

- [ ] **Step 4: Write `model.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""The things a diagram can show and where their parts are, in millimetres, loaded from a geometry.toml.

Every table of the file names its source. Nothing here supplies a figure the file lacks."""

import difflib
import pathlib
import re
import tomllib
from dataclasses import dataclass

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
            other.x0 >= self.x0 - slack and other.y0 >= self.y0 - slack
            and other.x1 <= self.x1 + slack and other.y1 <= self.y1 + slack
        )  # fmt: skip


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


def _item(thing_key, size, item_id, kind, face, box, label="", pin1=None, z=0):
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
    items[hid] = _item(thing_key, size, hid, "header", raw["face"], body, raw.get("label", ""), (x1, y1), z=1)
    for r in range(rows):
        for c in range(cols):
            n = (r * cols + c if raw["numbering"] == "across" else c * rows + r) + 1
            cx, cy = x1 + c * pitch, y1 + r * pitch
            pid = f"{hid}.pin.{n}"
            box = Box(cx - PAD / 2, cy - PAD / 2, cx + PAD / 2, cy + PAD / 2)
            items[pid] = _item(thing_key, size, pid, "pin", raw["face"], box, str(n), z=2)
    return items


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
                key, size, iid, it["kind"], it["face"], Box(*it["box"]), it.get("label", ""), pin1, it.get("z", 1)
            )
        for face, photo in raw.get("photos", {}).items():
            if face not in FACES or set(photo) != {"file", "px_per_mm", "origin"}:
                raise DiagramError(f"geometry: {key}: photo {face!r} needs file, px_per_mm and origin, on top or bottom")
        things[key] = Thing(key, raw["name"], size, items, raw.get("photos", {}))
    if not things:
        raise DiagramError(f"geometry: {geometry_path}: no things")
    return Scene(things)
```

- [ ] **Step 5: Run the tests, lint, `gen.py --check`, commit**

Expected: all pass. Commit `docs/diagrams/model.py docs/diagrams/test_model.py docs/wiring/acorn/geometry.toml docs/wiring/acorn/measure_hat.py docs/wiring/acorn/test_wiring.py` as `diagrams: the model, and the HAT's geometry in millimetres from its drawing`.

---

### Task 3: Views and sequences

**Files:**
- Create: `docs/diagrams/views.py`, `docs/diagrams/test_views.py`, `docs/wiring/acorn/views.toml`

**Interfaces:**
- Consumes: `model.Scene.select`, `model.Scene.item`, `DiagramError`.
- Produces:

```python
@dataclass(frozen=True)
class View:
    id: str
    thing: str                 # the thing shown (family A: one thing per view)
    face: str                  # "top" | "bottom"
    turn: int                  # 0, 90, 180, 270: clockwise, as the reader sees it
    crop: tuple[str, ...]      # selectors; () = the whole thing
    highlight: tuple[str, ...] # selectors; () = nothing muted
    callouts: dict[str, int]   # selector -> number
    sequence: str | None
    width: int                 # the picture's width in px: 700 unless the view says otherwise

def load(views_path: pathlib.Path, scene: Scene) -> dict[str, View]     # in file order
def file_stem(view_id: str) -> str                                       # the id, as its file name
```

Family A's fields only. `state`, `motion`, `wiring` and `layer` are added by families B to D; until then the loader refuses them as unknown keys.

- [ ] **Step 1: Write the failing tests**

`docs/diagrams/test_views.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from diagrams import model, views
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
SCENE = model.load(ACORN / "geometry.toml")


def load(tmp_path, text):
    path = tmp_path / "views.toml"
    path.write_text(text)
    return views.load(path, SCENE)


def test_the_committed_views_load():
    assert "pi5-hat.top" in views.load(ACORN / "views.toml", SCENE)


def test_defaults(tmp_path):
    v = load(tmp_path, '[views."a.b"]\nthing = "hat"\nface = "top"\n')["a.b"]
    assert (v.turn, v.crop, v.highlight, v.callouts, v.sequence, v.width) == (0, (), (), {}, None, 700)


@pytest.mark.parametrize(
    "body, message",
    [
        ('thing = "hta"\nface = "top"\n', "no thing 'hta'"),
        ('thing = "hat"\nface = "side"\n', "face"),
        ('thing = "hat"\nface = "top"\nturn = 45\n', "turn"),
        ('thing = "hat"\nface = "top"\ncrop = ["hat.m2-slto"]\n', "hat.m2-slot"),
        ('thing = "hat"\nface = "top"\nhighlight = ["hat.m2-slot"]\ncrop = ["hat.header.pins.19-26"]\n', "outside"),
        ('thing = "hat"\nface = "top"\ntitle = "The HAT"\n', "unknown key"),
        ('thing = "hat"\nface = "bottom"\ncrop = ["hat.m2-slot"]\n', "not on the face shown"),
    ],
)
def test_a_bad_view_is_refused(tmp_path, body, message):
    with pytest.raises(DiagramError, match=message):
        load(tmp_path, f'[views."a.b"]\n{body}')


def test_an_upper_case_id_is_refused_so_two_ids_never_share_a_file(tmp_path):
    text = '[views."a.b"]\nthing = "hat"\nface = "top"\n[views."A.b"]\nthing = "hat"\nface = "top"\n'
    with pytest.raises(DiagramError, match="id"):
        load(tmp_path, text)


def test_an_id_must_be_lower_case_words_joined_by_dots_and_hyphens(tmp_path):
    with pytest.raises(DiagramError, match="id"):
        load(tmp_path, '[views."a b"]\nthing = "hat"\nface = "top"\n')


def test_a_sequence_gives_its_views_their_viewpoint_and_allows_one_change(tmp_path):
    head = '[sequences.s]\nthing = "hat"\nface = "top"\nturn = 0\n'
    one = head + '[views."s.1"]\nsequence = "s"\n[views."s.2"]\nsequence = "s"\nturn = 90\n[views."s.3"]\nsequence = "s"\nturn = 90\n'
    got = load(tmp_path, one)
    assert [v.turn for v in got.values()] == [0, 90, 90]
    two = one + '[views."s.4"]\nsequence = "s"\nturn = 0\n'
    with pytest.raises(DiagramError, match="changes its viewpoint twice"):
        load(tmp_path, two)
```

Note the highlight test: a highlighted item must lie inside the crop's items' union grown by the crop margin (`frame.MARGIN`, Task 4, 3 mm); the M.2 slot is far from pins 19 to 26.

- [ ] **Step 2: Run to see them fail** (`No module named 'diagrams.views'`).

- [ ] **Step 3: Write `views.toml` (family A's views) and `views.py`**

`docs/wiring/acorn/views.toml`:

```toml
# SPDX-License-Identifier: Apache-2.0
# The views of the Acorn pages. A table's name is the id a page references: never rename one a page uses.
# Fields: docs/superpowers/specs/2026-10-10-diagram-views-design.md.

[views."pi5-hat.top"]
thing = "hat"
face = "top"

[views."pi5-hat.top.header"]
thing = "hat"
face = "top"
highlight = ["hat.header"]

[views."pi5-hat.top.m2-slot"]
thing = "hat"
face = "top"
crop = ["hat.m2-slot"]
highlight = ["hat.m2-slot"]

[views."pi5-hat.top.pins-19-26"]
thing = "hat"
face = "top"
crop = ["hat.header.pins.19-26"]
highlight = ["hat.header.pins.19-26"]

[views."pi5-hat.top.pins-5-10"]
thing = "hat"
face = "top"
crop = ["hat.header.pins.5-10"]
highlight = ["hat.header.pins.5-10"]
```

`docs/diagrams/views.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The views a views.toml declares, checked against the model: a view that cannot be drawn is refused here."""

import pathlib
import re
import tomllib
from dataclasses import dataclass

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
        view_id, merged["thing"], merged["face"], merged.get("turn", 0), tuple(raw.get("crop", ())),
        tuple(raw.get("highlight", ())), dict(raw.get("callouts", {})), seq, raw.get("width", 700),
    )  # fmt: skip
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
```

The `ID` pattern refuses upper case, which is what keeps two ids from sharing a file on a file system that folds case; the `stems` check stays for the day `file_stem` maps ids less directly.

- [ ] **Step 4: Run the tests, lint, commit** as `diagrams: views and sequences, checked against the model`.

---

### Task 4: Frame arithmetic

**Files:**
- Create: `docs/diagrams/frame.py`, `docs/diagrams/test_frame.py`

**Interfaces:**
- Consumes: `model.Box`, `model.Scene`, `views.View`, `views.crop_box`.
- Produces:

```python
@dataclass(frozen=True)
class Frame:
    box: Box            # the part of the thing shown, in the thing's own frame (mm)
    size: tuple[float, float]   # the thing's size
    face: str
    turn: int
    scale: float        # px per mm
    origin: tuple[float, float]  # where the frame's top left is drawn, px
    def to_px(self, x: float, y: float) -> tuple[float, float]   # a point of the thing -> canvas px
    def box_px(self, box: Box) -> tuple[float, float, float, float]  # x0, y0, x1, y1 on the canvas, x0 < x1, y0 < y1
    @property
    def px_size(self) -> tuple[float, float]                     # the drawn frame's width and height

def view_frame(scene, view, origin=(0.0, 0.0), width_px=None) -> Frame
def visible_fraction(item_box: Box, frame_box: Box, covers: list[Box]) -> float
```

The transform: on the bottom face the thing is seen turned over about its long (y) axis, so x becomes `width - x`; then the picture is turned clockwise by `turn`. `visible_fraction` is the share of `item_box` inside `frame_box` and not under any box of `covers` (covers are rasterised on a 0.1 mm grid: exact enough against the 0.5 and 0.1 thresholds, and simple).

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from diagrams import frame
from diagrams.model import Box


def make(turn=0, face="top", box=Box(0, 0, 10, 20), scale=2.0):
    return frame.Frame(box, (10.0, 20.0), face, turn, scale, (0.0, 0.0))


def test_no_turn_maps_millimetres_to_pixels():
    assert make().to_px(1, 2) == (2.0, 4.0) and make().px_size == (20.0, 40.0)


def test_a_quarter_turn_clockwise_puts_the_top_left_corner_at_the_top_right():
    f = make(turn=90)
    assert f.px_size == (40.0, 20.0)
    assert f.to_px(0, 0) == pytest.approx((40.0, 0.0))
    assert f.to_px(10, 20) == pytest.approx((0.0, 20.0))


def test_half_a_turn_and_three_quarters():
    assert make(turn=180).to_px(0, 0) == pytest.approx((20.0, 40.0))
    assert make(turn=270).to_px(0, 0) == pytest.approx((0.0, 20.0))


def test_the_bottom_face_is_mirrored_left_to_right():
    assert make(face="bottom").to_px(1, 2) == pytest.approx((18.0, 4.0))


def test_a_box_stays_a_box_whatever_the_turn():
    for turn in (0, 90, 180, 270):
        x0, y0, x1, y1 = make(turn=turn).box_px(Box(1, 2, 3, 5))
        assert x0 < x1 and y0 < y1 and (x1 - x0) * (y1 - y0) == pytest.approx(2 * 3 * 4)


def test_a_cropped_frame_draws_only_its_box():
    f = make(box=Box(2, 4, 6, 10))
    assert f.px_size == (8.0, 12.0) and f.to_px(2, 4) == (0.0, 0.0)


def test_visible_fraction():
    item = Box(0, 0, 10, 10)
    assert frame.visible_fraction(item, Box(0, 0, 20, 20), []) == pytest.approx(1.0)
    assert frame.visible_fraction(item, Box(5, 0, 20, 20), []) == pytest.approx(0.5, abs=0.02)
    assert frame.visible_fraction(item, Box(0, 0, 20, 20), [Box(0, 0, 10, 4)]) == pytest.approx(0.6, abs=0.02)
    assert frame.visible_fraction(item, Box(50, 50, 60, 60), []) == 0.0
```

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Write `frame.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Where a point of a thing lands in a picture, for a face, a turn and a crop; and how much of an item shows."""

from dataclasses import dataclass

from . import views
from .model import Box

GRID = 0.1  # mm: the grid visible_fraction counts on


@dataclass(frozen=True)
class Frame:
    box: Box
    size: tuple
    face: str
    turn: int
    scale: float
    origin: tuple

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
            if frame_box.x0 <= x <= frame_box.x1 and frame_box.y0 <= y <= frame_box.y1:
                if not any(c.x0 <= x <= c.x1 and c.y0 <= y <= c.y1 for c in covers):
                    seen += 1
    return seen / (nx * ny)
```

- [ ] **Step 4: Run the tests** (the 90 and 270 expectations pin the transform: if one fails, fix the mapping, not the test: clockwise as the reader sees it). **Lint, commit** as `diagrams: the frame of a view: face, turn, crop, and what shows`.

---

### Task 5: The card: `measure_card.py` and the Acorn's geometry

**Files:**
- Create: `docs/wiring/acorn/measure_card.py`, `docs/wiring/acorn/test_card.py`
- Modify: `docs/wiring/acorn/geometry.toml` (the `acorn` thing), `docs/wiring/acorn/README.md` (one row)

**Interfaces:**
- Produces: `measure_card.measure_mm(path) -> {"px_per_mm", "origin", "length_shown", "p1": [x0, y0, x1, y1], "p2": [...], "p1_pin1": [x, y], "p2_pin1": [x, y], "pad": [...], "contact_pitch_mm": {"P1": float, "P2": float}}` in the card's bottom-face frame; `geometry.toml` gains `things.acorn` with items `acorn.p1`, `acorn.p2` (`kind = "socket"`, `face = "bottom"`, `pin1`) and `acorn.pad` (`kind = "pad"`).

What is known and from where: the card is 22 × 80 mm (wiring.toml's source: the board maker's repository). `photos/acorn-cw.jpg` (522 × 1100 px) shows the end of the card away from the M.2 edge, underside up, the sockets on its left edge. Pixel boxes today: `gen.ACORN_CW` (P1, P2) and `steps.ACORN_PAD`.

The scale must be measured, not assumed:
1. Find the card's two long edges along several rows clear of the sockets (the board is dark; the photo's background is paper-coloured, as `Sheet.photo` already relies on). Their distance in px is 22.00 mm: that gives px/mm.
2. Independent check: in each socket, find the six bright contacts and fit their pitch (as `measure_hat.py` fits header pads, with `fit_line`). At the scale from 1, the pitch must be 1.20 mm within 5 %. If it is not, the script stops: the photo is not square-on or the edges were misread.
3. The socket boxes and the pad box, from the same blobs, replace `ACORN_CW` and `ACORN_PAD` as the source; `test_card.py` holds `gen.ACORN_CW` and `steps.ACORN_PAD` to the measured boxes within 3 px until family B removes those constants.
4. Pin 1 of each socket is the contact nearest the M.2 edge (wiring.toml's first source line); in this photo the M.2 edge is at the bottom, so pin 1 is the contact with the largest y.

The photo shows only part of the card's length: `length_shown` is its height in mm, and the thing's frame has its origin at the far-end corner so every item's y is measured from the end the photo shows. `geometry.toml` records `size = [22.0, 80.0]` with the source, and a `shown = [0, <length_shown>]` range on the photo; an item or a crop beyond `shown` on the bottom face has no geometry and cannot be declared (there is nothing to declare it from).

- [ ] **Step 1: Write the failing test**

`docs/wiring/acorn/test_card.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pathlib
import tomllib

import gen
import measure_card
import pytest
import steps

HERE = pathlib.Path(__file__).parent
GOT = measure_card.measure_mm(HERE / "photos" / "acorn-cw.jpg")


def test_the_contacts_of_both_sockets_are_1_2_mm_apart_at_the_scale_the_cards_width_gives():
    for name in ("P1", "P2"):
        assert GOT["contact_pitch_mm"][name] == pytest.approx(1.20, rel=0.05)


def test_geometry_toml_has_what_the_photo_measures():
    acorn = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]
    assert acorn["photos"]["bottom"]["px_per_mm"] == GOT["px_per_mm"]
    assert acorn["photos"]["bottom"]["origin"] == GOT["origin"]
    for key in ("p1", "p2", "pad"):
        assert acorn["items"][key]["box"] == GOT[key]
    assert acorn["items"]["p1"]["pin1"] == GOT["p1_pin1"] and acorn["items"]["p2"]["pin1"] == GOT["p2_pin1"]


def test_the_old_pixel_boxes_agree_with_the_measured_ones():
    px = measure_card.measure(HERE / "photos" / "acorn-cw.jpg")
    for name in ("P1", "P2"):
        assert gen.ACORN_CW[name] == pytest.approx(px["sockets"][name], abs=3)
    assert steps.ACORN_PAD == pytest.approx(px["pad"], abs=3)


def test_pin_1_is_at_the_end_of_each_socket_nearest_the_m2_edge():
    acorn = tomllib.loads((HERE / "geometry.toml").read_text())["things"]["acorn"]["items"]
    for key in ("p1", "p2"):
        x0, y0, x1, y1 = acorn[key]["box"]
        assert acorn[key]["pin1"][1] > (y0 + y1) / 2  # the M.2 edge is at the larger y in this frame
```

- [ ] **Step 2: Run to see it fail** (`No module named 'measure_card'`).

- [ ] **Step 3: Write `measure_card.py`** on `measure_hat.py`'s pattern (same script header and pins; `blobs`, `centre` and `fit_line` imported from `measure_hat`): `measure(path)` returns pixel values (`scale_px_per_mm`, `edges`, `sockets`, `contacts`, `pad`), raising `SystemExit` with the reason when the edges are not found on at least 20 rows agreeing within 2 px, when a socket does not show six contacts, or when the pitch check of point 2 fails; `measure_mm(path)` converts as `measure_hat.measure_mm` does, mirroring x for the bottom face (`x_mm = 22.0 - (px - left) / scale`, because the photo shows the underside); `main` prints the values and supports `--check` against `geometry.toml`.

If the script cannot establish the scale (edges not found, or the pitch check fails by more than 5 %), **stop the task and report the measured numbers**: do not widen the tolerance and do not enter figures by eye.

- [ ] **Step 4: Run `uv run docs/wiring/acorn/measure_card.py`, write its figures into `geometry.toml`:**

```toml
[things.acorn]
name = "SQRL Acorn"
size = [22.0, 80.0]
source = "22 x 80 mm, M.2 2280: the board maker's repository (wiring.toml [[sources]], \"The card's form\")"

[things.acorn.photos.bottom]
file = "acorn-cw.jpg"
px_per_mm = 0.0      # measure_card.py
origin = [0, 0]      # measure_card.py

[things.acorn.items.p1]
kind = "socket"
face = "bottom"
label = "P1"
box = [0, 0, 0, 0]   # measure_card.py
pin1 = [0, 0]        # measure_card.py
source = "measured in the vendor's underside photo by measure_card.py; scale from the card's 22.00 mm width, checked against the contacts' 1.20 mm pitch"
```

(and `p2`, `pad` likewise; every zero replaced by the printed figure, as in Task 2.) If `model.load` needs the photo's `shown` range, add it to the photo table's allowed keys in `model.py` with a test in `test_model.py` that a bottom-face item beyond `shown` is refused with `outside the photographed part`.

- [ ] **Step 5: Run all tests, lint, `gen.py --check`, commit** as `diagrams: the Acorn's sockets in millimetres, measured in the vendor's photo`.

---

### Task 6: Drawing a view

**Files:**
- Create: `docs/diagrams/draw.py`, `docs/diagrams/test_draw.py`
- Modify: `docs/diagrams/palette.py` (roles for the render layer), `docs/wiring/acorn/test_palette.py` only if it lists roles exhaustively
- Modify: `docs/wiring/acorn/views.toml` (the Acorn's views)

**Interfaces:**
- Consumes: `canvas.Sheet`, `frame.view_frame`, `frame.visible_fraction`, `model`, `views.View`, `palette.role`.
- Produces: `draw.render(scene, view) -> tuple[str, dict]`: the drawing with colour tokens (for `palette.resolve`), and facts for the manifest and the tests: `{"size": [w, h], "items": [ids drawn], "highlight": [ids], "muted": [ids], "inset": bool, "labels": [texts], "pin1": [ids whose pin 1 marker is drawn], "frame_mm": [x0, y0, x1, y1] (the frame in the thing's millimetres, after it has grown for pin 1)}`.

What is drawn, in order, on a `Sheet` exactly as large as the frame plus a 12 px border (a label may use the border; nothing else does):
1. The board: its outline over the frame (rounded where the frame reaches a board corner), filled `render-board`.
2. Every item of the thing on the face shown whose box meets the frame, by `z`: a header as a `body` rectangle; a pin as a `gold` square with, when the pitch is at least 22 px on the canvas, its number inside (`on-gold`); a socket or slot as a `render-part` rectangle with `render-part-edge`; a standoff, hole or pad as a circle of its box.
3. Muting: when the view has a highlight set, every item not in it and not the board is drawn with its `-muted` role (`render-part-muted`, `gold-muted`, `body-muted`), and no pin number; highlighted items get the existing `mark` outline (`gen.highlight`'s two strokes: `mark-edge` 5.5 px under `mark` 3 px).
4. Pin 1: for each highlighted connector (header, socket) and for each connector in a whole-thing view, a filled triangle at its `pin1` point pointing at the pin, and the label `1` beside it. If the marker would fall outside the frame, the frame is first grown to hold `pin1` (a crop to pins 19 to 26 therefore does **not** grow to pin 1: pin 1 of the header is then shown on the inset instead, and the range's own first pin carries its number: this is the case the spec's rule covers by "a connector in the highlight set"; a pin range is not a connector).
5. Labels: an item's `label`, where it has one and the item is highlighted or the view is whole-thing, as a `box` tag beside the item on the side with most free room; callout numbers as `body` discs with `on-body` numerals. More than four words in a label raises `DiagramError`.
6. Inset: when `view.crop` is set, the whole thing at 110 px on its longer side, same face and turn, in the corner of the frame farthest from the highlighted items' centre, on a `box` rectangle with an `ink` edge; the frame's box marked on it with the `mark` outline; pin 1 of each connector of the thing drawn on it. If the inset would cover more than a tenth of any highlighted item, try the other three corners in order; if all four do, raise `DiagramError(f"view {id}: no corner has room for the inset")`.
7. `sheet.check(view.id)` (overlap, overflow, contrast), re-raised as `DiagramError`.

Rules checked before drawing, each raising `DiagramError(f"view {view.id}: ...")`:
- a highlighted item with `visible_fraction < 0.5` in the frame ("less than half of hat.m2-slot shows");
- (family B adds the one-tenth rule for earlier parts and the attachment rule; they need states.)

New palette roles (light, dark, what), chosen to reach the canvas's contrast checks; the dark values are verified by `palette.contrast` in `test_draw.py`, not by eye:

```python
"render-board": ("#2f5d4a", "#27493c", "a board in the render layer"),
"render-part": ("#c9ced6", "#8d96a3", "a socket, a slot, a standoff in the render layer"),
"render-part-edge": ("#15181d", "#e3e6ea", "its outline"),
"render-part-muted": ("#55756a", "#3b5a4f", "the same, muted: near the board's colour"),
"gold-muted": ("#7d7a52", "#6d6a4a", "a pin, muted"),
"body-muted": ("#2a4a3e", "#223c33", "a header's body, muted"),
```

- [ ] **Step 1: Write the failing tests**

`docs/diagrams/test_draw.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from diagrams import draw, model, palette, views
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
SCENE = model.load(ACORN / "geometry.toml")
VIEWS = views.load(ACORN / "views.toml", SCENE)


def facts(view_id):
    return draw.render(SCENE, VIEWS[view_id])[1]


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


def test_the_picture_is_as_wide_as_the_view_asks_plus_its_border():
    assert facts("pi5-hat.top")["size"][0] == 700 + 2 * draw.BORDER


def test_a_label_of_more_than_four_words_is_refused():
    long = dataclasses.replace(SCENE.item("hat.m2-slot"), label="the slot the card goes in")
    scene = model.Scene({**SCENE.things, "hat": dataclasses.replace(
        SCENE.things["hat"], items={**SCENE.things["hat"].items, "hat.m2-slot": long})})
    with pytest.raises(DiagramError, match="more than four words"):
        draw.render(scene, VIEWS["pi5-hat.top.m2-slot"])


def test_a_view_too_small_for_its_inset_is_refused():
    tiny = dataclasses.replace(VIEWS["pi5-hat.top.pins-19-26"], width=120)
    with pytest.raises(DiagramError, match="inset|leaves|overlaps"):
        draw.render(SCENE, tiny)


def test_the_two_themes_differ_only_in_colour():
    svg, _ = draw.render(SCENE, VIEWS["pi5-hat.top.header"])
    light, dark = (palette.resolve(svg, t) for t in palette.THEMES)
    strip = lambda s: __import__("re").sub(r"#[0-9a-fA-F]{3,6}", "#", s)  # noqa: E731
    assert strip(light) == strip(dark) and light != dark


def test_muted_and_full_parts_can_be_told_apart_on_both_themes():
    for theme in palette.THEMES:
        full, muted = (palette.value(palette.role(r), theme) for r in ("render-part", "render-part-muted"))
        assert palette.contrast(full, muted) >= 2.0
        assert palette.contrast(full, palette.value(palette.role("render-board"), theme)) >= 3.0
```

Add to `views.toml`:

```toml
[views."acorn.bottom.sockets"]
thing = "acorn"
face = "bottom"
turn = 270
crop = ["acorn.p1", "acorn.p2", "acorn.pad"]

[views."acorn.bottom.p1"]
thing = "acorn"
face = "bottom"
turn = 270
crop = ["acorn.p1"]
highlight = ["acorn.p1"]

[views."acorn.bottom.p2"]
thing = "acorn"
face = "bottom"
turn = 270
crop = ["acorn.p2"]
highlight = ["acorn.p2"]
```

`turn = 270` is to be confirmed in Step 4 by looking: the picture must show the card as `gen.acorn_photo_down` shows it today (sockets along the top, M.2 edge to the left, pin 1 of each socket at its left end), which is how the reader holds it. If 270 gives the mirror or the opposite turn, the transform of Task 4 is right by its tests and the value here changes to the one that matches; record which in the commit message.

Because only part of the card's underside has geometry, `acorn.bottom.sockets` is a crop (with an inset of the card's 22 × 80 outline, the photographed part's items on it) and there is no whole-underside view in this family.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Write `draw.py`** to the numbered description above. Structure: `BORDER = 12`; `render(scene, view)` computes the frame box (`views.crop_box`, grown by pin 1 points per rule 4), runs the visibility rule, makes `Frame` with `origin=(BORDER, BORDER)`, creates `Sheet(w, h)`, calls `_board`, `_items`, `_pin1`, `_labels`, `_inset` (each a function of `(sh, frame, scene, view, facts)` appending to `facts`), then `sh.check` inside `try/except SystemExit as e: raise DiagramError(str(e)) from None`. `_inset` builds a second `Frame` for the whole thing and reuses `_board`, `_items(muted=all)` and `_pin1` with it: the inset is the same drawing code at another scale, never a separate picture. Every colour comes from `palette.role`. Group each drawn item as `<g id="{item.id}">…</g>` so a test (and later the page's check) can find it.

- [ ] **Step 4: Run the tests; then look.** Write each view's light and dark SVG to `./tmp/views/` with a ten-line script run by `uv run` (resolve with `palette.resolve`), render them with headless Chrome as `render.py` does, and open the PNGs beside `photos/hat-plus-b-ccw.jpg` and `generated/acorn-card-underside.png`. Check by eye, for each view: every drawn part sits where the photo has it; pin 1 is at the right end; the highlighted part is the obvious thing in the picture in both themes; the inset is readable and its frame mark is on the right place; no label touches a part it does not name. Fix what is wrong in `draw.py` (or the palette values), re-run the tests. Remove `./tmp/`.

- [ ] **Step 5: Lint, `gen.py --check`, commit** as `diagrams: a view drawn: board, parts, highlight, pin 1, labels and the inset`.

---

### Task 7: The build command, the manifest and the stale check

**Files:**
- Create: `docs/diagrams/build.py`, `docs/diagrams/test_build.py`
- Modify: `.github/workflows/wiring.yml` (a `build.py --check` step), `docs/wiring/acorn/README.md` (a "Views" section: what `geometry.toml`, `views.toml` and `generated/views/` are and the two commands)

**Interfaces:**
- Consumes: `draw.render`, `views.load`, `views.file_stem`, `model.load`, `palette.resolve`, `palette.dark_name`.
- Produces: `build.build(board_dir) -> tuple[dict[str, str], dict]` (`{"<id>.svg": light, "<id>-dark.svg": dark}`, and the manifest); `build.stale(board_dir) -> list[str]`; the command `uv run docs/diagrams/build.py docs/wiring/acorn [--check]`.

`generated/views/views.json` (sorted keys, two-space indent, a trailing newline):

```json
{
  "views": {
    "pi5-hat.top.pins-19-26": {
      "light": "pi5-hat.top.pins-19-26.png",
      "dark": "pi5-hat.top.pins-19-26-dark.png",
      "size": [724, 380],
      "thing": "hat",
      "face": "top",
      "turn": 0,
      "sequence": null,
      "highlight": ["hat.header.pin.19", "…"],
      "inset": true,
      "photo_matched": false,
      "svg_sha256": {"light": "…", "dark": "…"}
    }
  }
}
```

`photo_matched` is `false` for every view in this family: matching a render to a photo of the same state is the page author's check, recorded here when it is done (a later family adds the field to `views.toml`).

Without `--check`: write the SVGs to `<board>/tmp-views/` (git-ignored; add the pattern to `.gitignore`), render each to PNG at 2x with headless Chrome exactly as `render.py` does (import its logic by moving the per-file part of `render.py` into a function `render_svg(svg_path, png_path)` in `docs/diagrams/chrome.py`, which `render.py` then calls: its output must not change, proved by `gen.py --check`), move the PNGs to `generated/views/`, write `views.json`, delete `tmp-views/` and any PNG in `generated/views/` that no view owns.

With `--check`: build in memory and fail (exit 1, one line per problem) if `views.json` is missing or differs from the manifest built now (which catches a changed drawing through `svg_sha256`), if a view's PNG is missing, or if a PNG is there that no view owns.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: Apache-2.0
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from diagrams import build

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"


def test_the_committed_views_are_up_to_date():
    assert build.stale(ACORN) == []


def test_the_manifest_lists_every_view_with_both_files():
    files, manifest = build.build(ACORN)
    for view_id, entry in manifest["views"].items():
        assert f"{view_id}.svg" in files and f"{view_id}-dark.svg" in files
        assert entry["light"] == f"{view_id}.png" and entry["dark"] == f"{view_id}-dark.png"
        assert entry["photo_matched"] is False and len(entry["svg_sha256"]["light"]) == 64


@pytest.fixture
def board(tmp_path):
    copy = tmp_path / "acorn"
    shutil.copytree(ACORN, copy, ignore=shutil.ignore_patterns("__pycache__", "*.svg", "acorn-*.png"))
    return copy


def test_a_changed_view_is_stale(board):
    text = (board / "views.toml").read_text().replace('highlight = ["hat.header"]', 'highlight = ["hat.m2-slot"]')
    (board / "views.toml").write_text(text)
    assert any("pi5-hat.top.header" in line for line in build.stale(board))


def test_a_removed_view_whose_png_is_still_there_is_stale(board):
    text = (board / "views.toml").read_text()
    start = text.index('[views."pi5-hat.top.m2-slot"]')
    end = text.index("[views.", start + 1)
    (board / "views.toml").write_text(text[:start] + text[end:])
    assert any("pi5-hat.top.m2-slot.png" in line and "no view" in line for line in build.stale(board))


def test_a_missing_png_is_stale(board):
    (board / "generated" / "views" / "pi5-hat.top.png").unlink()
    assert any("pi5-hat.top.png" in line and "missing" in line for line in build.stale(board))


def test_changed_geometry_is_stale(board):
    text = (board / "geometry.toml").read_text().replace("pitch = 2.54", "pitch = 2.50")
    (board / "geometry.toml").write_text(text)
    assert build.stale(board)


def test_the_manifest_is_stable_json(board):
    text = (board / "generated" / "views" / "views.json").read_text()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
```

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Write `chrome.py` and `build.py`**; change `render.py` to call `chrome.render_svg`. `build.py` has the `# /// script` header with the same pins as `gen.py` and puts `docs/` on `sys.path` as the test files do.

- [ ] **Step 4: Generate.** `uv run docs/diagrams/build.py docs/wiring/acorn`, then `uv run docs/diagrams/build.py docs/wiring/acorn --check` (expected: `views are up to date`), then the whole test command, `gen.py --check`, ruff.

- [ ] **Step 5: Commit** the code as `diagrams: build.py writes the views, their manifest, and checks they are current`; then the generated files as one or two commits of at most 15 files each (`diagrams: the first views of the HAT and the card, light and dark`).

---

### Task 8: Hold the render to the photo

**Files:**
- Create: `docs/diagrams/match.py`, `docs/diagrams/test_match.py`

**Interfaces:**
- Consumes: `model.Scene`, `Thing.photos`, Pillow.
- Produces: `match.overlay(scene, thing_key, face, photos_dir) -> PIL.Image` (the photo with every item's box outlined, for a person to look at); `match.item_px(thing, item) -> tuple` (an item's box in photo pixels); `match.contrast_inside(image, box_px) -> float` (the difference between the mean luminance inside an item's box and in a ring 1 mm wide round it).

The test that keeps render and photo together, per item kind: a header pin's box centre must be brighter than the board between pins (a pad); a socket's and the slot's box must differ from its ring by at least 12 luminance levels (a part is there); a pad's box must be brighter than its ring. A box drawn over empty board fails. Every item with a photo for its face is tested; an item kind with no such test fails the test run (`pytest.fail(f"no photo test for kind {kind}")`), so a new kind cannot slip past.

- [ ] **Step 1: Write the failing tests** (`test_match.py`: one parametrised test over every `(thing, item)` that has a photo for its face, dispatching on `kind` as above; one test that `overlay` returns an image of the photo's size; one test that moving the HAT header's `pin1` by 1.27 mm in a copied geometry makes the pin test fail).

- [ ] **Step 2: Run to see them fail. Step 3: Write `match.py`. Step 4: Run; write the two overlays to `./tmp/`, look at them, remove `./tmp/`.**

If an item fails because its geometry is off, fix the measuring script (Task 2 or 5), not the tolerance.

- [ ] **Step 5: Lint, commit** as `diagrams: every item's box is held to its feature in the photo`.

---

### Task 9: Whole-family verification

- [ ] **Step 1:** Run, from the worktree root, and read all of the output:

```bash
uv run --no-project --with ruff ruff check docs/diagrams docs/wiring/acorn
uv run --no-project --with ruff ruff format --check docs/diagrams docs/wiring/acorn
uv run --no-project --python 3.12 --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/diagrams docs/wiring/acorn
uv run --python 3.12 docs/wiring/acorn/gen.py --check
uv run --python 3.12 docs/diagrams/build.py docs/wiring/acorn --check
uv run docs/wiring/acorn/measure_hat.py --check
uv run docs/wiring/acorn/measure_card.py --check
git status --short
```

Expected: no lint finding; every test passes; `generated/ is up to date`; `views are up to date`; both measure checks pass; a clean tree.

- [ ] **Step 2:** Open every PNG in `generated/views/` (light and dark) and confirm the list of Task 6 Step 4 once more on the committed files.

- [ ] **Step 3:** Report to the session lead: the views drawn (ids), the test count, anything the plan said that turned out different, and every figure that could not be measured.

---

## What family A does not do

| Not here | Where |
|---|---|
| States, placements, the motion arrow, the one-tenth and attachment rules, the plugging-in sequence, results, wrong configurations, the three corrections to the fitting picture | Family B |
| Cable, plug and housing as things; wires and cavities as items from `wiring.toml`; the build view; assembly and verification steps | Family C |
| The as-laid view, the finished cable in place, the three-layer and variants figures, `figures.toml` and its slot check | Family D |
| The Compute Blade's geometry and views | Family E |
| The photo layer in a view (`layer = "photo"`) | Family B, when a state view first needs it; A's views are render-layer |
| The card's top face and the rest of its underside | No photo of either is in the repository. Finding one (the board maker's repository first) is a photo-list item; the views are added to `views.toml` in the family that is open when a photo with a usable licence is found |

Each of B to E gets its own plan, written when the family before it has merged, because each builds on interfaces that review may change.

## Measurements nobody has (for the project lead's list)

None blocks family A. Each blocks the view named.

| Figure | Blocks | Why it cannot come from a drawing |
|---|---|---|
| A photo of the Acorn's top face, and of its whole underside | The standard figures "whole board top" and "whole board bottom" (family D's slot check) | The repository has only the connector end of the underside |
| Which face of the card is up in the HAT's M.2 slot, and where its far end lies on the HAT (confirming that it reaches the standoff marked 2280) | Every view of the card in its slot (family B) | Derivable from the socket and standoff in the maker's drawing and the M-key, but no photo of a card in this HAT confirms it |
| Where the two half cables come out from under the fitted card, and how they lie to the header | The as-laid view and "the finished cable in place" (family D) | Only a photo of a fitted cable shows it |
| The length of a half cable | The reach in the as-laid view (family D) | Not measured on a cut cable |
| The outside size of the Pico-EZmate plug and of the Dupont housings | Plug and housing drawn to scale (families B and C) | To be taken from the makers' drawings (Molex's for the plug); if a drawing gives no outside size, a measurement with calipers |
| The height of the header's pins above the HAT with the stacking header fitted | Nothing from above; any side view | The maker's drawing does not say |
