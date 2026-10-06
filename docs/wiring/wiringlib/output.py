# SPDX-License-Identifier: Apache-2.0
"""Write a generator's files into its generated/ directory, or check that what is there is current."""

import hashlib


def stale(files, out):
    """What in `out` is not what the generator produces now, as a sorted list of lines; empty when current.

    `files` is {file name: text}: every .svg and .md the generator writes. A file that differs or is
    missing is stale, so is an .svg or .md in `out` that the generator no longer writes, and so is a PNG
    whose SVG has changed since chrome.py rendered it (png-sources.sha256 records what it rendered from).
    """
    found = [f for f, text in files.items() if not (out / f).exists() or (out / f).read_text() != text]
    found += [p.name for p in out.glob("*") if p.suffix in (".svg", ".md") and p.name not in files]
    rendered = (out / "png-sources.sha256").read_text() if (out / "png-sources.sha256").exists() else ""
    for f, text in files.items():
        if f.endswith(".svg") and f"{hashlib.sha256(text.encode()).hexdigest()}  {f}" not in rendered.splitlines():
            found.append(f"{f[:-4]}.png (rendered from an older {f}; run render.py)")
    return sorted(found)


def check(files, out):
    """`gen.py --check`: stop with the list of stale files, or say that generated/ is up to date."""
    found = stale(files, out)
    if found:
        raise SystemExit(
            "generated/ is out of date with wiring.toml or the generator; run `uv run gen.py` and commit:\n  "
            + "\n  ".join(found)
        )
    print("generated/ is up to date")


def write(files, out):
    """`gen.py`: write every file, and remove an .svg, .png or .md the generator no longer writes."""
    out.mkdir(exist_ok=True)
    for f, text in files.items():
        (out / f).write_text(text)
    keep = set(files) | {f"{f[:-4]}.png" for f in files if f.endswith(".svg")}
    gone = [p for p in out.glob("*") if p.suffix in (".svg", ".png", ".md") and p.name not in keep]
    for p in gone:
        p.unlink()
    removed = f", removed {len(gone)} it no longer writes" if gone else ""
    print(f"wrote {len(files)} files to {out.parent.name}/{out.name}/{removed}; run render.py for the PNGs")
