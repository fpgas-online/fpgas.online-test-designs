# Tiny Tapeout FPGA demo board wiring

How a Tiny Tapeout demo board that carries the FPGA breakout (a Lattice iCE40UP5K) is wired to its host, a
Raspberry Pi with a Digilent Pmod HAT: kept as one table and turned into everything that shows it. Modelled on
the [Acorn generator](../acorn/README.md), and built from the same pieces ([`../wiringlib/`](../wiringlib/__init__.py)).

| File | What it is |
|---|---|
| `wiring.toml` | **The wiring.** Which iCE40 pin is which Tiny Tapeout signal, which demo board header and pin carries it, which Pmod HAT port each header is cabled to, which Raspberry Pi GPIO each port pin is; the serial port, the display, the pins that load the FPGA, the clock, the reset, the LED; what has been measured, with its date and place; and where every other fact comes from (`[sources]`). |
| `wiring.py` | Loads `wiring.toml` and refuses it if an iCE40 pin or a microcontroller pin is given twice, a group has not eight pins, a header has no cable or two headers share a port, an FPGA output lands on a Raspberry Pi GPIO that another wire shares, or a measurement has no date, place or record. Works out each wire's whole way, and which wires share a GPIO, so neither is written down twice. |
| `picture.py` | The cable picture, `tt-fpga-pmod-cables.svg`: both boards as a diagram, each cable, pin 1 marked. Also drawn with only some headers picked out (`-ui-uo`, `-uo`), for the page that is about those. |
| `tables.py` | The pages, as Markdown: `tt-fpga-cables.md` (which header to which port), `tt-fpga-pins-ui-uo.md`, `tt-fpga-pins-uio-uart.md`, `tt-fpga-pins-other.md` (wire by wire) and `tt-fpga-sources.md`. Each is complete in itself and repeats the picture and the sentences needed to find its header; headings start at level 3, to be included under a page's own section. |
| `gen.py` | Writes `generated/` from the table; `--check` fails if `generated/` is not what `wiring.toml` produces, or a PNG was rendered from an older SVG. |
| `render.py` | Renders every SVG in `generated/` to PNG with headless Chrome (or Chromium), for pages and PDFs that cannot take the SVG. |
| `generated/` | The output, committed. Do not edit it by hand. |
| `test_code_agrees.py` | **What stops the documentation and the tests drifting apart.** See below. |
| `test_wiring.py`, `test_tables.py`, `test_picture.py` | The checks on the table, the pages and the picture. |

## The test code keeps its own numbers, and a test holds them to this table

The boot check judges a board's cabling against a table in
[`designs/pmod-pin-id/host/identify_pmod_pins.py`](../../../designs/pmod-pin-id/host/identify_pmod_pins.py)
(`BOARDS["tt"]`). That script, the loopback test, the loader and the serial bridge are installed on the
Raspberry Pi one file at a time, and the gateware's pins are in LiteX's own format
([`designs/_shared/tt_fpga_platform.py`](../../../designs/_shared/tt_fpga_platform.py)), so none of them can
read `wiring.toml`. `test_code_agrees.py` reads each of them and fails when any entry differs from
`wiring.toml`: every wire of the pin identification table, the Pmod HAT's GPIO lists, the wires the pin
identification design gives turns to, the loopback test's GPIO lists, every pin of the platform file, the
loader's microcontroller pins and the serial bridge's. A change to the wiring is made in `wiring.toml` and in
the code in the same commit, or the `Wiring sheets` workflow fails.

## Changing the wiring

```console
$ uv run docs/wiring/tt-fpga/gen.py          # the pictures and pages into generated/
$ uv run docs/wiring/tt-fpga/render.py       # the PNGs (needs google-chrome-stable or chromium)
$ uv run --no-project --with pytest --with fonttools==4.65.0 pytest docs/wiring/tt-fpga
$ git add docs/wiring/tt-fpga
```

Edit `wiring.toml`, never a generated file. Run the tests of this directory on their own, as above: its
modules have the same names as the Acorn generator's (`wiring`, `tables`), so one pytest run cannot hold both.

## What the pages may and may not say

- A wire is printed as *measured* only when a `[[measurements]]` entry covers it, and that entry must carry its
  date, its place and the record it was carried from. Nothing is measured by being written here: add an entry
  only for a measurement that was made, with the record that shows it.
- A fact nobody has checked says so, in `[sources]`, in those words.
- The picture is a diagram. What is printed beside each connector, and where pin 1 is on a real board, is not
  recorded in this repository; the pages say so rather than guess. When someone reads it off a board, record it
  in `wiring.toml` with its date and draw it.
- An FPGA on a demo board is loaded by streaming only; no code of ours writes, replaces or deletes a file on a
  Tiny Tapeout demo board. `tables.STREAMING` prints that on every page that mentions loading.
