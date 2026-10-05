# Acorn wiring

How an SQRL Acorn (CLE-215+, or the CLE-101 sold as LiteFury) is wired to its
host, kept as one table and turned into everything that shows it.

| File | What it is |
|---|---|
| `wiring.toml` | **The wiring.** The Acorn's P1 and P2 pinouts, each carrier's headers as printed on the board, which wire goes to which pin, the series resistor, and the Dupont housings. |
| `wiring.py` | Loads `wiring.toml` and refuses it if a wire lands on a 5 V or 3.3 V pin, two wires share a pin, VCC is wired, a ground meets a signal, or a wire is outside every housing. |
| `gen.py` | Writes `generated/` from the table: the two wiring sheets (`sheetlib.py`) and the pin tables (`tables.py`). |
| `render.py` | Renders the sheets to PNG with headless Chromium, for pages and PDFs that cannot take the SVG. |
| `generated/` | The output, committed. [fpgas.online-docs](https://github.com/fpgas-online/fpgas.online-docs) copies it onto [docs.fpgas.online](https://docs.fpgas.online/en/latest/boards/acorn/wiring.html); do not edit it by hand. |
| `GOALS.md` | What the sheets have to show, and what must not be on them. |
| `photos/`, `prep_photos.py` | The board photos the sheets use, and the script that cut them from the vendors' originals. |
| `fonts/` | Liberation Sans and Mono (SIL Open Font License, `fonts/COPYRIGHT`), drawn as outlines in the sheets. |

## Changing the wiring

```console
$ uv run docs/wiring/acorn/gen.py          # about a minute: sheets and tables into generated/
$ uv run --no-project python docs/wiring/acorn/render.py  # the PNGs (needs chromium)
$ git add docs/wiring/acorn
```

Edit `wiring.toml`, never a generated file or the picture. The `Wiring sheets`
workflow runs the tests, and `gen.py --check`, which fails if `generated/` is
not what `wiring.toml` produces, or if a PNG was rendered from an older SVG.

The sheet generator fails the build if any label leaves its box or the canvas,
overlaps another label, sits on a wire, or a pad leaves its header. Pillow and
fontTools are pinned in `gen.py` and the fonts are here, so the output is the
same byte for byte on every machine. `gen.py --search` tries every header
placement again (a few minutes) and reports the one with the fewest wire
crossings; the placements in use are `NUDGE` in `gen.py`.

## The SVGs load nothing

Text is drawn as glyph outlines and each photo as horizontal runs of colour,
so the SVGs have no `data:` URIs or other references. They therefore render
from their `raw.githubusercontent.com` URLs, which are served with
`Content-Security-Policy: default-src 'none'`. That costs about 2 MB a sheet.

## Photos

`prep_photos.py` made `photos/` from the vendors' originals, which are not in
this repository: the Compute Blade top view is Uptime Lab's
(docs.computeblade.com), the HAT is Waveshare's dimension drawing of the PoE
M.2 HAT+, and the card underside is RHS Research's LiteFury photo (the Acorn is
the same PCB). Each sheet credits them.
