"""The Acorn's part of the wiring canvas: where its files are, and its signals and connectors from wiring.toml.

The canvas itself (Sheet: text as glyph outlines, photos as strokes, the layout and contrast checks that fail
the build) is docs/wiring/wiringlib/canvas.py, and every colour is a token of docs/wiring/wiringlib/palette.py,
resolved into the light and the dark SVG; both are shared with the other generators under docs/wiring/.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # docs/wiring, for wiringlib

import wiring
from wiringlib import canvas
from wiringlib.canvas import (  # noqa: F401
    BODY,
    BOX,
    FAINT,
    FONTS,
    GOLD,
    INK,
    LIGHT_SHORT,
    MUTED,
    ON_WIRE,
    PAPER,
    RED,
    TEXT_ON_PAPER,
    TEXT_SMALL,
    H,
    W,
)
from wiringlib.palette import wire

HERE = pathlib.Path(__file__).parent
OUT = HERE / "generated"
GREY = wire("#9aa0a8")  # a wire that is cut back and is not VCC

# name: (colour, who drives it, what it is), from wiring.toml
SIGNALS = {k: (wire(v["colour"]), v.get("drive"), v["what"]) for k, v in wiring.SIGNALS.items() if k != "VCC"}
P1_PINS = wiring.CONNECTORS["P1"]["pins"]  # pin 1 .. pin 6, physical order
P2_PINS = wiring.CONNECTORS["P2"]["pins"]


def label_of(sig):
    return wiring.SIGNALS[sig]["label"]


class Sheet(canvas.Sheet):
    photos = HERE / "photos"
