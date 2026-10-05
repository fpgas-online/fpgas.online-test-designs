# SPDX-License-Identifier: Apache-2.0
"""The step pictures say what wiring.toml says.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import copy
import functools
import re

import pytest
import steps
import wiring

RAW = wiring.DATA["carriers"]
CABLES = [(key, connector) for key in wiring.CARRIERS for connector in wiring.CONNECTORS]
RAILS = ("5V", "3.3V")


@functools.cache
def picture(key, connector):
    return steps.cable(wiring.CARRIERS[key], connector)[0]


def words(svg):
    """Every piece of text in a picture, in the order it was drawn."""
    return re.findall(r'aria-label="([^"]*)"', svg)


def rail(name):
    return name.replace(" ", "") in RAILS


def test_every_cable_has_its_picture():
    assert sorted(steps.CABLES) == sorted(CABLES)


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_every_connected_wire_is_in_exactly_one_cavity_and_a_cut_wire_in_none(key, connector):
    plan = steps.housing(wiring.CARRIERS[key], connector)
    filled = [s for s in plan.cavities.values() if s is not None]
    for sig in wiring.CONNECTORS[connector]["pins"]:
        if sig in RAW[key]["wires"]:
            header, pin = RAW[key]["wires"][sig]
            assert filled.count(sig) == 1
            assert (plan.header, plan.cavities[pin]) == (header, sig)
            assert sig not in plan.cut
        else:
            assert sig not in filled
            assert sig in plan.cut
    assert "VCC" in plan.cut
    assert len(filled) + len(plan.cut) == len(wiring.CONNECTORS[connector]["pins"])
    # the housing is one of the header's own, whole
    assert [plan.first, plan.last] in RAW[key]["headers"][plan.header]["housings"]
    assert sorted(plan.cavities) == list(range(plan.first, plan.last + 1))
    # the empty cavities are exactly the housing's pins that wiring.toml puts no wire on
    on_header = {pin for header, pin in RAW[key]["wires"].values() if header == plan.header}
    assert {n for n, s in plan.cavities.items() if s is None} == set(plan.cavities) - on_header


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_the_picture_shows_each_cavity_with_its_wire_or_empty(key, connector):
    """Read back from the drawing: each cavity is one group, holding the wire's number and signal (or
    "empty", and "5 V" over a 5 V pin) and then the pin's own number."""
    plan = steps.housing(wiring.CARRIERS[key], connector)
    pins = wiring.CONNECTORS[connector]["pins"]
    header = RAW[key]["headers"][plan.header]["pins"]
    svg = picture(key, connector)
    groups = dict(re.findall(r'<g id="cavity-(\d+)">(.*?)</g><!--/cavity-->', svg))
    assert sorted(map(int, groups)) == sorted(plan.cavities)
    for pin in plan.cavities:
        inside = words(groups[str(pin)])
        wire = next((s for s, (h, p) in RAW[key]["wires"].items() if (h, p) == (plan.header, pin)), None)
        if wire is not None:
            assert inside == [str(pins.index(wire) + 1), wiring.SIGNALS[wire]["label"], str(pin)], pin
        elif header[str(pin)]["name"].replace(" ", "") == "5V":
            assert inside == ["empty", "5 V", str(pin)], pin
        else:
            assert inside == ["empty", str(pin)], pin
    for sig in plan.cut:  # a cut wire is named in a note, and is in no cavity
        assert any(re.match(rf"wires? .*\b{pins.index(sig) + 1}\b.*: cut back", w) for w in words(svg)), sig


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_the_turned_round_warning_names_a_rail_exactly_when_a_wire_would_land_on_one(key, connector):
    plan = steps.housing(wiring.CARRIERS[key], connector)
    header = RAW[key]["headers"][plan.header]["pins"]
    hits = {
        sig
        for sig, (h, pin) in RAW[key]["wires"].items()
        if h == plan.header
        and sig in wiring.CONNECTORS[connector]["pins"]
        and rail(header[str(plan.first + plan.last - pin)]["name"])
    }
    drawn = " ".join(words(picture(key, connector)))
    assert (re.search(r"Turned round, the housing puts [0-9.]+ V on", drawn) is not None) == bool(hits)
    assert ("Turned round, the housing puts its wires on the wrong pins." in drawn) == (not hits)
    for sig in hits:
        assert re.search(rf"Turned round, the housing puts .*\b{wiring.SIGNALS[sig]['label']}\b", drawn)


def test_which_cables_the_warning_names_a_rail_on():
    """The four cables as wired today: both blade housings reach a 5 V pin when turned, neither Pi 5 one does."""
    warned = {
        (key, connector): steps.turned_warning(wiring.CARRIERS[key], steps.housing(wiring.CARRIERS[key], connector))
        for key, connector in CABLES
    }
    assert warned["blade", "P1"] == "Turned round, the housing puts 5 V on the TCK wire."
    assert warned["blade", "P2"] == "Turned round, the housing puts 5 V on the K2 wire."
    assert warned["pi5", "P1"] == warned["pi5", "P2"] == "Turned round, the housing puts its wires on the wrong pins."


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_every_picture_states_the_view_and_what_is_not_checked(key, connector):
    drawn = words(picture(key, connector))
    text = " ".join(drawn)
    assert "Dupont housing, seen from the wire side," in text
    assert "You are looking down" in drawn
    assert steps.ASSUMED[0] in drawn and steps.ASSUMED[1] in drawn
    assert re.search(r'viewBox="0 0 780 \d+"', picture(key, connector))


def test_the_series_resistor_is_drawn_on_the_cable_that_has_one():
    for key, connector in CABLES:
        c = wiring.CARRIERS[key]
        has = any(s in c.resistors for s in wiring.CONNECTORS[connector]["pins"])
        drawn = words(picture(key, connector))
        assert ("in heat shrink" in drawn) == has, (key, connector)
        assert c.resistor_value in drawn if has else "470 Ω" not in drawn, (key, connector)


def test_the_printed_numbers_run_as_the_board_has_them():
    blade, pi5 = wiring.CARRIERS["blade"], wiring.CARRIERS["pi5"]
    assert blade.headers["ext"].grid(1, 10) == [(1, 6), (2, 7), (3, 8), (4, 9), (5, 10)]
    assert blade.headers["uart"].grid(1, 4) == [(1,), (2,), (3,), (4,)]
    assert pi5.headers["gpio"].grid(5, 10) == [(5, 6), (7, 8), (9, 10)]
    assert pi5.headers["gpio"].count == 40 and len(pi5.headers["gpio"].grid(1, 40)) == 20


def test_a_two_column_header_without_its_numbering_is_refused():
    d = copy.deepcopy(RAW["blade"])
    del d["headers"]["ext"]["numbering"]
    with pytest.raises(wiring.WiringError, match="needs numbering"):
        wiring._carrier("blade", d)
