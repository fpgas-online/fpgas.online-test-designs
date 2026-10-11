# SPDX-License-Identifier: Apache-2.0
"""An SVG to a PNG with headless Chrome, at 2x. Google Chrome is used where it is installed, Chromium otherwise."""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from PIL import Image

SCALE = 2
# Headless Chrome's page is shorter than the --window-size it is given (the window's own furniture is taken
# off), so a window of exactly the SVG's size cuts the bottom of the picture off. The window is therefore
# made this much taller than the SVG, and the screenshot cropped back to the SVG's size.
SPARE = 200


def browser():
    """The browser to run, or SystemExit saying none is installed."""
    found = next((b for b in ("google-chrome-stable", "chromium") if shutil.which(b)), None)
    if found is None:
        raise SystemExit("rendering needs google-chrome-stable or chromium on the PATH")
    return found


def new_profile(parent):
    """A directory for Chrome's own files, under `parent`: the caller removes it."""
    return tempfile.mkdtemp(prefix=".render-profile-", dir=parent)


def render_svg(svg_path, png_path, profile):
    """Render the SVG at `svg_path` to a PNG at `png_path`, SCALE times its own size, read from its root
    element. `profile` is a directory for Chrome's files (new_profile). Returns (width, height) of the PNG."""
    svg, png = pathlib.Path(svg_path), pathlib.Path(png_path)
    exe = browser()
    root = re.match(r"<svg\b[^>]*>", svg.read_text())
    size = root and [re.search(rf'\b{name}="(\d+)"', root.group(0)) for name in ("width", "height")]
    if not root or not all(size):
        raise SystemExit(f"{svg.name}: no whole-number width and height on its root element")
    w, h = (int(m.group(1)) for m in size)
    # Without this a headless Chrome waits minutes for the session bus on a machine that has a desktop session.
    env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
    run = subprocess.run(
        [
            exe,
            "--headless",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}",
            f"--user-data-dir={profile}",
            f"--screenshot={png}",
            f"--window-size={w},{h + SPARE}",
            svg.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    if run.returncode:
        raise SystemExit(f"{svg.name}: {exe} exited {run.returncode}:\n{run.stderr}")
    shot = Image.open(png)
    if shot.width != SCALE * w or shot.height < SCALE * h:
        raise SystemExit(f"{png.name}: the screenshot is {shot.size}, too small for an SVG of {w} x {h}")
    shot.crop((0, 0, SCALE * w, SCALE * h)).save(png)
    return SCALE * w, SCALE * h
