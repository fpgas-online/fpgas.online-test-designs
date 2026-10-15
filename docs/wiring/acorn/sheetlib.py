# SPDX-License-Identifier: Apache-2.0
"""The Acorn sheets' canvas: docs/diagrams/canvas.py's Sheet at the sheets' size, with the Acorn's signals."""

import pathlib

import palette  # noqa: F401  (puts docs/ on the path)
import wiring
from diagrams import canvas
from diagrams.canvas import (  # noqa: F401
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
