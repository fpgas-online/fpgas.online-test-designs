# SPDX-License-Identifier: Apache-2.0
"""The step pictures say what wiring.toml says.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import copy
import functools
import html
import re

import check
import pages as docs_pages
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


def light_images(text):
    """The pictures of Markdown text, each once: the light PNG of every light and dark pair (test_palette.py)."""
    return [i for i in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text) if not i.endswith("-dark.png")]


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
def test_every_picture_states_the_view_and_sends_the_reader_to_the_check_of_wire_one(key, connector):
    drawn = words(picture(key, connector))
    text = " ".join(drawn)
    assert "Dupont housing, seen from the wire side," in text
    assert "You are looking down" in drawn
    assert "Not yet checked" not in text and "taken to be" not in text  # what it assumes is the bench run's
    assert html.escape(steps.assumed_check(wiring.CARRIERS[key], connector), quote=False) in drawn
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
    images = light_images(text)
    for image in images:
        assert "/" not in image  # by bare file name, in the same directory
        assert image.replace(".png", ".svg") in built or image.startswith("acorn-wiring-"), image
    for connector in wiring.CONNECTORS:
        cavity = steps.file_name(c, connector).replace(".svg", ".png")
        # where the housing is filled, where its terminals are pushed in, where it is checked, where it is fitted
        assert images.count(cavity) == 4
        assert steps.prepare_name(c, connector).replace(".svg", ".png") in images
        assert steps.turned_warning(c, steps.housing(c, connector))[:-1] in text
    assert tables.bom(c).strip() in text  # the parts list itself, not a link to it
    assert "it must never reach the host" in text
    prose = "\n".join(line for line in text.splitlines() if not line.startswith("|"))  # the parts tables apart
    assert not re.search(r"^#{1,2} ", text, re.M) and "—" not in prose and "see above" not in text.lower()
    assert text.rstrip().endswith(gen_credits(key) + ".")
    assert ("Solder the 470 Ω resistor between the two cut ends." in text) == bool(RAW[key].get("resistors"))
    assert ("heat-shrink tube, about 3 mm" in text) == bool(RAW[key].get("resistors"))
    building = text.replace(steps.fit_actions(c)[-1], "")  # the fitting look says it again, for both
    assert building.count(f", {steps.HARM}.") == sum(
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
    last = steps.procedure(c).split(steps.FIT_STEPS[0])[1]
    assert all(steps.png(n) in last for n in steps.fit_names(c))
    actions = steps.fit_actions(c)
    assert all(f"\n{n}. {action}\n" in last for n, action in enumerate(actions, 1))
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


def test_the_look_before_power_names_each_marked_pin_and_says_what_a_turned_housing_does():
    """The last fitting action, per carrier, from the wiring: a Pi 5 housing has no 5 V to turn onto."""
    assert steps.HARM.endswith("which can destroy the FPGA pin on the Acorn that wire reaches")
    assert "DS181, Table 1" in steps.HARM  # the limit it is over, with its source
    for c in wiring.CARRIERS.values():
        last = steps.fit_actions(c)[-1]
        assert last.startswith("Before powering on, look at both housings again")
        for connector in wiring.CONNECTORS:
            plan = steps.housing(c, connector)
            assert f"pin {plan.first} of the {c.headers[plan.header].name}" in last
    pi5 = steps.fit_actions(wiring.CARRIERS["pi5"])[-1]
    assert "5 V" not in pi5 and steps.HARM not in pi5
    assert "marked corner is on pin 19 of the 40-pin header" in pi5 and "P2 housing's on pin 5 of the" in pi5
    assert "Turned round, either housing puts its wires on the wrong pins." in pi5
    blade = steps.fit_actions(wiring.CARRIERS["blade"])[-1]
    assert "P1 housing's marked corner is on pin 1 of the Extension Port" in blade
    assert "P2 housing's on pin 1 of the UART" in blade
    assert (
        "Turned round, the P1 housing puts 5 V on the TCK wire and the P2 housing puts 5 V on the K2 wire, "
        f"{steps.HARM}." in blade
    )


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_fitting_picture_draws_every_action_of_the_list_beside_it_with_its_number(key):
    c = wiring.CARRIERS[key]
    actions = steps.fit_actions(c)
    for half, numbers in enumerate(steps.FIT_HALVES, 1):
        svg = steps.fit(c, half)
        assert re.findall(r'<circle id="action-(\d+)"', svg) == [str(n) for n in numbers]
        drawn = " ".join(words(svg))
        for n in numbers:
            assert actions[n - 1] in drawn, actions[n - 1]


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_each_half_of_the_fitting_picture_follows_its_own_three_actions(key):
    """Each half is printed with its three actions, so that a half and its words fit on one sheet."""
    c = wiring.CARRIERS[key]
    block = steps.fit_block(c)
    one, two = (block.index(steps.png(n)) for n in steps.fit_names(c))
    actions = steps.fit_actions(c)
    assert block.index("1. ") < block.index(f"3. {actions[2]}") < one < block.index(steps.FIT_SECOND)
    assert block.index(steps.FIT_SECOND) < block.index(f"4. {actions[3]}") < block.index(f"6. {actions[5]}") < two


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_finished_wiring_sheet_is_on_the_overview_not_on_the_fitting_page(key):
    c = wiring.CARRIERS[key]
    pages = steps.guide(c)
    sheet = f"{steps.SHEETS[key]}.png"
    assert sheet in pages[steps.guide_name(c, "overview")]
    fit = pages[steps.guide_name(c, "fit")]
    assert sheet not in fit and "finished wiring" not in fit.lower()
    assert steps.procedure(c).count(f"({sheet})") == 1


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
    assert wiring.LENGTHS["flag_back"] > wiring.LENGTHS["resistor"]


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_flag_step_shows_whole_wires_and_the_cut_picture_comes_only_after_the_meter_check(key):
    """The meter check exists so that the wire cut is the 3.3 V one: no picture before it may show a wire cut."""
    c = wiring.CARRIERS[key]
    text = steps.procedure(c)
    for connector in wiring.CONNECTORS:
        flag_step = text.split(f"Find wire 1 of the {connector} cable")[1].split("\n**")[0]
        assert light_images(flag_step) == [steps.png(steps.flag_name(connector))]
        check_step = text.split(f"Check which wire of the {connector} cable is wire 1")[1].split("\n**")[0]
        assert light_images(check_step) == [steps.png(steps.ground_check_name(connector))]
        assert text.index(flag_step) < text.index(check_step)  # flagged first, then checked
        assert "Take the plug out again." in check_step and "Put a numbered tape flag" in flag_step
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
            rf'<line x1="([\d.]+)" y1="([\d.]+)" x2="\1" y2="([\d.]+)" stroke="{steps.BLACK_WIRE}" '
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
            assert len(at) == 4  # filled, pushed in, checked, and fitted on the bench check
            for i in at[1:]:
                # the step's own words say why
                words = next(line for line in reversed(lines[:i]) if line.startswith("**"))
                assert f"The {connector} cavity picture is shown again" in words, words


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
        # the one line that warns the reader, naming the issue of the bench run; nothing else about what is unproven
        assert body.startswith(tables.BANNER.strip()) and body.count(steps.bench_run(c)) == 1
        assert "Not yet run by us" not in body and "written from the design" not in body
        assert not re.search(r"^#{1,1} |^#### ", body, re.M), name  # headings from level 2; no cable heading left over
        for image in light_images(body):
            assert "/" not in image, image
    assert paged == whole  # every step, in order, nothing twice
    # no page points at a step that is on another page
    for name, body in pages.items():
        assert "next step" not in body and "step before" not in body.replace("in the step before.", ""), name
    overview = pages[steps.guide_name(c, "overview")]
    mine = [s for s in wiring.SOURCES if s.get("carrier", key) == key]
    others = [s for s in wiring.SOURCES if s.get("carrier", key) != key]
    # the claims and their sources are the review's record (wiring.toml), not a section of the page
    assert mine and others and "Where the facts come from" not in overview and "Sources" not in overview
    assert not any(f"- {s['claim']}: " in overview for s in wiring.SOURCES)
    assert all(s.get("carrier") in (None, *wiring.CARRIERS) for s in wiring.SOURCES)
    for part in ("jtag-1", "uart-1", "bench", "fit"):  # the photo credit is not left to be the last line of a page
        assert pages[steps.guide_name(c, part)].count("Photos: ") == 1
        assert not pages[steps.guide_name(c, part)].rstrip().endswith("same PCB).")
    # a fitted card comes out, with the power off, before a cable's first step; the cuts the guide does make are named
    for part in ("jtag-1", "uart-1"):
        first_step = dict(step_blocks(pages[steps.guide_name(c, part)]))[1]
        assert first_step.startswith(f"**1.** {steps.CARD_OUT_STEP}")
        assert f"If it is fitted, {c.power_off[0].lower()}{c.power_off[1:]} Then take the card out." in first_step
        assert steps.STATIC in first_step
    assert "cut in half, once" in overview
    # the reach check is asked for at a moment the guide has: after the one cut, before any wire is cut back
    assert "before you cut anything" not in overview and "first step" not in overview
    assert "second step" not in overview  # a step is quoted by its number, which the generator counts
    first = pages[steps.guide_name(c, "jtag-1")]
    cut, reach = first.index("Cut the Molex cable in half"), first.index("Check that each half reaches")
    flag = first.index("flag the wires")
    assert cut < reach < flag  # after the one cut, before the first wire is flagged, cut back or crimped
    (reach_step,) = (b for _, b in step_blocks(first) if "Check that each half reaches" in b.split("\n", 1)[0])
    assert "in its slot" not in reach_step.replace("out of its slot", "")  # the card is out of its slot then
    for k in wiring.CONNECTORS:  # each half named with its own header
        assert (
            f"the half for {k} from socket {k} to the {steps.header_words(c.headers[steps.housing(c, k).header].name)}"
            in reach_step
        )
    numbers = [int(n) for n in re.findall(r"^\*\*(\d+)\.\*\*", steps.procedure(c), re.M)]
    assert numbers == list(range(1, len(numbers) + 1))  # the whole procedure numbered 1 to N
    # the wire-1 check has an outcome for every result, and says what the last wire's silence rests on
    for part in ("jtag-1", "uart-1"):
        body = pages[steps.guide_name(c, part)]
        assert "If both still beep, stop and cut nothing" in body and "expected to stay silent to ground" in body
        assert f"send both readings to {c.contact}." in body
        assert "If neither wire beeps" in body and "beeps instead, stop" in body
    # whom to tell is the carrier's, by role: the site operator for the ps1 blades, the public wording for the Pi 5
    assert c.contact == {"blade": "the site operator", "pi5": wiring.CONTACT}[c.key]
    assert f"Tell {c.contact}." in reach_step
    # a wire with the series resistor in it is not told to beep: its page gives the reading to expect
    for part, connector in (("jtag-2", "P1"), ("uart-2", "P2")):
        body = pages[steps.guide_name(c, part)]
        has = steps.through_resistor(c, connector)
        assert bool(has) == any(s in c.resistors for s in wiring.CONNECTORS[connector]["pins"])
        n = steps.resistor_wire(c, connector)
        assert (n is not None) == bool(has)
        own = steps.png(f"acorn-cable-check-{key}-{connector.lower()}.svg")
        assert (own in body) == bool(has) and ("(acorn-cable-check.png)" in body) != bool(has)
        if has:
            j2 = wiring.CONNECTORS[connector]["pins"].index("J2") + 1  # the resistor is in the J2 wire
            assert n == j2 and f"Wire {j2} is the exception" in body and f"Leave wire {j2} until last" in body
            assert f"it must read close to {c.resistor_value}" in body and "it must show over-range" in body
            assert "touch the two probes together first" in body
            picture = steps.build()[steps.check_name(c, connector)]
            assert f"Wire {j2} has the" in picture and "It will not beep" in picture
    assert "resistor" not in steps.check_picture()  # the shared picture names no exception
    for connector in wiring.CONNECTORS:
        # the wire-1 picture leaves what to do when the check proves nothing to its step's words, on its sheet
        picture = " ".join(words(steps.ground_check(connector)))
        assert steps.NOT_TOLD_APART in picture and "If both still beep" not in picture and "send" not in picture
        assert "shows only that wire 1 and the pad are joined" in picture and "by us" not in picture
    assert ("the one wire that is cut to take the resistor" in overview) == bool(c.resistors)
    if c.resistors:
        said = (
            f"lands on GPIO14, which is also JTAG TMS: the {c.resistor_value} in the wire is meant to let JTAG through"
        )
        assert said in steps.procedure(c)
    # the meter check of wire 1 is on the page that cuts wires, before the cut
    for part in ("jtag-1", "uart-1"):
        body = pages[steps.guide_name(c, part)]
        assert body.index("ground-check.png") < body.index("off about") and "## What you need" in body
    for part in ("jtag-2", "uart-2"):
        assert "Hold the empty" in pages[steps.guide_name(c, part)]
    assert all(
        f"**{steps.fit_step(c, half)}.** {words}" in pages[steps.guide_name(c, "fit")]
        for half, words in enumerate(steps.FIT_STEPS, 1)
    )
    assert "This is a bench check" in pages[steps.guide_name(c, "bench")]
    # the ground beep is never given as proof of which way round a housing is: the marked corner is
    bench = pages[steps.guide_name(c, "bench")]
    assert "The beep also shows" not in bench and "meant to show" not in bench and "would then stay silent" not in bench
    for connector in wiring.CONNECTORS:
        assert (
            f"The beep does not show which way round the {connector} housing is" in bench
            or "The beep does not show which way round either housing is" in bench
            or f"the {connector} housing's GND wire would sit on" in bench
        )
    assert "marked corner" in steps.ground_shows_way_round(c)
    said = steps.ground_shows_way_round(c)  # one sentence where both housings behave alike, not the same one twice
    assert len(set(re.split(r"(?<=\.) ", re.sub(r"\bP[12]\b", "P", said)))) == len(re.split(r"(?<=\.) ", said))


def step_blocks(body):
    """[(the step's number, its text and pictures)] of a page, up to the next step or heading."""
    at = [m.start() for m in re.finditer(r"^\*\*\d+\.\*\* ", body, re.M)]
    blocks = []
    for i, start in enumerate(at):
        end = at[i + 1] if i + 1 < len(at) else len(body)
        heading = re.search(r"^## ", body[start:end], re.M)
        block = body[start : start + heading.start()] if heading else body[start:end]
        blocks.append((int(re.match(r"\*\*(\d+)", block).group(1)), block))
    return blocks


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_every_step_of_the_building_pages_has_one_picture_of_its_own(key):
    """A printed step keeps its words and its picture on one sheet, so a step has one new picture.

    The one exception: a cavity picture shown again, with words saying why (pushing the terminals in and the meter
    check, to read each wire's cavity from, and the bench check). Fitting is two steps, one picture each."""
    c = wiring.CARRIERS[key]
    cavities = {steps.png(steps.file_name(c, k)): k for k in wiring.CONNECTORS}
    seen = set()
    for name, body in steps.guide(c).items():
        for n, block in step_blocks(body):
            lines = block.splitlines()
            fresh = []
            for i, line in enumerate(lines):
                for image in light_images(line):
                    k = cavities.get(image)
                    said = f"The {k} cavity picture is shown again" in lines[0] or (
                        i >= 2 and lines[i - 2].startswith(f"The {k} cavity picture again")
                    )
                    if not (image in seen and said):
                        fresh.append(image)
                    seen.add(image)
            assert len(fresh) <= 1, (name, n, fresh)
    pages = steps.guide(c)
    fit = pages[steps.guide_name(c, "fit")]
    assert [light_images(block) for _, block in step_blocks(fit)] == [[steps.png(f)] for f in steps.fit_names(c)]
    # the bench check: each housing with its cavity picture, then the beeps with theirs, one picture to a step
    bench = pages[steps.guide_name(c, "bench")]
    assert [light_images(block) for _, block in step_blocks(bench)] == [
        *([steps.png(steps.file_name(c, k))] for k in wiring.CONNECTORS),
        [steps.png(steps.shell_check_name(c))],
    ]
    assert [steps.bench_step(c, steps.BENCH_START), steps.bench_step(c, steps.BENCH_BEEP)] == [1, 3]


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_no_words_stand_between_a_steps_pictures(key):
    """A step is its words (a paragraph and any list), then its pictures, with nothing between or after them: the
    print tool keeps on one sheet only the pictures that follow a step's words directly (fpgas.online-docs #102)."""
    c = wiring.CARRIERS[key]
    for name, body in steps.guide(c).items():
        for n, block in step_blocks(body):
            lines = [line for line in block.splitlines() if line]
            first = next((i for i, line in enumerate(lines) if line.startswith("![")), len(lines))
            assert all(line.startswith("![") for line in lines[first:]), (name, n)
            assert all(re.match(r"\d+\. ", line) for line in lines[1:first]), (name, n)


def quotes(c):
    """[(file, the key of the page quoted, the step numbers)] of every quote of a building page's step by its
    number: in the check's and the verify pages, in the generated pages and in the pictures of carrier `c`.

    Words quote a step as "steps 3 and 4 of <a link to the page>" (pages.link); a picture, which cannot link, as
    "step 4 of preparing this cable's wires", which is the first page of the cable the picture is of."""
    docs = wiring.HERE.parent.parent
    texts = [*sorted((docs / "verify").glob("*.md")), *sorted((wiring.HERE / "check").glob("*.md"))]
    texts += sorted((wiring.HERE / "generated").glob("*.md"))
    texts += sorted((wiring.HERE / "generated").glob(f"acorn-cable-{c.key}-*.svg"))
    by_address = {docs_pages.url(c.key, page): page for key, page in docs_pages.every() if key == c.key}
    linked = r"steps? (\d+)(?: and (\d+))? of \[[^\]]+\]\((https://[^)\s]+)\)"
    drawn = r"steps? (\d+)(?: and (\d+))? of preparing this cable(?:'|&#x27;|&apos;)s wires"
    found = []
    for f in texts:
        if f.name.startswith("acorn-check-") and f"-{c.key}-" not in f.name:
            continue
        text = f.read_text()
        for a, b, address in re.findall(linked, text):
            if address in by_address:  # a link to the other carrier's page is that carrier's quote
                found.append((f.name, by_address[address], [int(a)] + ([int(b)] if b else [])))
        for a, b in re.findall(drawn, text):  # only a cable's own picture says this: its name has the connector
            (part,) = (part for connector, (part, _) in steps.GUIDE.items() if f"-{connector.lower()}" in f.name)
            found.append((f.name, f"{part}-1", [int(a)] + ([int(b)] if b else [])))
    return found


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_a_quoted_step_number_is_the_step_it_means(key):
    """Pages and pictures that send the reader to a step of a building page quote its number: it is that step.

    The meter check of a finished cable (connector 2), the meter check of wire 1 (connector 1) and the fitting
    steps."""
    c = wiring.CARRIERS[key]
    n = steps.meter_check_step(c)
    pages = steps.guide(c)
    for connector, (part, title) in steps.GUIDE.items():
        assert steps.step_number(c, f"{part}-2", steps.CHECK_EACH) == n
        assert steps.step_number(c, f"{part}-2", steps.CHECK_CAVITY) == n + 1
        assert f"**{n}.** {steps.CHECK_EACH}" in pages[steps.guide_name(c, f"{part}-2")]
        w1, page = steps.wire_one_step(c, connector)
        assert page == f"{part}-1" and docs_pages.title(c.key, page).startswith(f"How to prepare the {title} cable")
        assert f"**{w1}.** {steps.wire_one_check(connector)}" in pages[steps.guide_name(c, f"{part}-1")]
    fit = [steps.fit_step(c, half) for half in (1, 2)]
    assert fit == [1, 2]
    meant = {f"{part}-2": [[n, n + 1]] for part, _ in steps.GUIDE.values()}
    meant |= {f"{steps.GUIDE[k][0]}-1": [[steps.wire_one_step(c, k)[0]]] for k in wiring.CONNECTORS}
    # the overview quotes the first page's one cut and its reach check; "Step N of that page" is the same page
    first = steps.guide(c)[steps.guide_name(c, "jtag-1")].splitlines()
    cut, reach = steps.numbered(first, steps.CUT_HALF), steps.numbered(first, steps.REACH)
    meant["jtag-1"] += [[cut]]
    overview = steps.guide(c)[steps.guide_name(c, "overview")]
    assert f", in step {cut} of {docs_pages.link(c.key, 'jtag-1')}." in overview
    assert f"Step {reach} of that page checks that each half reaches" in overview and reach == cut + 1
    meant["fit"] = [[f] for f in fit]
    meant["check-3"] = [list(check.jtag_steps())]  # the two checks of GPIO14, on the page about JTAG on a blade
    bench = [steps.bench_step(c, w) for w in (steps.BENCH_START, steps.BENCH_BEEP)]
    meant["bench"] = [[b] for b in bench]
    quoted = quotes(c)
    assert {page for _, page, _ in quoted} >= {"jtag-1", "uart-1", "jtag-2"}
    for name, page, numbers in quoted:
        assert numbers in meant[page], (name, page, numbers)


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_reach_step_has_its_own_picture(key):
    c = wiring.CARRIERS[key]
    body = steps.guide(c)[steps.guide_name(c, "jtag-1")]
    blocks = dict(step_blocks(body))
    (block,) = (b for n, b in blocks.items() if b.startswith(f"**{n}.** Check that each half reaches"))
    assert light_images(block) == [steps.png(steps.reach_name(c))]
    assert steps.reach_name(c) in steps.build_names() and steps.reach_name(c) in steps.build()


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_no_page_has_a_beep_show_that_ground_is_ground(key):
    """Wire 1's beep to the pad (and contact 1's to the shell) only shows they are joined: ground is taken as given."""
    c = wiring.CARRIERS[key]
    texts = [*steps.guide(c).values(), steps.procedure(c)]
    for text in texts:
        flat = " ".join(text.split())
        assert "beep shows it" not in flat and "beep is what shows it" not in flat and "is what shows it" not in flat
        assert "reaches nothing" not in flat
    bench = " ".join(steps.guide(c)[steps.guide_name(c, "bench")].split())
    assert "shows only that contact 1 and the shell are joined" in bench
    for connector in wiring.CONNECTORS:
        assert "shows only that wire 1 and the pad are joined" in " ".join(words(steps.ground_check(connector)))


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_bench_steps_words_say_what_their_picture_shows(key):
    c = wiring.CARRIERS[key]
    bench = steps.guide(c)[steps.guide_name(c, "bench")]
    assert "where its housing sits" not in bench
    for k in wiring.CONNECTORS:
        assert (
            f"The {k} cavity picture is shown again below, for which wire goes in which cavity, and which corner"
            in bench
        )


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_taking_the_card_out_says_only_what_the_repo_records(key):
    c = wiring.CARRIERS[key]
    for part in ("jtag-1", "uart-1", "bench"):
        page = steps.guide(c)[steps.guide_name(c, part)]
        assert steps.card_out(c) in page, part
    out = steps.card_out(c)
    assert "by us" not in out and out.count("](https://") == 1  # one link, to the maker's own page
    if key == "blade":  # the PH1 screwdriver is in the parts list
        assert "PH1" in out and "uptime-lab/compute-blade" in out and "assembly guide" in out
    else:  # no screw size or driver for the Pi 5's HAT is recorded: the bench run's issue has it
        assert "PH1" not in out and "M2" not in out and "SSD mounting screw" in out and "waveshare.com" in out


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_putting_the_card_back_is_from_the_makers_pages_and_the_bench_intro_orders_screw_then_card(key):
    c = wiring.CARRIERS[key]
    action = steps.fit_actions(c)[3]
    if key == "blade":
        for words in ("standoff", "5 mm hex driver", "nylon washer", "30° angle", "press down", "PH1 driver"):
            assert words in action
        assert any("assembly.mdx" in s["source"] for s in wiring.SOURCES if s.get("carrier") == "blade")
    else:
        assert "SSD mounting screw" in action and "by us" not in action
        assert any("SSD mounting screw x1" in s["source"] for s in wiring.SOURCES if s.get("carrier") == "pi5")
    intro = steps.guide(c)[steps.guide_name(c, "bench")]
    assert "take it out first" not in intro and "if it is fitted, take it out. Take " in intro
    assert steps.REACH_NOTE.count("not drawn") == 1


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_the_bench_run_line_names_the_carrier_s_issue(key):
    """During the docs rework a build page warns once, at its top, that nobody has followed it on the hardware,
    and names the issue of the bench run that will confirm or remove it."""
    c = wiring.CARRIERS[key]
    issue = steps.BENCH_RUN[key]
    assert steps.bench_run(c) == (
        f"This procedure is waiting for its bench run: [issue #{issue}]"
        f"(https://github.com/fpgas-online/fpgas.online-test-designs/issues/{issue})."
    )
    assert len(set(steps.BENCH_RUN.values())) == len(wiring.CARRIERS) == len(steps.BENCH_RUN)
    whole = steps.procedure(c)
    assert whole.count(steps.bench_run(c)) == 1 and "Not yet run by us on this hardware" not in whole
    for body in steps.guide(c).values():
        lines = body.splitlines()
        assert lines[2] == steps.bench_run(c) and lines[3] == ""  # under the banner, a paragraph of its own


HOW_TO = ("jtag-1", "jtag-2", "uart-1", "uart-2", "bench", "fit")


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_what_you_need_is_lists_of_parts_and_tools_and_nothing_to_do(key):
    """ "What you need" is what to have on the bench: a list of parts and a list of tools, each of 2 to 7 items.
    What the reader does before the first cut (power off, take the card out, mind static) is a step."""
    c = wiring.CARRIERS[key]
    for part in HOW_TO:
        body = steps.guide(c)[steps.guide_name(c, part)]
        need = body[body.index("## What you need") : body.index("## Steps")].splitlines()[1:]
        lines = [line for line in need if line]
        leads = [line for line in lines if not line.startswith("- ")]
        assert leads in (["**Parts**", "**Tools**"], ["**Parts**"], ["**Parts and tools**"]), (part, leads)
        lists, current = [], None
        for line in lines:
            if line.startswith("**"):
                current = []
                lists.append(current)
            else:
                current.append(line)
        assert all(2 <= len(items) <= 7 for items in lists), (part, [len(items) for items in lists])
        said = " ".join(lines).lower()
        doing_words = ("power off", "unplug", "take the card out", "take it out", "touch bare metal", "ask ")
        doing_words += ("cut it", "if it is", "side cutters;")
        for doing in doing_words:
            assert doing not in said, (part, doing)
        # everything its steps use is listed: the first cable's page lays each half from the card to the host
        if part == "jtag-1":
            assert f"- the {c.name}" + (f" with the {c.hat.name}" if c.hat else "") in need
        assert not any(line.rstrip().endswith(".") for line in lines), part  # items, not sentences


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_how_the_card_goes_in_and_comes_out_each_links_the_maker_s_page(key):
    """Taking the card out (a step's words) and putting it in (the fitting action, which is also drawn in a
    picture and so cannot link) each carry one link to the maker's own page: the action's is in its step's words."""
    c = wiring.CARRIERS[key]
    text, address = steps.MAKER[key]
    link = f"[{text}]({address})"
    assert steps.card_out(c).count(link) == 1
    fit = steps.guide(c)[steps.guide_name(c, "fit")]
    second = dict(step_blocks(fit))[steps.fit_step(c, 2)]
    lead = second.split("\n", 1)[0]
    assert lead.startswith(f"**{steps.fit_step(c, 2)}.** {steps.FIT_STEPS[1]}") and lead.count(link) == 1
    assert "](" not in steps.fit_actions(c)[3]  # the action itself, as the picture draws it, has no link
    # a cable's second-cable page says what to do with a cable that is still whole, as a step, not as a part
    uart = dict(step_blocks(steps.guide(c)[steps.guide_name(c, "uart-1")]))[1]
    assert "If the Molex cable is still whole, cut it in the middle with side cutters" in uart
