# SPDX-License-Identifier: Apache-2.0
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from diagrams import model, views
from diagrams.errors import DiagramError

ACORN = pathlib.Path(__file__).resolve().parents[1] / "wiring" / "acorn"
SCENE = model.load(ACORN / "geometry.toml")


def load(tmp_path, text):
    path = tmp_path / "views.toml"
    path.write_text(text)
    return views.load(path, SCENE)


def test_the_committed_views_load():
    assert "pi5-hat.top" in views.load(ACORN / "views.toml", SCENE)


def test_defaults(tmp_path):
    v = load(tmp_path, '[views."a.b"]\nthing = "hat"\nface = "top"\n')["a.b"]
    assert (v.turn, v.crop, v.highlight, v.callouts, v.sequence, v.width) == (0, (), (), {}, None, 700)


@pytest.mark.parametrize(
    "body, message",
    [
        ('thing = "hta"\nface = "top"\n', "no thing 'hta'"),
        ('thing = "hat"\nface = "side"\n', "face"),
        ('thing = "hat"\nface = "top"\nturn = 45\n', "turn"),
        ('thing = "hat"\nface = "top"\ncrop = ["hat.m2-slto"]\n', "hat.m2-slot"),
        (
            'thing = "hat"\nface = "top"\nhighlight = ["hat.m2-slot"]\ncrop = ["hat.header.pins.19-26"]\n',
            "outside",
        ),
        ('thing = "hat"\nface = "top"\ntitle = "The HAT"\n', "unknown key"),
        ('thing = "hat"\nface = "bottom"\ncrop = ["hat.m2-slot"]\n', "not on the face shown"),
    ],
)
def test_a_bad_view_is_refused(tmp_path, body, message):
    with pytest.raises(DiagramError, match=message):
        load(tmp_path, f'[views."a.b"]\n{body}')


def test_an_upper_case_id_is_refused_so_two_ids_never_share_a_file(tmp_path):
    text = '[views."a.b"]\nthing = "hat"\nface = "top"\n[views."A.b"]\nthing = "hat"\nface = "top"\n'
    with pytest.raises(DiagramError, match="id"):
        load(tmp_path, text)


def test_an_id_must_be_lower_case_words_joined_by_dots_and_hyphens(tmp_path):
    with pytest.raises(DiagramError, match="id"):
        load(tmp_path, '[views."a b"]\nthing = "hat"\nface = "top"\n')


def test_a_sequence_gives_its_views_their_viewpoint_and_allows_one_change(tmp_path):
    head = '[sequences.s]\nthing = "hat"\nface = "top"\nturn = 0\n'
    one = (
        head
        + '[views."s.1"]\nsequence = "s"\n[views."s.2"]\nsequence = "s"\nturn = 90\n'
        + '[views."s.3"]\nsequence = "s"\nturn = 90\n'
    )
    got = load(tmp_path, one)
    assert [v.turn for v in got.values()] == [0, 90, 90]
    two = one + '[views."s.4"]\nsequence = "s"\nturn = 0\n'
    with pytest.raises(DiagramError, match="changes its viewpoint twice"):
        load(tmp_path, two)


def test_a_crop_is_its_items_union_grown_by_the_margin_and_kept_on_the_thing(tmp_path):
    view = load(tmp_path, '[views."a.b"]\nthing = "hat"\nface = "top"\ncrop = ["hat.header.pins.19-26"]\n')["a.b"]
    union = SCENE.item("hat.header.pin.19").box.union(SCENE.item("hat.header.pin.26").box)
    width = SCENE.things["hat"].size[0]
    assert views.MARGIN == 3.0 and union.x1 + 3.0 > width  # the header is at the board's edge: the margin runs off it
    box = views.crop_box(SCENE, view)
    assert (box.x0, box.y0, box.x1, box.y1) == pytest.approx((union.x0 - 3.0, union.y0 - 3.0, width, union.y1 + 3.0))
