# SPDX-License-Identifier: Apache-2.0
"""Render generated/*.svg to PNG with headless Chromium, at 2x, for pages and PDFs that cannot use the SVG."""

import hashlib
import pathlib
import subprocess

out = pathlib.Path(__file__).parent.resolve() / "generated"
sources = []
for svg in sorted(out.glob("*.svg")):
    png = svg.with_suffix(".png")
    subprocess.run(
        [
            "chromium",
            "--headless",
            "--no-sandbox",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--screenshot={png}",
            "--window-size=1600,900",
            svg.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    sources.append(f"{hashlib.sha256(svg.read_bytes()).hexdigest()}  {svg.name}\n")
    print(png.name, png.stat().st_size)
# The SVGs each PNG was rendered from: `gen.py --check` fails if a PNG is older than its SVG.
(out / "png-sources.sha256").write_text("".join(sources))
