# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools==4.65.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""The Tiny Tapeout FPGA demo board's cable picture and pin tables, all from wiring.toml.

Run:  uv run gen.py           (writes generated/; --check compares instead, for CI)
      uv run render.py        (the PNGs of the pictures; needs google-chrome-stable or chromium)

The pictures are generated/tt-fpga-pmod-cables*.svg (picture.py), the tables generated/*.md (tables.py).
fontTools is pinned and the fonts are in ../wiringlib/fonts/, so the output is the same on every machine.
"""

import sys

import picture  # it puts docs/wiring on the import path, which wiringlib (below) is found on
import tables
import wiring
from wiringlib import output

OUT = wiring.HERE / "generated"


def build():
    """{file name: contents} for everything in generated/ except the PNGs (render.py makes those)."""
    return {**picture.build(), **tables.build()}


def main(argv):
    files = build()
    if "--check" in argv:
        output.check(files, OUT)
        return
    output.write(files, OUT)


if __name__ == "__main__":
    main(sys.argv[1:])
