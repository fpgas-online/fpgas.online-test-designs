# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Render generated/*.svg to PNG with headless Chrome, at 2x, for pages and PDFs that cannot use the SVG.

Run:  uv run render.py
Each SVG is rendered at its own size, read from its root element. Google Chrome is used where it is
installed, Chromium otherwise.
"""

import hashlib
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

out = pathlib.Path(__file__).parent.resolve() / "generated"
browser = next((b for b in ("google-chrome-stable", "chromium") if shutil.which(b)), None)
if browser is None:
    raise SystemExit("render.py needs google-chrome-stable or chromium on the PATH")
# Without this a headless Chrome waits minutes for the session bus on a machine that has a desktop session.
env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
profile = tempfile.mkdtemp(prefix=".render-profile-", dir=out.parent)  # Chrome's own files: removed below
sources = []
try:
    for svg in sorted(out.glob("*.svg")):
        root = re.match(r"<svg\b[^>]*>", svg.read_text())
        size = root and [re.search(rf'\b{name}="(\d+)"', root.group(0)) for name in ("width", "height")]
        if not root or not all(size):
            raise SystemExit(f"{svg.name}: no whole-number width and height on its root element")
        w, h = (int(m.group(1)) for m in size)
        png = svg.with_suffix(".png")
        run = subprocess.run(
            [
                browser,
                "--headless",
                "--no-sandbox",
                "--hide-scrollbars",
                f"--force-device-scale-factor={SCALE}",
                f"--user-data-dir={profile}",
                f"--screenshot={png}",
                f"--window-size={w},{h + SPARE}",
                svg.as_uri(),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
        if run.returncode:
            raise SystemExit(f"{svg.name}: {browser} exited {run.returncode}:\n{run.stderr}")
        shot = Image.open(png)
        if shot.width != SCALE * w or shot.height < SCALE * h:
            raise SystemExit(f"{png.name}: the screenshot is {shot.size}, too small for an SVG of {w} x {h}")
        shot.crop((0, 0, SCALE * w, SCALE * h)).save(png)
        sources.append(f"{hashlib.sha256(svg.read_bytes()).hexdigest()}  {svg.name}\n")
        print(png.name, f"{SCALE * w} x {SCALE * h}", png.stat().st_size)
finally:
    shutil.rmtree(profile)
# The SVGs each PNG was rendered from: `gen.py --check` fails if a PNG is older than its SVG.
(out / "png-sources.sha256").write_text("".join(sources))
