# SPDX-License-Identifier: Apache-2.0
"""The generated views of the pins each cable lands on say what wiring.toml says."""

import pathlib
import sys

import pytest
import wiring

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from diagrams import model, views

HERE = pathlib.Path(__file__).resolve().parent
SCENE = model.load(HERE / "geometry.toml")
VIEWS = views.load(HERE / "views.toml", SCENE)
PI5 = wiring.CARRIERS["pi5"]


def header_pins(connector):
    """The 40-pin header pins a cable's wires land on, from wiring.toml: the wires cut back land on none."""
    pins = wiring.CONNECTORS[connector]["pins"]
    return {PI5.wires[s][1] for s in pins if s in PI5.wires and PI5.wires[s][0] == "gpio"}


def numbers(selectors):
    return {int(i.id.rsplit(".", 1)[1]) for s in selectors for i in SCENE.select(s)}


@pytest.mark.parametrize("connector", list(wiring.CONNECTORS))
def test_a_pins_only_view_highlights_exactly_the_pins_its_cable_lands_on(connector):
    view = VIEWS[f"pi5-hat.top.{connector.lower()}-pins"]
    lit = numbers(view.highlight)
    assert lit == header_pins(connector)
    # the crop is the housing's footprint, so its empty cavities show, grey, among the lit pins
    assert lit < numbers(view.crop)
