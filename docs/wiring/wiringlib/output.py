# SPDX-License-Identifier: Apache-2.0
"""Write a generator's files into its generated/ directory, or check that what is there is current."""

import hashlib


def stale(files, out):
    """What in `out` is not what the generator produces now, as a sorted list of lines; empty when current.

    `files` is {file name: text}: every .svg and .md the generator writes. A file that differs or is
    missing is stale, so is an .svg, .md or .png in `out` that the generator no longer writes (a PNG is
    written for each SVG), and so is a PNG whose SVG has changed since chrome.py rendered it
    (png-sources.sha256 records what it rendered from).
    """
    found = [f for f, text in files.items() if not (out / f).exists() or (out / f).read_text() != text]
    found += [f"{p.name} (the generator no longer writes it)" for p in unwanted(files, out)]
    rendered = (out / "png-sources.sha256").read_text() if (out / "png-sources.sha256").exists() else ""
    for f, text in files.items():
        if f.endswith(".svg") and f"{hashlib.sha256(text.encode()).hexdigest()}  {f}" not in rendered.splitlines():
            found.append(f"{f[:-4]}.png (rendered from an older {f}; run render.py)")
    return sorted(found)


def unwanted(files, out):
    """The .svg, .md and .png files in `out` that the generator does not write: write() removes them and
    check() fails on them, so the two can never disagree about what belongs in generated/."""
    keep = set(files) | {f"{f[:-4]}.png" for f in files if f.endswith(".svg")}
    return sorted(p for p in out.glob("*") if p.suffix in (".svg", ".png", ".md") and p.name not in keep)


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
    for p in unwanted(files, out):
        p.unlink()
        print(f"removed {out.parent.name}/{out.name}/{p.name}: the generator no longer writes it")
    print(f"wrote {len(files)} files to {out.parent.name}/{out.name}/; run render.py for the PNGs")
