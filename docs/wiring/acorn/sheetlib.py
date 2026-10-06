"""The Acorn's part of the wiring canvas: where its files are, and its signals and connectors from wiring.toml.

The canvas itself (Sheet: text as glyph outlines, photos as strokes, the layout checks that fail the
build) is docs/wiring/wiringlib/canvas.py, shared with the other generators under docs/wiring/.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # docs/wiring, for wiringlib

import wiring
from wiringlib import canvas
from wiringlib.canvas import BODY, FAINT, FONTS, GOLD, INK, MUTED, PAPER, RED, H, W  # noqa: F401

HERE = pathlib.Path(__file__).parent
OUT = HERE / "generated"

# name: (colour, who drives it, what it is), from wiring.toml
SIGNALS = {k: (v["colour"], v.get("drive"), v["what"]) for k, v in wiring.SIGNALS.items() if k != "VCC"}
P1_PINS = wiring.CONNECTORS["P1"]["pins"]  # pin 1 .. pin 6, physical order
P2_PINS = wiring.CONNECTORS["P2"]["pins"]


def label_of(sig):
    return wiring.SIGNALS[sig]["label"]


class Sheet(canvas.Sheet):
    photos = HERE / "photos"
