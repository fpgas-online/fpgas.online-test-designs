# Acorn wiring

How an SQRL Acorn (CLE-215+, or the CLE-101 sold as LiteFury) is wired to its
host, kept as one table and turned into everything that shows it.

| File | What it is |
|---|---|
| `wiring.toml` | **The wiring.** The Acorn's P1 and P2 pinouts, each carrier's headers as printed on the board, which wire goes to which pin, the series resistor, and the Dupont housings. |
| `wiring.py` | Loads `wiring.toml` and refuses it if a wire lands on a 5 V or 3.3 V pin, two wires share a pin, VCC is wired, a ground meets a signal, or a wire is outside every housing. |
| `gen.py` | Writes `generated/` from the table: the two wiring sheets (`sheetlib.py`), the pin tables and the parts lists (`tables.py`), and, by calling `steps.py`, the cable pictures and procedures; every drawing as a light SVG and a dark one (`<name>-dark.svg`). |
| `palette.py` | Every colour of the drawings, light and dark, in one place (see "Light and dark" below). |
| `steps.py` | The pictures and the text for building the two cables, on the sheets' canvas and photos, all in `generated/`. `acorn-cable-<carrier>-<connector>.svg`: which wire goes in which cavity of the housing. `acorn-cable-<connector>-flag.svg`: the plug in its socket, every wire whole, a numbered flag on each. `acorn-cable-<connector>-ground-check.svg`: checking which wire is wire 1 with a meter, before any wire is cut back. `acorn-cable-<carrier>-<connector>-prepare.svg`: which wires are cut back and which get a terminal. `acorn-cable-<carrier>-<connector>-resistor.svg`: fitting the series resistor, where a cable has one. `acorn-card-underside.svg`: the card's connector end, labelled, for the device-info page. `acorn-cable-cut.svg`, `acorn-cable-crimp.svg`, `acorn-cable-push.svg`, `acorn-cable-check.svg`: the steps every cable shares, sketched. `acorn-cable-<carrier>-shell-check.svg`: the bench check before power. `acorn-cable-<carrier>-fit.svg` and `acorn-fit-<carrier>.md`: fitting the cables, as a numbered list with its picture, used as the procedure's last step and by the wiring page. `acorn-cables-<carrier>.md`: the whole procedure for a carrier, each step with its picture, complete in itself (headings from level 3, to be included under a page section). Narrower than a sheet and with larger text, to be read at a page's text width. Its `ASSUMPTIONS` are printed on every cavity picture until a built cable or a photograph settles them. `guide()` writes the same procedure as pages, `acorn-build-<carrier>-<part>.md` (overview, jtag-1, jtag-2, uart-1, uart-2, bench, fit), each numbered from 1 and within five printed A4 sheets; the overview prints `wiring.toml`'s `[sources]`. |
| `check.py` | The 'verifying' pages of each carrier, `acorn-check-<carrier>-<part>.md`: 1 run the check and read the result, 2 from a failing line to the wire, 2b every other Acorn message, and for the blade 3 what has been run on one; and the picture of which test uses which wire (`acorn-check-<carrier>-wires.svg`). The words the carriers share are in `check/*.md`, where a line starting `<!-- pi5 -->` or `<!-- blade -->` is for that carrier only and `<!-- pi5:begin -->` to `<!-- pi5:end -->` a block; the transcripts and the Acorn rows of 'Common failures' are read from `docs/verify/reading-the-result.md` and `docs/verify/common-failures.md`, so each exists once; the cavity pictures are `steps.py`'s, shown again. A page is included under a page's title (headings from level 2). |
| `render.py` | Renders every SVG in `generated/` (light and dark) to PNG, each at its own size, with headless Chrome (or Chromium where Chrome is not installed), for pages and PDFs that cannot take the SVG. |
| `generated/` | The output, committed. [fpgas.online-docs](https://github.com/fpgas-online/fpgas.online-docs) copies it onto [docs.fpgas.online](https://docs.fpgas.online/en/latest/boards/acorn/wiring.html); do not edit it by hand. |
| `GOALS.md` | What the sheets have to show, and what must not be on them. |
| `photos/`, `prep_photos.py` | The board photos the sheets use, and the script that cut them from the vendors' originals. |
| `measure_hat.py` | Measures where the HAT's header, pin 1 and M.2 slot are in its photo; `--check` compares with `wiring.toml`. |
| `fonts/` | Liberation Sans and Mono (SIL Open Font License, `fonts/COPYRIGHT`), drawn as outlines in the sheets. |

## Changing the wiring

```console
$ uv run docs/wiring/acorn/gen.py          # about a minute: sheets and tables into generated/
$ uv run docs/wiring/acorn/render.py       # the PNGs (needs google-chrome-stable or chromium)
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

## Light and dark

Every drawing is written twice: `<name>.svg` on light paper and
`<name>-dark.svg` beside it for the dark theme of docs.fpgas.online (its paper
is the theme's background, `#131416`), each with its PNG. The two differ only
in their colours, and in a few words for the dark sheet only (`Sheet.dark_only()`:
a caption that calls the wires black says there that black is drawn light). `palette.py` holds every colour the drawings use, named by
what it is and what it stands on, with its light and its dark value; the
drawing code writes those names as tokens and `palette.resolve()` turns them
into the two SVGs. A colour written anywhere else (an attribute, a hex value, a
style) stops the build, and so does any text short of 7:1 contrast straight on
the dark paper or 4.5:1 on a tag or box (`sheetlib.py`). Text of the light
sheets under 4.5:1 is printed by `gen.py` as a report, not a failure. Photographs keep their own colours on both; only the
background `prep_photos.py` painted round a board, joined to the photo's edge,
is left out, so the sheet shows through it.

In the generated Markdown each picture is the pair
`![alt](x.png){.only-light}` and `![alt](x-dark.png){.only-dark}`: the docs
theme's classes, which show one or the other (MyST's `attrs_inline` sets
them; the docs enable it). The printed booklet keeps the light one.

## Photos

`prep_photos.py` made `photos/` from the vendors' originals, which are not in
this repository (put them in `ref/` to run it again): the Compute Blade top view
is Uptime Lab's (docs.computeblade.com), the HAT is Waveshare's dimension
drawing of the PoE M.2 HAT+ (B), and the card underside is RHS Research's
LiteFury photo (the Acorn is the same PCB). Each sheet credits them.

The HAT is the one table `[carriers.pi5.hat]` in `wiring.toml`: its name, the
product string of its HAT EEPROM, Waveshare's page and drawing, the largest card
it takes, and where its header, pin 1 and M.2 slot are in the photo.
`measure_hat.py` measures those places in the photo, scaled by the drawing's
mounting holes; `measure_hat.py --check` (and the tests) fail if `wiring.toml`
says otherwise. Only the (B) is drawn: the PoE M.2 HAT+ without the (B) takes
2230 and 2242 cards only, and an Acorn is a 2280.
