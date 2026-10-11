"""Every pin-ID target elaborates without a toolchain, and sends each ball's own name on that ball (#303).

Each designs/pmod-pin-id/gateware/pmod_pin_id_<board>.py has `design()`, which its `main()` builds from: the
platform, the pin list and the module, everything but the toolchain run. This builds each one and converts it
to Verilog (LiteX/Migen elaboration: no Vivado, openXC7 or icestorm), so a target that no longer builds (a
changed platform, or a board added as "How to add a board to the pin-id design" says) fails here at once,
not after a long build, or never for a board whose job is not in the CI matrix. Then it checks:

- each pin the design drives sends the name of the ball it is constrained to: the scan's whole premise;
- the balls are the board's: its connector table's pins, or the fleet's wired pins where the target lists them;
- the host scanner's map for the board (`BOARDS` in designs/pmod-pin-id/host/identify_pmod_pins.py) names
  only balls the design sends, and its table of every Arty Pmod ball is the platform's.
"""

import importlib.util
import pathlib
import re
import sys

import pytest

pytest.importorskip("migen")
pytest.importorskip("litex")

from litex.build.generic_platform import Pins, Subsignal

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWARE = REPO / "designs/pmod-pin-id/gateware"
sys.path.insert(0, str(GATEWARE))  # the targets import their sibling pmod_pin_id by name

import designs._shared.migen_compat  # noqa: E402,F401  -- patches migen tracer
from designs._shared import acorn_p2  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = _load(REPO / "designs/pmod-pin-id/host/identify_pmod_pins.py", "identify_pmod_pins")

# board -> [(variant, toolchain)]: every variant main() offers, with each toolchain it offers.
SEVEN_SERIES = ("openxc7", "vivado")
TARGETS = {
    "acorn": [(v, t) for v in ("cle-215+", "cle-215", "cle-101") for t in SEVEN_SERIES],
    "arty": [(v, t) for v in ("a7-35", "a7-100") for t in SEVEN_SERIES],
    "netv2": [(v, t) for v in ("a7-35", "a7-100") for t in SEVEN_SERIES],
    "fomu": [(None, "icestorm")],
    "tt": [(None, "icestorm")],
}
CASES = [(board, v, t) for board, runs in TARGETS.items() for v, t in runs]


def test_every_target_in_the_directory_is_tested():
    on_disk = {p.stem.removeprefix("pmod_pin_id_") for p in GATEWARE.glob("pmod_pin_id_*.py")}
    assert on_disk == set(TARGETS)


@pytest.mark.parametrize("board", sorted(TARGETS))
def test_the_variants_and_toolchains_tested_are_the_ones_main_offers(board):
    code = (GATEWARE / f"pmod_pin_id_{board}.py").read_text()
    offered = {}
    for option in ("variant", "toolchain"):
        m = re.search(rf'add_argument\("--{option}", default="[^"]+", choices=\[([^\]]*)\]', code)
        offered[option] = re.findall(r'"([^"]+)"', m.group(1)) if m else None
    tested = TARGETS[board]
    if offered["variant"] is None:  # one board, built with the toolchain main() names
        assert offered["toolchain"] is None and f'def design(toolchain="{tested[0][1]}"):' in code
        assert tested == [(None, tested[0][1])]
    else:
        assert sorted(tested) == sorted((v, t) for v in offered["variant"] for t in offered["toolchain"])


def _target(board):
    return _load(GATEWARE / f"pmod_pin_id_{board}.py", f"pmod_pin_id_{board}")


def _elaborate(board, variant, toolchain):
    target = _target(board)
    kwargs = {"toolchain": toolchain} | ({"variant": variant} if variant else {})
    platform, pin_list, module = target.design(**kwargs)
    # as LiteX's toolchain build does it (litex/build/generic_toolchain.py): finalize, which gives a design with
    # no clock domain of its own the board's default clock as sys, then convert to Verilog
    fragment = module.get_fragment()
    platform.finalize(fragment)
    verilog = str(platform.get_verilog(fragment, name=platform.name))
    driven = {}
    for _sig, pins, _others, (name, number, _sub) in platform.constraint_manager.get_sig_constraints():
        if name.startswith("pin_id_"):
            assert number == 0 and name not in driven, name
            driven[name] = pins
    return target, platform, pin_list, driven, verilog


@pytest.mark.parametrize(("board", "variant", "toolchain"), CASES)
def test_the_target_elaborates_and_each_driven_ball_sends_its_own_name(board, variant, toolchain):
    _target_mod, _platform, pin_list, driven, verilog = _elaborate(board, variant, toolchain)
    assert "module" in verilog and "endmodule" in verilog
    labels = [label for _resource, label in pin_list]
    assert labels and all(label.endswith("\r\n") for label in labels), labels
    # pin_id_<i> sends pin_list[i]'s label, and the platform puts it on exactly that ball
    assert sorted(driven) == sorted(f"pin_id_{i}" for i in range(len(pin_list)))
    for i, label in enumerate(labels):
        assert driven[f"pin_id_{i}"] == [label.removesuffix("\r\n")], (board, i, label)
    assert len(set(labels)) == len(labels), "two pins send the same name"


def _connector_balls(platform, connectors):
    table = platform.constraint_manager.connector_manager.connector_table
    return [ball for name in connectors for ball in table[name]]


@pytest.mark.parametrize("board", ["arty", "fomu", "tt"])
def test_a_connector_target_sends_every_ball_of_its_connectors(board):
    target, platform, pin_list, _driven, _verilog = _elaborate(board, *TARGETS[board][0])
    balls = [label.removesuffix("\r\n") for _resource, label in pin_list]
    assert balls == _connector_balls(platform, target.CONNECTORS)


def test_the_acorn_target_sends_the_fleet_s_wired_p2_pins():
    _target_mod, _platform, pin_list, _driven, _verilog = _elaborate("acorn", *TARGETS["acorn"][0])
    balls = [label.removesuffix("\r\n") for _resource, label in pin_list]
    assert balls == [acorn_p2.SERIAL_TX, acorn_p2.SERIAL_RX, *acorn_p2.SPARE_GPIO]


def test_the_netv2_target_sends_on_the_platform_s_serial_pins():
    _target_mod, platform, pin_list, _driven, _verilog = _elaborate("netv2", *TARGETS["netv2"][0])
    balls = [label.removesuffix("\r\n") for _resource, label in pin_list]
    # the serial pins as litex-boards' platform lists them: the pins the NeTV2 wires to the Pi
    (serial,) = [r for r in sys.modules[type(platform).__module__]._io if r[:2] == ("serial", 0)]
    subs = [s for s in serial[2:] if isinstance(s, Subsignal)]
    pins = {s.name: next(c.identifiers for c in s.constraints if isinstance(c, Pins)) for s in subs}
    assert balls == [*pins["tx"], *pins["rx"]]


@pytest.mark.parametrize("board", sorted(HOST.BOARDS))
def test_the_host_scanner_s_map_names_only_balls_the_design_sends(board):
    _target_mod, _platform, pin_list, _driven, _verilog = _elaborate(board, *TARGETS[board][0])
    sent = {label.removesuffix("\r\n") for _resource, label in pin_list}
    mapped = [ball for _gpio, ball, _label in HOST.BOARDS[board]["pins"]]
    assert set(mapped) <= sent, sorted(set(mapped) - sent)
    if "untested" not in HOST.BOARDS[board]:  # a map that leaves nothing out checks every ball the design sends
        assert set(mapped) == sent, sorted(sent - set(mapped))


def test_the_scanner_s_table_of_every_arty_pmod_ball_is_the_platform_s():
    target, platform, _pin_list, _driven, _verilog = _elaborate("arty", *TARGETS["arty"][0])
    table = platform.constraint_manager.connector_manager.connector_table
    assert {f"Arty J{c[-1].upper()}": set(table[c]) for c in target.CONNECTORS} == {
        conn: set(balls) for conn, balls in HOST.ARTY_PMODS.items()
    }
