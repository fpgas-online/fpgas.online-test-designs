# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Render generated/*.svg to PNG with headless Chrome, at 2x, for pages and PDFs that cannot use the SVG.

Run:  uv run render.py
Each SVG is rendered at its own size, read from its root element (docs/diagrams/chrome.py). Google Chrome is
used where it is installed, Chromium otherwise.
"""

import hashlib
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from diagrams import chrome

out = pathlib.Path(__file__).parent.resolve() / "generated"
chrome.browser()  # stops here, with its message, if there is no browser
profile = chrome.new_profile(out.parent)  # Chrome's own files: removed below
sources = []
try:
    for svg in sorted(out.glob("*.svg")):
        png = svg.with_suffix(".png")
        width, height = chrome.render_svg(svg, png, profile)
        sources.append(f"{hashlib.sha256(svg.read_bytes()).hexdigest()}  {svg.name}\n")
        print(png.name, f"{width} x {height}", png.stat().st_size)
finally:
    shutil.rmtree(profile)
# The SVGs each PNG was rendered from: `gen.py --check` fails if a PNG is older than its SVG.
(out / "png-sources.sha256").write_text("".join(sources))
