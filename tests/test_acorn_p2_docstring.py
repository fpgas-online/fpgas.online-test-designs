"""The P2 pin table in designs/_shared/acorn_p2.py's docstring must say what docs/wiring/acorn/wiring.toml says.

The docstring is read from the source, without importing the module, so this needs no LiteX and runs in the
wiring workflow. Each row is held to wiring.toml: its pin and ball, its Use, and the host pin each carrier wires
it to.
"""

import ast
import pathlib

import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]
WIRING = tomllib.loads((REPO / "docs" / "wiring" / "acorn" / "wiring.toml").read_text())
DOC = ast.get_docstring(ast.parse((REPO / "designs" / "_shared" / "acorn_p2.py").read_text()))

COLUMNS = ["P2 pin", "Ball", "Use", "Pi 5 HAT", "Compute Blade"]


def _table(doc):
    """{ball: {column: cell}} for each row of the docstring's pin table, after checking its header."""
    lines = [line for line in doc.splitlines() if line.startswith("|")]
    assert lines, "no pin table in acorn_p2's docstring"
    cells = [[c.strip() for c in line.strip("|").split("|")] for line in lines]
    assert cells[0] == COLUMNS, f"acorn_p2's pin table has the columns {cells[0]}"
    assert all(set(c) <= set("-") for c in cells[1]), "the pin table's second line is not its rule"
    rows = {}
    for row in cells[2:]:
        assert len(row) == len(COLUMNS), f"acorn_p2's pin table has a row of {len(row)} cells: {row}"
        assert row[1] not in rows, f"acorn_p2's pin table has {row[1]} twice"
        rows[row[1]] = dict(zip(COLUMNS, row, strict=True))
    return rows


def _host_pin(carrier, ball):
    """The pin of `carrier`'s header that `ball` is wired to, or None if the ball's wire is cut."""
    wire = WIRING["carriers"][carrier]["wires"].get(ball)
    if wire is None:
        return None
    header, number = wire
    return WIRING["carriers"][carrier]["headers"][header]["pins"][str(number)]


def _also_on(carrier, ball, gpio):
    """The other signals `carrier` wires to the same GPIO as `ball`."""
    return [
        signal
        for signal in WIRING["carriers"][carrier]["wires"]
        if signal != ball and (_host_pin(carrier, signal) or {}).get("gpio") == gpio
    ]


def _expected_host_cell(carrier, ball):
    """The host cell for `ball` on `carrier`, as the table writes it, from wiring.toml."""
    pin = _host_pin(carrier, ball)
    if pin is None:  # cut: say what the GPIO the Pi 5 uses for it carries on this carrier instead
        gpio = _host_pin("pi5", ball)["gpio"]
        there = _also_on(carrier, ball, gpio)
        assert len(there) == 1, f"{ball} is cut on {carrier}, and {gpio} carries {there} there"
        return f"cut ({gpio} is JTAG {there[0]} there)"
    cell = pin["gpio"]
    if pin.get("func", "").endswith("XD0"):  # the serial pins say which way they go: TXD0 -> "(TXD)"
        cell += f" ({pin['func'][:-1]})"
    for signal in _also_on(carrier, ball, pin["gpio"]):
        cell += f", also JTAG {signal}"
        if ball in WIRING["carriers"][carrier]["resistors"]:
            cell += f" via {WIRING['carriers'][carrier]['resistor_value'].replace('Ω', 'ohm')}"
    return cell


TABLE = _table(DOC)
P2 = WIRING["connectors"]["P2"]["pins"]
BALLS = [name for name in P2 if "ball" in WIRING["signals"][name]]


def test_one_row_for_each_signal_pin_of_p2_in_pin_order():
    assert list(TABLE) == BALLS, f"acorn_p2's pin table has the balls {list(TABLE)}; wiring.toml's P2 has {BALLS}"
    for ball, row in TABLE.items():
        assert row["P2 pin"] == str(P2.index(ball) + 1), f"{ball} is at P2 pin {P2.index(ball) + 1}, not {row}"


def test_each_row_s_use_is_wiring_toml_s():
    for ball, row in TABLE.items():
        assert row["Use"] == WIRING["signals"][ball]["what"], f"{ball}'s Use in acorn_p2's pin table"


def test_each_row_s_host_pins_are_the_carriers_wires():
    for ball, row in TABLE.items():
        assert row["Pi 5 HAT"] == _expected_host_cell("pi5", ball), f"{ball}'s Pi 5 cell"
        assert row["Compute Blade"] == _expected_host_cell("blade", ball), f"{ball}'s Compute Blade cell"


def _broken(old, new):
    doc = DOC.replace(old, new, 1)
    assert doc != DOC, old
    return doc


def test_the_checks_catch_a_deleted_row_and_wrong_cells():
    """The two cases #330's re-review found the old ball-only check let through, and a wrong host pin."""
    row3 = next(line for line in DOC.splitlines() if line.startswith("| 3 "))
    deleted = _table(_broken(row3 + "\n", ""))
    assert list(deleted) != BALLS
    swapped_use = _table(_broken("| serial TX, FPGA output |", "| serial RX, FPGA output |"))
    assert swapped_use["K2"]["Use"] != WIRING["signals"]["K2"]["what"]
    wrong_gpio = _table(_broken("| GPIO3        |", "| GPIO2        |"))
    assert wrong_gpio["J5"]["Pi 5 HAT"] != _expected_host_cell("pi5", "J5")
