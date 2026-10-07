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
DISPLAY = REPO / "designs/tt-display/gateware/tt_display.py"
CLOCK = next(o for o in W.other if "hz" in o)


def clock_as_started(path):
    """(the GPIOs a script starts a PWM clock on, the frequencies it sets on one), each as a set of numbers:
    every `PWM(Pin(n))` and every `<name>.freq(n)` in the MicroPython the file sends to the board."""
    text = path.read_text()
    pins = {int(n) for n in re.findall(r"PWM\(Pin\((\d+)\)\)", text)}
    rates = {int(n.replace("_", "")) for n in re.findall(r"\b\w+\.freq\(([\d_]+)\)", text)}
    return pins, rates


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
    # SHARED is two dict comprehensions joined with `|`, not a literal, so ast.literal_eval refuses it. It is
    # this repository's own expression, it uses no name, and it is evaluated with no builtins to reach.
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
    # The default way of sending (PIO) does not use sck_pin and mosi_pin: its state machine is given the pins.
    assert set(re.findall(r"sideset_base=Pin\((\d+)\)", text)) == {str(mcu["sck"])}
    assert set(re.findall(r"out_base=Pin\((\d+)\)", text)) == {str(mcu["mosi"])}
    # --gpio-release sets every GPIO of the 24 signals to an input: one unbroken range
    gpios = sorted(w.mcu_gpio for w in W.wires)
    assert gpios == list(range(gpios[0], gpios[-1] + 1))
    assert f"for g in list(range({gpios[0]}, {gpios[-1] + 1})):" in text


def test_the_loader_and_the_serial_bridge_start_the_wirings_clock_on_the_wirings_pin():
    """Both scripts start the clock (the bridge starts it again after its own reset of the board)."""
    assert CLOCK["mcu_source"] == "code"
    for path in (LOADER, BRIDGE):
        pins, rates = clock_as_started(path)
        assert pins == {CLOCK["mcu_gpio"]}, path.name
        assert rates == {CLOCK["hz"]}, path.name


def test_the_gateware_expects_the_clock_the_wiring_gives():
    text = PLATFORM.read_text()
    assert {float(n) for n in re.findall(r"1e9 / ([0-9.e]+)", text)} == {float(CLOCK["hz"])}
    assert literal(PIN_ID_GATEWARE, "SYS_CLK_FREQ") == CLOCK["hz"]


def test_the_fpga_named_on_the_pages_is_the_device_the_platform_builds_for():
    assert f'"{W.board["fpga_device"]}"' in PLATFORM.read_text()
    family, part, package = W.board["fpga_device"].split("-")
    assert f"{family}{part}".lower() in W.board["fpga"].lower()  # iCE40UP5K
    assert package.lower() in W.board["fpga"].lower()  # SG48


def test_the_display_design_puts_the_ring_the_middle_bar_and_the_dot_where_the_wiring_does():
    """tt_display.py drives uo_out with the ring's segments on its first RING bits, then the middle bar, then
    the dot. It holds no segment names, so this ties the places of g and the dot, not the order a to f."""
    assert "uo_out.eq(Cat(*[ring == i for i in range(RING)], middle, dot))" in DISPLAY.read_text()
    ring = literal(DISPLAY, "RING")
    segments = W.display["segments"]
    assert segments[:ring] == ["a", "b", "c", "d", "e", "f"] and segments[ring:] == ["g", "dot"]


def test_the_serial_bridge_is_on_the_two_microcontroller_pins_of_the_wirings_serial_port():
    u = W.uart
    rx, tx = (W.wire(u[end]["group"], u[end]["bit"]) for end in ("rx", "tx"))
    # the microcontroller sends on the design's RX and receives on the design's TX
    expected = f"uart = UART({u['mcu_uart']}, {u['baud']}, tx=Pin({rx.mcu_gpio}), rx=Pin({tx.mcu_gpio}))"
    assert expected in BRIDGE.read_text()


def test_the_loader_starts_the_clock_and_frees_the_gpios_only_with_gpio_release_and_the_bridge_starts_its_own():
    """The sources page says so in those words: the flag's name, what it does, and that the bridge needs no flag."""
    text = LOADER.read_text()
    assert 'add_argument(\n        "--gpio-release",' in text
    snippet = literal(LOADER, "GPIO_RELEASE_SNIPPET")
    assert "PWM(Pin(16))" in snippet and "Pin(g, Pin.IN)" in snippet
    # the clock is started nowhere else in the loader, and the snippet is added only when the flag is given
    assert text.count("PWM(Pin(") == snippet.count("PWM(Pin(")
    assert "    if gpio_release:\n        script += GPIO_RELEASE_SNIPPET\n" in text
    # the bridge loads without the flag, so it has to start the clock itself (test above)
    assert re.findall(r"tt_fpga_program\.program\(([^)]*)\)", BRIDGE.read_text()) == ["port, local_path"] * 2
    said = next(v for k, v in W.sources.items() if k.startswith("The other RP2350 GPIO numbers"))
    assert "run with `--gpio-release`, starts the clock and then sets the GPIOs of the 24 signals to inputs" in said
    assert "without that flag it starts no clock and leaves GPIO17 to GPIO40 as they were" in said
    assert "Our serial bridge starts the clock itself" in said
