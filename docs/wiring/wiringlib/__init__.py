# SPDX-License-Identifier: Apache-2.0
"""What the wiring generators under docs/wiring/ share, so that an improvement to one reaches all.

canvas.py     the SVG canvas: text as glyph outlines, the layout checks that fail the build
fragments.py  the banner every generated Markdown file starts with, and a Markdown table
output.py     writing generated/, and `--check`: failing when generated/ is not what the source produces
chrome.py     rendering generated/*.svg to PNG with headless Chrome
fonts/        Liberation Sans and Mono (SIL Open Font License, fonts/COPYRIGHT)

A generator puts docs/wiring on its import path and imports from here; it is not an installed package.
"""
