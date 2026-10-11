# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import build, draw, model, views
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"


def test_the_committed_views_are_up_to_date():
    assert build.stale(ACORN) == []


def test_the_manifest_lists_every_view_with_both_files():
    files, manifest = build.build(ACORN)
    assert manifest["views"]
    for view_id, entry in manifest["views"].items():
        assert f"{view_id}.svg" in files and f"{view_id}-dark.svg" in files
        assert entry["light"] == f"{view_id}.png" and entry["dark"] == f"{view_id}-dark.png"
        assert entry["photo_matched"] is False and len(entry["svg_sha256"]["light"]) == 64


def test_the_manifest_lists_the_photos_still_wanted_as_views_toml_does():
    manifest = build.build(ACORN)[1]
    wanted = build.photos_wanted(ACORN / "views.toml")
    assert manifest["photos_wanted"] == wanted and len(wanted) >= 4
    assert all(set(w) == {"what", "blocks"} for w in wanted)


@pytest.fixture
def board(tmp_path):
    copy = tmp_path / "acorn"
    shutil.copytree(ACORN, copy, ignore=shutil.ignore_patterns("__pycache__", "*.svg", "acorn-*.png"))
    return copy


def test_a_changed_view_is_stale(board):
    text = (board / "views.toml").read_text().replace('highlight = ["hat.header"]', 'highlight = ["hat.m2-slot"]')
    (board / "views.toml").write_text(text)
    assert any("pi5-hat.top.header" in line for line in build.stale(board))


def test_a_removed_view_whose_png_is_still_there_is_stale(board):
    text = (board / "views.toml").read_text()
    start = text.index('[views."pi5-hat.top.m2-slot"]')
    end = text.index("[views.", start + 1)
    (board / "views.toml").write_text(text[:start] + text[end:])
    assert any("pi5-hat.top.m2-slot.png" in line and "no view" in line for line in build.stale(board))


def test_a_missing_png_is_stale(board):
    (board / "generated" / "views" / "pi5-hat.top.png").unlink()
    assert any("pi5-hat.top.png" in line and "missing" in line for line in build.stale(board))


def test_a_missing_manifest_is_stale(board):
    (board / "generated" / "views" / "views.json").unlink()
    assert any("views.json" in line and "missing" in line for line in build.stale(board))


def test_changed_geometry_is_stale(board):
    text = (board / "geometry.toml").read_text().replace("pitch = 2.54", "pitch = 2.50")
    (board / "geometry.toml").write_text(text)
    assert build.stale(board)


def test_a_changed_photo_wanted_list_is_stale(board):
    text = (board / "views.toml").read_text().replace("the length of a half cable", "the length of a cable")
    (board / "views.toml").write_text(text)
    assert any("photos_wanted" in line for line in build.stale(board))


def test_the_manifest_is_stable_json():
    text = (ACORN / "generated" / "views" / "views.json").read_text()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ('what = "a photo"', "blocks"),
        ('blocks = "a figure"', "what"),
        ('what = "a photo"\nblocks = "a figure"\nwho = "x"', "who"),
        ('what = ""\nblocks = "a figure"', "what"),
        ('what = "a photo"\nblocks = 3', "blocks"),
        ('what = ["a photo"]\nblocks = "a figure"', "what"),
    ],
)
def test_a_malformed_photos_wanted_entry_is_refused(tmp_path, entry, message):
    path = tmp_path / "views.toml"
    path.write_text(f"[[photos_wanted]]\n{entry}\n")
    with pytest.raises(DiagramError, match=message) as e:
        build.photos_wanted(path)
    assert "photos_wanted" in str(e.value)


def test_photos_wanted_that_is_not_an_array_of_tables_is_refused(tmp_path):
    path = tmp_path / "views.toml"
    path.write_text('photos_wanted = "a photo"\n')
    with pytest.raises(DiagramError, match="photos_wanted"):
        build.photos_wanted(path)


def test_each_manifest_entry_agrees_with_its_view_and_its_drawing_and_its_files():
    """Not the committed file: what build() makes now, entry by entry, against the sources it came from."""
    scene = model.load(ACORN / "geometry.toml")
    declared = views.load(ACORN / "views.toml", scene)
    files, manifest = build.build(ACORN)
    assert list(manifest["views"]) == list(declared)
    for view_id, view in declared.items():
        entry, facts = manifest["views"][view_id], draw.render(scene, view)[1]
        assert (entry["thing"], entry["face"], entry["turn"], entry["sequence"]) == (
            view.thing,
            view.face,
            view.turn,
            view.sequence,
        ), view_id
        assert (entry["size"], entry["highlight"], entry["inset"]) == (
            facts["size"],
            facts["highlight"],
            facts["inset"],
        ), view_id
        assert entry["photo_matched"] is False, view_id
        for theme, name in (("light", f"{view_id}.svg"), ("dark", f"{view_id}-dark.svg")):
            assert entry["svg_sha256"][theme] == hashlib.sha256(files[name].encode()).hexdigest(), (view_id, theme)


def test_a_png_with_one_byte_changed_is_stale(board):
    png = board / "generated" / "views" / "pi5-hat.top.png"
    data = bytearray(png.read_bytes())
    data[-20] ^= 1
    png.write_bytes(bytes(data))
    assert any("pi5-hat.top.png" in line and "does not match its recorded hash" in line for line in build.stale(board))


def test_a_png_replaced_by_another_picture_is_stale(board):
    out = board / "generated" / "views"
    (out / "pi5-hat.top-dark.png").write_bytes((out / "pi5-hat.top.png").read_bytes())
    assert any(
        "pi5-hat.top-dark.png" in line and "does not match its recorded hash" in line for line in build.stale(board)
    )


def test_a_manifest_that_records_no_hash_for_a_png_is_stale(board):
    path = board / "generated" / "views" / "views.json"
    manifest = json.loads(path.read_text())
    del manifest["views"]["pi5-hat.top"]["png_sha256"]["dark"]
    path.write_text(build.manifest_text(manifest))
    assert any("pi5-hat.top" in line and "no recorded hash" in line for line in build.stale(board))


def test_the_committed_manifest_records_the_hash_of_every_png_beside_its_svgs():
    manifest = json.loads((ACORN / "generated" / "views" / "views.json").read_text())
    for view_id, entry in manifest["views"].items():
        assert set(entry["png_sha256"]) == {"light", "dark"} == set(entry["svg_sha256"]), view_id
        for theme in ("light", "dark"):
            png = (ACORN / "generated" / "views" / entry[theme]).read_bytes()
            assert entry["png_sha256"][theme] == hashlib.sha256(png).hexdigest(), (view_id, theme)


def test_writing_records_the_hash_of_the_pngs_it_has_just_rendered(board):
    out = board / "generated" / "views"
    manifest = build.build(board)[1]
    assert all("png_sha256" not in e for e in manifest["views"].values())  # a fresh build has no PNGs to hash
    recorded = build.with_png_hashes(manifest, out)
    committed = json.loads((out / "views.json").read_text())
    assert recorded == committed
