# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Render generated/*.svg to PNG with headless Chrome, at 2x, for pages and PDFs that cannot use the SVG.

Run:  uv run render.py
The work is docs/wiring/wiringlib/chrome.py, shared with the Acorn generator.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # docs/wiring, for wiringlib

from wiringlib import chrome

chrome.render(pathlib.Path(__file__).parent.resolve() / "generated")
