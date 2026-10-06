# SPDX-License-Identifier: Apache-2.0
"""The step pictures say what wiring.toml says.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import copy
import functools
import re

import pytest
import steps
import tables
import wiring

RAW = wiring.DATA["carriers"]
CABLES = [(key, connector) for key in wiring.CARRIERS for connector in wiring.CONNECTORS]
RAILS = ("5V", "3.3V")
CUT = wiring.LENGTHS["cut_back"]


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
        assert any(re.match(rf"wires? .*\b{pins.index(sig) + 1}\b.*: cut off about {CUT} mm", w) for w in words(svg)), (
            sig
        )


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


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_the_prepare_picture_cuts_exactly_the_cut_wires_and_puts_a_terminal_on_the_rest(key, connector):
    c = wiring.CARRIERS[key]
    pins = wiring.CONNECTORS[connector]["pins"]
    svg = steps.prepare(c, connector)
    wired = {pins.index(s) + 1 for s in pins if s in RAW[key]["wires"]}
    assert {int(n) for n in re.findall(r'<g id="terminal-wire-(\d+)">', svg)} == wired
    cut = set()
    for note in words(svg):
        m = re.match(rf"wires? ([\d and]+): cut off about {CUT}\b", note)
        if m:
            cut |= {int(n) for n in re.findall(r"\d+", m.group(1))}
    assert cut == set(range(1, len(pins) + 1)) - wired
    # the resistor: on exactly the wires wiring.toml lists for this carrier, if they are in this cable
    resistors = {pins.index(s) + 1 for s in RAW[key].get("resistors", []) if s in pins}
    assert {int(n) for n in re.findall(r'<g id="resistor-wire-(\d+)">', svg)} == resistors


def test_the_series_resistor_is_prepared_on_wire_2_of_the_blade_p2_cable_only():
    found = {
        (key, connector): re.findall(r'<g id="resistor-wire-(\d+)">', steps.prepare(wiring.CARRIERS[key], connector))
        for key, connector in CABLES
    }
    assert found == {("blade", "P2"): ["2"], ("blade", "P1"): [], ("pi5", "P1"): [], ("pi5", "P2"): []}


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_procedure_is_complete_in_itself(key):
    c = wiring.CARRIERS[key]
    text = steps.procedure(c)
    built = set(steps.build_names())
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    for image in images:
        assert "/" not in image  # by bare file name, in the same directory
        assert image.replace(".png", ".svg") in built or image.startswith("acorn-wiring-"), image
    for connector in wiring.CONNECTORS:
        cavity = steps.file_name(c, connector).replace(".svg", ".png")
        assert images.count(cavity) == 3  # where the housing is filled, where it is checked, where it is fitted
        assert steps.prepare_name(c, connector).replace(".svg", ".png") in images
        assert steps.turned_warning(c, steps.housing(c, connector))[:-1] in text
    assert tables.bom(c).strip() in text  # the parts list itself, not a link to it
    assert "it must never reach the host" in text
    prose = "\n".join(line for line in text.splitlines() if not line.startswith("|"))  # the parts tables apart
    assert not re.search(r"^#{1,2} ", text, re.M) and "—" not in prose and "see above" not in text.lower()
    assert text.rstrip().endswith(gen_credits(key) + ".")
    assert ("Solder the 470 Ω resistor between the two cut ends." in text) == bool(RAW[key].get("resistors"))
    assert ("heat-shrink tube, about 3 mm" in text) == bool(RAW[key].get("resistors"))
    assert text.count("which can destroy the host") == sum(
        "puts 5 V on" in steps.turned_warning(c, steps.housing(c, conn)) for conn in wiring.CONNECTORS
    )
    assert f"about {CUT} mm from the plug" in text and "buy a few more than this, as spares" in text
    assert (
        text.index("Slide a piece of the 3 mm tube") < text.index("Solder the") if RAW[key].get("resistors") else True
    )


def gen_credits(key):
    import gen

    return gen.CREDITS[key]


@pytest.mark.parametrize(("key", "connector"), CABLES)
def test_cavities_are_drawn_where_the_header_has_them_and_each_wire_ends_at_its_own(key, connector):
    c = wiring.CARRIERS[key]
    plan = steps.housing(c, connector)
    pins = wiring.CONNECTORS[connector]["pins"]
    svg = picture(key, connector)
    at = {}
    for pin, x, y, w, h in re.findall(
        r'<g id="cavity-(\d+)"><rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg
    ):
        at[int(pin)] = (float(x), float(y), float(x) + float(w), float(y) + float(h))
    grid = c.headers[plan.header].grid(plan.first, plan.last)
    assert sorted(at) == sorted(n for row in grid for n in row)
    for r, row in enumerate(grid):
        assert len({at[n][1] for n in row}) == 1  # one row, one height
        assert [at[n][0] for n in row] == sorted(at[n][0] for n in row)  # left to right as the header has them
        if r:
            assert at[row[0]][1] > at[grid[r - 1][0]][1]  # rows downwards
    for col in range(len(grid[0])):
        assert len({at[row[col]][0] for row in grid}) == 1  # one column, one x
    ends = {
        int(n): (float(x), float(y)) for n, x, y in re.findall(r'id="wire-(\d+)-end" cx="([\d.]+)" cy="([\d.]+)"', svg)
    }
    wired = {pins.index(s) + 1: pin for s, (h, pin) in RAW[key]["wires"].items() if s in pins}
    assert sorted(ends) == sorted(wired)
    for number, (x, y) in ends.items():
        own = [n for n, (x0, y0, x1, y1) in at.items() if x0 - 1 <= x <= x1 + 1 and y0 <= y <= y1]
        assert own == [wired[number]], number


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_last_step_fits_plugs_then_card_then_both_housings_on_their_headers(key):
    c = wiring.CARRIERS[key]
    last = steps.procedure(c).split("Fit the cables, in this order.")[1]
    assert steps.fit_block(c).rstrip() in last and steps.png(steps.fit_name(c)) in last
    assert "ground-check.png" not in last
    assert (wiring.HERE / "generated" / f"acorn-fit-{key}.md").read_text().endswith(steps.fit_block(c))
    order = [
        last.index(s) for s in (c.power_off, "take them off", "Press the P1 plug", "Put the Acorn in the M.2 slot")
    ]
    assert order == sorted(order)
    for connector in wiring.CONNECTORS:
        plan = steps.housing(c, connector)
        fit = f"the {connector} housing on the {c.headers[plan.header].name}"
        assert last.index(fit) > order[-1]
        assert f"marked corner on pin {plan.first}" in last


def test_the_ground_check_is_in_each_flag_step_and_on_the_box():
    for c in wiring.CARRIERS.values():
        text = steps.procedure(c)
        for connector in wiring.CONNECTORS:
            assert text.count(steps.png(steps.ground_check_name(connector))) == 1
        assert text.count("If wire 6 beeps instead, stop") == len(wiring.CONNECTORS)
        assert text.count(f"about {wiring.LENGTHS['flag_back']} mm back from the tip") == len(wiring.CONNECTORS)
        assert text.count("Every other cavity must stay silent for that contact.") == len(wiring.CONNECTORS)
        assert "This is a bench check; the housings come off again before the cables are fitted." in text
        assert ("Trim the resistor's leads to about" in text) == bool(c.resistors)
        assert text.index("If wire 6 beeps instead") < text.index("Cut wire")
    assert any("mounting pad is ground" in item and "not measured" in item for item in steps.ASSUMPTIONS)
    assert wiring.LENGTHS["flag_back"] > wiring.LENGTHS["resistor"]


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_flag_step_shows_whole_wires_and_the_cut_picture_comes_only_after_the_meter_check(key):
    """The meter check exists so that the wire cut is the 3.3 V one: no picture before it may show a wire cut."""
    c = wiring.CARRIERS[key]
    text = steps.procedure(c)
    for connector in wiring.CONNECTORS:
        flag_step = text.split(f"Find wire 1 of the {connector} cable")[1].split("\n**")[0]
        images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", flag_step)
        assert images == [steps.png(steps.flag_name(connector)), steps.png(steps.ground_check_name(connector))]
        prepared = steps.png(steps.prepare_name(c, connector))
        assert text.count(prepared) == 1
        assert text.index(prepared) > text.index(steps.png(steps.ground_check_name(connector)))
        cut_step = text[: text.index(prepared)].rsplit("\n**", 1)[1]
        assert "off about" in cut_step and "in no cavity" in cut_step


@pytest.mark.parametrize("connector", list(wiring.CONNECTORS))
def test_the_flag_and_meter_pictures_draw_every_wire_whole_with_its_flag(connector):
    count = len(wiring.CONNECTORS[connector]["pins"])
    for draw in (steps.flag, steps.ground_check):
        svg = draw(connector)
        assert re.findall(r'<g id="flag-wire-(\d+)">', svg) == [str(n) for n in range(1, count + 1)]
        assert "terminal-wire-" not in svg and "resistor-wire-" not in svg
        # six wires of one length, from the plug to their cut faces
        wires = re.findall(
            rf'<line x1="([\d.]+)" y1="([\d.]+)" x2="\1" y2="([\d.]+)" stroke="{steps.BODY}" '
            rf'stroke-width="{steps.WIRE}"/>',
            svg,
        )
        assert len(wires) == count and len({(y0, y1) for _x, y0, y1 in wires}) == 1
        assert float(wires[0][2]) - float(wires[0][1]) == steps.FLAG_WIRE


def test_a_repeated_cavity_picture_says_why_it_is_there_again():
    for c in wiring.CARRIERS.values():
        lines = steps.procedure(c).splitlines()
        for connector in wiring.CONNECTORS:
            cavity = steps.png(steps.file_name(c, connector))
            at = [i for i, line in enumerate(lines) if f"]({cavity})" in line]
            assert len(at) == 3
            for i in at[1:]:
                assert lines[i - 2].startswith(f"The {connector} cavity picture again")


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_guides_pages_hold_every_step_of_the_procedure_once_each_numbered_from_one(key):
    c = wiring.CARRIERS[key]
    pages = steps.guide(c)
    names = ["overview", "jtag-1", "jtag-2", "uart-1", "uart-2", "bench", "fit"]
    assert list(pages) == [steps.guide_name(c, n) for n in names]
    whole = [re.sub(r"^\*\*\d+\.\*\* ", "", line) for line in steps.procedure(c).splitlines() if line.startswith("**")]
    paged = []
    for name, body in pages.items():
        numbered = re.findall(r"^\*\*(\d+)\.\*\* (.*)$", body, re.M)
        assert [int(n) for n, _ in numbered] == list(range(1, len(numbered) + 1)), name  # from 1, no gap
        paged += [words for _, words in numbered]
        assert body.startswith(tables.BANNER.strip()) and "Not yet run by us on this hardware" in body
        assert not re.search(r"^#{1,1} |^#### ", body, re.M), name  # headings from level 2; no cable heading left over
        for image in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body):
            assert "/" not in image, image
    assert paged == whole  # every step, in order, nothing twice
    # no page points at a step that is on another page
    for name, body in pages.items():
        assert "next step" not in body and "step before" not in body.replace("in the step before.", ""), name
    overview = pages[steps.guide_name(c, "overview")]
    mine = [s for s in wiring.SOURCES if s.get("carrier", key) == key]
    others = [s for s in wiring.SOURCES if s.get("carrier", key) != key]
    assert mine and all(f"- {s['claim']}: " in overview for s in mine) and "has not been measured by us" in overview
    assert others and not any(s["claim"] in overview for s in others)  # nothing about the other carrier
    assert all(s.get("carrier") in (None, *wiring.CARRIERS) for s in wiring.SOURCES)
    for part in ("jtag-1", "uart-1", "bench", "fit"):  # the photo credit is not left to be the last line of a page
        assert pages[steps.guide_name(c, part)].count("Photos: ") == 1
        assert not pages[steps.guide_name(c, part)].rstrip().endswith("same PCB).")
    # a fitted card comes out, with the power off, before a cable's first step; the cuts the guide does make are named
    for part in ("jtag-1", "uart-1"):
        need = pages[steps.guide_name(c, part)]
        assert f"if it is fitted, {c.power_off[0].lower()}{c.power_off[1:]} Then take the card out." in need
    assert "cut in half, once" in overview
    assert ("the one wire that is cut to take the resistor" in overview) == bool(c.resistors)
    if c.resistors:
        assert f"lands on GPIO14, which is also JTAG TMS: with {c.resistor_value} in the wire" in steps.procedure(c)
    # the meter check of wire 1 is on the page that cuts wires, before the cut
    for part in ("jtag-1", "uart-1"):
        body = pages[steps.guide_name(c, part)]
        assert body.index("ground-check.png") < body.index("off about") and "## What you need" in body
    for part in ("jtag-2", "uart-2"):
        assert "Hold the empty" in pages[steps.guide_name(c, part)]
    assert "Fit the cables, in this order" in pages[steps.guide_name(c, "fit")]
    assert "This is a bench check" in pages[steps.guide_name(c, "bench")]
