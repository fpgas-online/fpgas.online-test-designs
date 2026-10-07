# SPDX-License-Identifier: Apache-2.0
"""What the wiring generators under docs/wiring/ share, so that an improvement to one reaches all.

canvas.py     the SVG canvas: text as glyph outlines, the layout and contrast checks that fail the build
palette.py    every colour, light and dark: drawings made with tokens, resolved into <name>.svg and <name>-dark.svg
fragments.py  the banner every generated Markdown file starts with, a Markdown table, a picture as its light/dark pair
output.py     writing generated/, and `--check`: failing when generated/ is not what the source produces
chrome.py     rendering generated/*.svg to PNG with headless Chrome
fonts/        Liberation Sans and Mono (SIL Open Font License, fonts/COPYRIGHT)

A generator puts docs/wiring on its import path and imports from here; it is not an installed package.
"""
