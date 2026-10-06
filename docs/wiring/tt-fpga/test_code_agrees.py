# SPDX-License-Identifier: Apache-2.0
"""wiring.toml and the code's own copies of the wiring agree, entry by entry.

The test code cannot read wiring.toml: its host scripts are installed on the Raspberry Pi one file at a time
(verify/pyproject.toml force-includes each), and the gateware's platform file is LiteX's own format. So
each keeps its numbers, and this test fails when one of them and wiring.toml differ. The pin identification
test's table (identify_pmod_pins.BOARDS["tt"]) is what the boot check judges a board's cabling against, so
that is the one the documentation must never drift from.

The code is read, not imported (ast): the host scripts need gpiod and the platform needs LiteX, and neither
is installed where this runs.

Run: uv run --no-project --with pytest pytest docs/wiring/tt-fpga
"""

import ast
import pathlib
import re

import wiring

REPO = pathlib.Path(__file__).resolve().parents[3]
W = wiring.WIRING
PIN_ID = REPO / "designs/pmod-pin-id/host/identify_pmod_pins.py"
PIN_ID_GATEWARE = REPO / "designs/pmod-pin-id/gateware/pmod_pin_id_tt.py"
LOOPBACK = REPO / "designs/pmod-loopback/host/test_pmod_loopback.py"
PLATFORM = REPO / "designs/_shared/tt_fpga_platform.py"
LOADER = REPO / "designs/_host/tt_fpga_program.py"
BRIDGE = REPO / "designs/_host/tt_test_wrapper.py"


def assigned(path, name):
    """The expression assigned to the module-level `name` in the file at `path`, as its syntax tree."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    raise AssertionError(f"{path.name} assigns no {name}")


def literal(path, name):
    return ast.literal_eval(assigned(path, name))


def platform_io():
    """{resource or resource.subsignal: [iCE40 pins]} from the platform's `_io`, read from its syntax tree."""

    def pins(call):
        return [int(p) for p in call.args[0].value.split()]

    out = {}
    for entry in assigned(PLATFORM, "_io").elts:
        name = entry.elts[0].value
        for item in entry.elts[2:]:
            if not isinstance(item, ast.Call):
                continue
            if item.func.id == "Pins":
                out[name] = pins(item)
            elif item.func.id == "Subsignal":
                out[f"{name}.{item.args[0].value}"] = pins(item.args[1])
    return out


def test_the_pin_identification_table_is_the_wiring_wire_for_wire():
    """BOARDS["tt"]: (Pi GPIO, iCE40 pin, "HAT <port>.<pin> <- <signal>") for every wire, in the HAT's order."""
    board = literal(PIN_ID, "BOARDS")["tt"]
    ours = [(w.gpio, str(w.fpga_pin), f"HAT {w.port}.{w.pin} <- {w.signal}") for w in W.wires]
    assert board["pins"] == ours
    assert board["wires"] == len(W.wires)


def test_the_pmod_hat_ports_are_the_ones_the_pin_identification_test_scans():
    assert literal(PIN_ID, "PMOD_HAT_PORTS") == {port: p["gpios"] for port, p in W.hat.items()}


def test_the_pin_identification_design_gives_turns_to_exactly_the_wires_that_share_a_gpio():
    """pmod_pin_id_tt.SHARED: {(platform connector, bit): turn}. Its keys are the shared wires, and two wires
    on one GPIO never have the same turn."""
    node = assigned(PIN_ID_GATEWARE, "SHARED")
    turns = eval(compile(ast.Expression(node), PIN_ID_GATEWARE.name, "eval"), {"__builtins__": {}})
    ours = {(W.groups[w.group]["connector"], w.bit): w for w in W.shared()}
    assert set(turns) == set(ours)
    for key, wire in ours.items():
        for other in W.shares(wire):
            assert turns[key] != turns[(W.groups[other.group]["connector"], other.bit)]


def test_the_loopback_test_drives_ui_in_and_reads_uo_out_on_the_wirings_gpios():
    tt = literal(LOOPBACK, "BOARD_CONFIGS")["tt"]
    assert tt["drive_pins"] == [w.gpio for w in W.of_group("ui_in")]
    assert tt["read_pins"] == [w.gpio for w in W.of_group("uo_out")]
    assert tt["width"] == 8


def test_the_platform_file_has_the_same_ice40_pin_for_every_signal_and_nothing_more():
    io = platform_io()
    ours = {group: g["fpga_pins"] for group, g in W.groups.items()}
    ours |= {o["signal"]: [o["pin"]] for o in W.other}
    ours |= {f"serial.{end}": [W.wire(W.uart[end]["group"], W.uart[end]["bit"]).fpga_pin] for end in ("rx", "tx")}
    assert io == ours
    connectors = {name: [int(p) for p in pins.split()] for name, pins in literal(PLATFORM, "_connectors")}
    assert connectors == {g["connector"]: g["fpga_pins"] for g in W.groups.values()}


def test_the_loader_drives_the_microcontroller_pins_the_wiring_names():
    text = LOADER.read_text()
    mcu = {c["name"]: c["gpio"] for c in W.config["mcu"]}
    for name, variable in (("sck", "sck_pin"), ("mosi", "mosi_pin"), ("ss", "ss_pin"), ("reset", "reset_pin")):
        found = set(re.findall(rf"^{variable} = Pin\((\d+), Pin\.OUT\)", text, re.M))
        assert found == {str(mcu[name])}, (name, found)
    clock = next(o for o in W.other if o["signal"] == "clk_rp2040")
    assert clock["mcu_source"] == "code"
    assert set(re.findall(r"PWM\(Pin\((\d+)\)\)", text)) == {str(clock["mcu_gpio"])}
    assert set(re.findall(r"\.freq\((50_000_000)\)", text)) == {"50_000_000"} and "50 MHz" in clock["what"]
    # --gpio-release sets every GPIO of the 24 signals to an input: one unbroken range
    gpios = sorted(w.mcu_gpio for w in W.wires)
    assert gpios == list(range(gpios[0], gpios[-1] + 1))
    assert f"for g in list(range({gpios[0]}, {gpios[-1] + 1})):" in text


def test_the_serial_bridge_is_on_the_two_microcontroller_pins_of_the_wirings_serial_port():
    u = W.uart
    rx, tx = (W.wire(u[end]["group"], u[end]["bit"]) for end in ("rx", "tx"))
    # the microcontroller sends on the design's RX and receives on the design's TX
    expected = f"uart = UART({u['mcu_uart']}, {u['baud']}, tx=Pin({rx.mcu_gpio}), rx=Pin({tx.mcu_gpio}))"
    assert expected in BRIDGE.read_text()
