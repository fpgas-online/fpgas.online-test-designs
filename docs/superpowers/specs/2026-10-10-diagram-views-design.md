# Diagram views: design

Date: 2026-10-10. Scope: phase 0 item 2 of the documentation plan. One model renders every diagram a page
needs as a named view. First user: the Acorn pages for a Raspberry Pi 5; the Compute Blade and the other
boards follow on the same engine.

## What exists today

`docs/wiring/acorn/` holds the only diagram generator.

| Part | What it is | What it lacks |
|---|---|---|
| `wiring.toml` | The electrical model: each socket's pin order, the signals, each carrier's headers by printed number, which wire lands on which pin, the housings, the resistor, lengths, parts, tools | No geometry except the HAT photo's pixel boxes |
| `gen.py`, `steps.py` | About 30 pictures, each drawn by its own function | Geometry is pixel constants spread through the code (`ACORN_CW`, `BLADE_BOARD`, `BLADE_HEADERS`, `M2_SLOT`, `USB_SHELL`, `ACORN_PAD`); nothing is addressable, so nothing can be cropped, highlighted or put in another state |
| The pictures | Photo-based sheets with titles, action text, warnings and assumption boxes drawn into them | A picture narrates itself; one picture serves several steps; a card is never shown in its slot, a plug never seated |
| `sheetlib.py`, `palette.py` | A canvas that measures its own text, fails the build on overlap, overflow and low contrast, and resolves colour tokens into a light and a dark drawing | Bound to the Acorn (`sheetlib` imports `wiring`) |
| `render.py`, `gen.py --check` | PNGs by headless Chrome; the build fails when `generated/` is stale | Nothing to change |
| The pages | Each picture is two Markdown images, one per theme | The pair is written by hand at every use; no ids |

The canvas, the palette, the photo tracer, the renderer and the stale check are sound and are kept.

## Approaches considered

1. **Parameters on the existing picture functions** (`cable(c, "P1", highlight=...)`). Cheapest. Fails the goal:
   every picture stays bespoke, crops and states are re-solved per function, other boards get nothing.
2. **Post-process the finished SVGs** (crop the viewBox, dim groups by id). Gives crop and highlight. Cannot
   give state (a seated plug is not in the drawing), orientation, or an inset; the baked-in words stay.
3. **A scene model and a view engine.** Items with ids and millimetre geometry; a view names a scene, a crop, a
   highlight set, a state and an orientation; the engine draws it. Recommended: it is the only one that gives
   state and orientation, and every later board is data, not code.

## The model

A new board-neutral package, `docs/diagrams/`. A board's data stays in the directory of the page set it
belongs to (`docs/wiring/acorn/`).

- **Object**: a physical thing with its own frame in millimetres, seen from above, with a top and a bottom
  face: the Acorn card, the HAT on its Pi, a Pico-EZmate half cable, a Dupont housing.
- **Item**: an addressable part of an object, with an id, a face, a box, and where it has one a pin 1 point
  and an attachment point. Ids are dotted paths: `acorn.p1`, `acorn.p1.pin.1`, `hat.header`,
  `hat.header.pin.19`, `hat.m2-slot`, `hat.standoff.2280`, `cable-p1.plug`, `cable-p1.wire.3`,
  `cable-p1.housing`, `cable-p1.housing.cavity.21`.
- **Placement**: where one object sits on another in a state: the card in the M.2 slot, a plug in a socket, a
  housing on header pins 19 to 26. A placement is a transform, so a view of the assembled host is composed,
  not drawn by hand.
- **Electrical data**: `wiring.toml`, unchanged. Pins, wires, cavities and their colours and labels are
  generated from it as items; nothing electrical is written twice.
- **Geometry data**: a new `geometry.toml` beside `wiring.toml`. Every figure in it names its source: the
  maker's drawing (the HAT, at the 8.177 px/mm `measure_hat.py` already establishes; the card's 22 × 80 mm;
  the plug's 1.2 mm pitch; 2.54 mm housings) or a photo measurement. The pixel constants now in `gen.py` and
  `steps.py` move here. A figure nobody has measured is not written down; the view that needs it fails.
- **Layers**: each object has a *render* layer (outline, holes, connectors, pin 1 markers, the silkscreen
  words a step refers to: drawn from the model, small, croppable, the same in any state) and, where a photo
  exists, a *photo* layer registered to the same frame. A test holds the two together: each item's box must
  lie on its feature in the photo within a tolerance, as `measure_hat.py --check` does for the HAT today.

## A view

Views are declared in `views.toml`, one table per view. The id is the table name and is what a page
references; it never changes once a page uses it.

```toml
[sequences."acorn-pi5.fit"]            # a run of step views: the viewpoint holds
scene = "pi5-hat"                      # the objects and their default placements
face = "top"
turn = 0                               # quarter turns; a sequence may change viewpoint once, declared

[views."acorn-pi5.fit.p1-aligned"]
sequence = "acorn-pi5.fit"
crop = ["hat.header.pins.19-26", "cable-p1.housing"]   # the frame is these items plus a margin
highlight = ["cable-p1.housing"]       # the part this step adds
state = { "cable-p1.housing" = "aligned" }
motion = ["cable-p1.housing", "hat.header.pins.19-26"]   # the arrow: what moves, onto what
```

| Field | Meaning | Default |
|---|---|---|
| `scene`, `face`, `turn` | What is in the picture and from where; from the sequence when the view is in one | required |
| `crop` | Items the frame must contain | the whole scene |
| `highlight` | Items drawn at full strength; everything else is muted | nothing muted |
| `state` | Per item: for a plug or housing `out`, `aligned`, `seated`; for the card `out`, `in-slot`, `screwed`; for a switch its position; and the wrong states (`turned`, `shifted` by rows, wires swapped) | each item's default |
| `motion` | An arrow from the moving item to its attachment point | none |
| `callouts` | Item to number, for a master picture whose numbers are the page's sections | none |
| `wiring` | `build` or `as-laid` (below) | none |
| `layer` | `render`, `photo` or `both` | `render` |

What a view cannot hold: a title, a sentence, a warning, a list of assumptions. Labels are the item's own
name as printed on the part, placed on the item by the engine. The step's words belong to the page.

### What the engine guarantees, and fails on

The build stops, naming the view and the rule, when:

- a highlighted item is not wholly inside the frame, or less than half of it is visible;
- an item placed in an earlier step of the sequence is less than a tenth visible;
- the attachment point of a `motion` is covered by the moving item;
- a connector in the highlight set has its pin 1 marker outside the frame;
- a cropped view has no room for its inset (every crop carries an inset of the whole object, in the same
  orientation, with the frame marked on it; a whole-object view carries none);
- a sequence changes `face` or `turn` more than once;
- a label holds more than four words, overlaps another, leaves the frame or is short of its contrast (the
  canvas's existing checks);
- a state names an item that has no such state, or an id that the model does not have.

### Theme

A view is drawn once with colour tokens and resolved to light and dark, as today. It is published as one
figure: the generator writes a manifest, `generated/views/views.json`, giving for each id its light and dark
files, pixel size, sequence and position, highlight set, and whether a photo of that state has been matched.
A page names the id and its alt text; one `view` directive turns that into a single figure holding both
images under the theme's `only-light` and `only-dark` classes, so no page writes a pair. Print takes the
light one. The directive's home (this repository, loaded by the docs build, or the docs repository) is the
docs lane's to settle; the manifest is the interface either way.

### Files

A view is committed as `generated/views/<id>.png` and `<id>-dark.png`. Its SVGs are not committed: the
manifest carries each SVG's hash, and `--check` fails when a regenerated view's hash differs or a PNG was
rendered from another hash. Render-layer views are a few tens of kilobytes; a photo-layer view is about half
a megabyte per theme, which is why `render` is the default.

## The wiring, two ways

- **Build view** (`wiring = "build"`): drawn for making the cable. The plug with its six numbered wires; the
  housing from the wire side with each wire's number in its cavity. A wire is drawn as a line only when it is
  in the highlight set, so a step view shows one wire going to one cavity and nothing crosses. The view says
  on its face that it is the build view.
- **As-laid view** (`wiring = "as-laid"`): drawn to match reality, for checking and debugging. The host from
  above, the card in its slot, the housings on the header, every wire end at its true position and in its
  true order, crossings shown. The path between the ends is drawn as the ribbon lies only once a photo of a
  fitted cable has been matched; until then the view is a line drawing and the photo is on the photo list.

## Template slots

`figures.toml` names, per board and per build guide, which view fills each slot.

- Standard figures per board: whole board top; whole board bottom; each connector with pin 1; the wiring as
  the ribbon lies; the three-layer programming figure; the variants side by side.
- The build-guide set: the finished cable in place; the cable and its internals; the connectors and every
  pin's function; assembly steps; verification steps; plugging-in steps; a result after each group of steps;
  wrong configurations.

A board or guide listed in `figures.toml` must fill every slot with views that exist: an empty slot stops the
build. A board is added to the file when its set is complete, so the file never holds a placeholder. The
three-layer figure is not a geometry view: it is a small diagram kind of its own, drawn from three lines of
data (protocol, connection, tool). The variants figure is an ordinary view whose scene holds the variants at
one scale and orientation, the differing item highlighted.

## View families: one pull request each

| | Family | Contents | First views |
|---|---|---|---|
| A | The engine and the boards | `docs/diagrams/` (canvas and palette lifted out of the Acorn directory, the old generator's output unchanged byte for byte); model, `geometry.toml`, crop, highlight, inset, orientation, theme, manifest, the checks; the Acorn and the HAT as render layers held to their photos | Acorn top and bottom; P1 and P2 each cropped with pin 1 and inset; the HAT from above; its header rows 19 to 26 and 5 to 10 |
| B | State | Placements and states; the plugging-in sequence for the Pi 5 with a before and an after for every change; the result views; the wrong configurations (housing turned, one row off, TX and RX swapped). Carries the three corrections from the review of the fitting picture: the 2280 standoff as an item, the card drawn in its slot, labels placed by the engine | plug out, aligned, seated at P1 |
| C | The cable | The cable and its internals; the build view; one assembly step view per wire; the verification views (probe points as highlighted items) | wire 1 to its cavity |
| D | The set | The as-laid view; the finished cable in place; the three-layer and variants figures; `figures.toml` complete for the Acorn on a Pi 5 | |
| E | Compute Blade | The same slots from the blade's data | |

The old pictures and the pages that use them are not touched by A to D. They are removed when the pages are
rebuilt on views, in the pull requests that rebuild them.

## Testing

Test-first, with pytest beside the code, run by the existing `wiring.yml` workflow (widened to the new
directory):

- the model refuses unknown ids, a geometry figure without a source, an item outside its object;
- frame, visibility, pin 1, inset, sequence and label rules each have a failing fixture and a passing one;
- a state changes exactly the items it names (the drawn item set is compared);
- light and dark differ only in colour;
- render layer against photo layer, per item, within tolerance;
- the manifest lists every view and only those; `--check` catches a stale view and a stale PNG;
- every slot of every listed board resolves.

Each family's views are then rendered in Chrome, light and dark, and looked at beside the photo of the same
state before review.

## Not in scope

The `view` directive in the docs build; the docs skills; the page templates; rewriting pages; photographing
anything. Views that need a photo nobody has are listed in the manifest as unmatched, for the photo list.
