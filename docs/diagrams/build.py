# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow==12.3.0", "fonttools==4.65.0"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Every view of a board to SVG and PNG, and the manifest pages reference them by.

Run:  uv run docs/diagrams/build.py docs/wiring/acorn [--check]

Without --check: writes each view's light and dark SVG to <board>/tmp-views/ (git-ignored), renders them to PNG
at 2x with headless Chrome, moves the PNGs to <board>/generated/views/, writes views.json beside them, removes
tmp-views/ and any PNG there that no view owns.

With --check: builds the SVGs in memory only (it never starts Chrome) and compares the manifest built now with
the committed views.json. A changed geometry.toml or views.toml, or a changed drawing, shows in the SVGs' SHA-256
sums. It does NOT re-render the PNGs: it reports a PNG that is missing or that no view owns, but not one that
is out of date with its SVG. Rebuild after any change and commit the PNGs with the manifest.
"""

import hashlib
import json
import pathlib
import shutil
import sys

import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from diagrams import draw, model, palette, views
from diagrams.errors import DiagramError

OUT = "generated/views"
TMP = "tmp-views"
MANIFEST = "views.json"
WANTED_KEYS = {"what", "blocks"}


def photos_wanted(views_path):
    """The photos and figures still wanted: the `[[photos_wanted]]` entries of a views.toml, each `what` and
    `blocks` as one line of text. Anything else in an entry is refused."""
    raw = tomllib.loads(pathlib.Path(views_path).read_text()).get("photos_wanted", [])
    if not (isinstance(raw, list) and all(isinstance(e, dict) for e in raw)):
        raise DiagramError(f"{views_path}: photos_wanted is not an array of tables")
    for n, entry in enumerate(raw, 1):
        where = f"photos_wanted entry {n}"
        if set(entry) - WANTED_KEYS:
            raise DiagramError(f"{where}: unknown key {sorted(set(entry) - WANTED_KEYS)}")
        for key in sorted(WANTED_KEYS):
            value = entry.get(key)
            if not (isinstance(value, str) and value.strip() and "\n" not in value):
                raise DiagramError(f"{where}: {key} is missing or is not one line of text")
    return [dict(e) for e in raw]


def build(board_dir):
    """({file name: SVG text}, manifest) for every view of the board, in memory. No Chrome, no files."""
    board = pathlib.Path(board_dir)
    scene = model.load(board / "geometry.toml")
    declared = views.load(board / "views.toml", scene)
    files, entries = {}, {}
    for view_id, view in declared.items():
        svg, facts = draw.render(scene, view)
        stem = views.file_stem(view_id)
        light, dark = palette.resolve(svg, "light"), palette.resolve(svg, "dark")
        files[f"{stem}.svg"], files[f"{stem}-dark.svg"] = light, dark
        entries[view_id] = {
            "light": f"{stem}.png",
            "dark": f"{stem}-dark.png",
            "size": facts["size"],
            "thing": view.thing,
            "face": view.face,
            "turn": view.turn,
            "sequence": view.sequence,
            "highlight": facts["highlight"],
            "inset": facts["inset"],
            "photo_matched": False,
            "svg_sha256": {
                "light": hashlib.sha256(light.encode()).hexdigest(),
                "dark": hashlib.sha256(dark.encode()).hexdigest(),
            },
        }
    return files, {"photos_wanted": photos_wanted(board / "views.toml"), "views": entries}


def manifest_text(manifest):
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def stale(board_dir):
    """One line for each way the committed views are not what the board's files make now. Empty if current."""
    board = pathlib.Path(board_dir)
    out = board / OUT
    manifest = build(board)[1]
    problems = []
    if not (out / MANIFEST).is_file():
        problems.append(f"{OUT}/{MANIFEST} is missing")
    else:
        text = (out / MANIFEST).read_text()
        if text != manifest_text(manifest):
            try:
                old = json.loads(text)
            except json.JSONDecodeError as e:
                old = {}
                problems.append(f"{OUT}/{MANIFEST} is not JSON: {e}")
            old_views = old.get("views", {})
            for view_id, entry in manifest["views"].items():
                if view_id not in old_views:
                    problems.append(f"view {view_id}: not in {MANIFEST}")
                elif old_views[view_id] != entry:
                    problems.append(f"view {view_id}: its entry in {MANIFEST} is out of date")
            for view_id in sorted(set(old_views) - set(manifest["views"])):
                problems.append(f"view {view_id}: in {MANIFEST} but no longer in views.toml")
            if old.get("photos_wanted") != manifest["photos_wanted"]:
                problems.append(f"photos_wanted in {MANIFEST} is out of date")
            if not problems:
                problems.append(f"{OUT}/{MANIFEST} is not what a build writes")
    owned = {name for e in manifest["views"].values() for name in (e["light"], e["dark"])}
    for name in sorted(owned):
        if not (out / name).is_file():
            problems.append(f"{OUT}/{name} is missing")
    if out.is_dir():
        for png in sorted(out.glob("*.png")):
            if png.name not in owned:
                problems.append(f"{OUT}/{png.name}: no view owns it")
    return problems


def write(board_dir):
    """Build, render the PNGs with Chrome, and write generated/views/. Returns the manifest."""
    from diagrams import chrome

    board = pathlib.Path(board_dir)
    files, manifest = build(board)
    tmp, out = board / TMP, board / OUT
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    out.mkdir(parents=True, exist_ok=True)
    chrome.browser()
    profile = chrome.new_profile(tmp)
    try:
        for name, text in files.items():
            svg = tmp / name
            svg.write_text(text)
            png = svg.with_suffix(".png")
            width, height = chrome.render_svg(svg, png, profile)
            shutil.move(png, out / png.name)
            print(png.name, f"{width} x {height}")
    finally:
        shutil.rmtree(tmp)
    owned = {name for e in manifest["views"].values() for name in (e["light"], e["dark"])}
    for png in sorted(out.glob("*.png")):
        if png.name not in owned:
            png.unlink()
            print(f"removed {png.name}: no view owns it")
    (out / MANIFEST).write_text(manifest_text(manifest))
    return manifest


def main(argv):
    args = [a for a in argv if a != "--check"]
    if len(args) != 1 or len(argv) - len(args) > 1:
        raise SystemExit("usage: build.py BOARD_DIR [--check]")
    try:
        if "--check" in argv:
            problems = stale(args[0])
            if problems:
                raise SystemExit("views are out of date; run build.py without --check:\n" + "\n".join(problems))
            print("views are up to date")
        else:
            manifest = write(args[0])
            print(f"wrote {len(manifest['views'])} views to {args[0]}/{OUT}/")
    except DiagramError as e:
        raise SystemExit(f"build.py: {e}") from None


if __name__ == "__main__":
    main(sys.argv[1:])
