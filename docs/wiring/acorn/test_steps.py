# SPDX-License-Identifier: Apache-2.0
"""The step pictures say what wiring.toml says.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import copy

import pytest
import steps
import wiring

RAW = wiring.DATA["carriers"]
CABLES = [(key, connector) for key in wiring.CARRIERS for connector in wiring.CONNECTORS]


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


def test_the_printed_numbers_run_as_the_board_has_them():
    blade, pi5 = wiring.CARRIERS["blade"], wiring.CARRIERS["pi5"]
    assert blade.headers["ext"].grid(1, 10) == [(1, 6), (2, 7), (3, 8), (4, 9), (5, 10)]
    assert blade.headers["uart"].grid(1, 4) == [(1,), (2,), (3,), (4,)]
    assert pi5.headers["gpio"].grid(5, 10) == [(5, 6), (7, 8), (9, 10)]


def test_a_two_column_header_without_its_numbering_is_refused():
    d = copy.deepcopy(RAW["blade"])
    del d["headers"]["ext"]["numbering"]
    with pytest.raises(wiring.WiringError, match="needs numbering"):
        wiring._carrier("blade", d)


def test_the_blade_p1_picture_labels_every_wire_and_every_empty_cavity():
    c = wiring.CARRIERS["blade"]
    svg, _ = steps.cable(c, "P1", steps.CABLES[("blade", "P1")])
    plan = steps.housing(c, "P1")
    pins = wiring.CONNECTORS["P1"]["pins"]
    for pin, sig in plan.cavities.items():
        name = c.headers["ext"].pins[pin]["name"].replace("5V", "5 V").replace("3.3V", "3.3 V")
        if sig is None:
            assert f'aria-label="empty: {name}"' in svg, pin
        else:
            assert svg.count(f'aria-label="wire {pins.index(sig) + 1}"') == 1, sig
            assert svg.count(f'aria-label="pin {pin} {name}"') == 1, sig
    assert svg.count('aria-label="empty: 5 V"') == 2
    assert 'aria-label="wire 6: cut back, heat shrink over the end"' in svg
    assert 'viewBox="0 0 950 900"' in svg
