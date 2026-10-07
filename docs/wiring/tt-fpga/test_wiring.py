# SPDX-License-Identifier: Apache-2.0
"""wiring.toml is checked on load: a table that does not hang together never reaches a page.

Run: uv run --no-project --with pytest pytest docs/wiring/tt-fpga
"""

import copy

import pytest
import wiring

W = wiring.WIRING


def rejects(mutate, match):
    d = copy.deepcopy(wiring.DATA)
    mutate(d)
    with pytest.raises(wiring.WiringError, match=match):
        wiring.build(d)


def test_the_committed_wiring_loads_with_a_wire_for_every_bit_of_every_group():
    assert [(w.group, w.bit) for w in W.wires] == [(g, bit) for g in ("ui_in", "uio", "uo_out") for bit in range(8)]
    assert {w.port for w in W.of_group("ui_in")} == {"JA"}
    assert {w.port for w in W.of_group("uio")} == {"JB"}
    assert {w.port for w in W.of_group("uo_out")} == {"JC"}


def test_a_wire_has_the_whole_way_from_the_fpga_to_the_pi():
    w = W.wire("uo_out", 4)
    assert (w.fpga_pin, w.header, w.pin, w.port, w.gpio, w.mcu_gpio) == (45, "output", 7, "JC", 4, 37)


def test_the_shared_gpios_are_found_from_the_hat_not_written_down():
    assert [w.signal for w in W.shared()] == ["ui_in[1]", "ui_in[2]", "ui_in[3]", "uio[1]", "uio[2]", "uio[3]"]
    assert [x.signal for x in W.shares(W.wire("ui_in", 3))] == ["uio[3]"]
    assert W.shares(W.wire("uo_out", 3)) == []


def test_only_a_wire_with_a_gpio_to_itself_is_called_measured():
    for w in W.wires:
        assert (W.measured(w) is not None) == (not W.shares(w)), w.signal


def test_a_measurement_carries_its_date_its_place_and_its_record():
    (m,) = W.measurements
    assert m.dates == ("29 September 2026", "4 October 2026")
    assert m.when == "on 29 September 2026, and again by the boot check (`fpgas-verify`) on 4 October 2026"
    rejects(lambda d: d["measurements"][0].pop("dates"), "a measurement has no dates")
    rejects(lambda d: d["measurements"][0].__setitem__("when", "one day"), "must name each of its `dates`")
    assert "welland" in m.where and "tt-fpga-pin-mapping.md" in m.record
    rejects(lambda d: d["measurements"][0].pop("when"), "a measurement has no when")
    rejects(lambda d: d["measurements"][0].pop("record"), "a measurement has no record")
    rejects(lambda d: d["measurements"][0].__setitem__("wires", ["ui_in[9]"]), "wires that do not exist")


def test_an_ice40_pin_given_twice_is_refused():
    rejects(lambda d: d["groups"]["uio"]["fpga_pins"].__setitem__(0, 13), r"iCE40 pin 13 is given to ui_in\[0\] and")
    rejects(lambda d: d["other"][0].__setitem__("pin", 48), "iCE40 pin 48 is given to")
    rejects(lambda d: d["config"]["fpga"][0].__setitem__("pin", 2), "iCE40 pin 2 is given to")


def test_a_group_without_eight_pins_is_refused():
    rejects(lambda d: d["groups"]["ui_in"]["fpga_pins"].pop(), "7 iCE40 pins; a group has eight")


def test_two_headers_on_one_port_and_a_header_without_a_cable_are_refused():
    rejects(lambda d: d["cables"].__setitem__("bidir", "JA"), "two headers go to port JA")
    rejects(lambda d: d["cables"].pop("output"), "header 'output' has no cable")
    rejects(lambda d: d["cables"].__setitem__("output", "JD"), "port 'JD', which .hat. does not list")


def test_an_fpga_output_on_a_shared_gpio_is_refused():
    """Two FPGA pins on one Raspberry Pi GPIO are safe only while one of them is an input. Cabling the Output
    header to a port that shares GPIOs would put eight outputs there."""

    def swap(d):
        d["cables"]["output"], d["cables"]["bidir"] = "JB", "JC"

    rejects(swap, r"uo_out\[1\], which the FPGA drives, shares GPIO10 with ui_in\[1\]")


def test_a_pmod_connector_must_account_for_all_twelve_pins():
    rejects(lambda d: d["pmod"].__setitem__("ground_pins", [5]), "each of pins 1 to 12 once")


def test_the_serial_port_must_be_an_input_and_an_output_of_the_design():
    rejects(lambda d: d["uart"]["rx"].__setitem__("group", "uo_out"), "rx is on uo_out, which the FPGA drives")
    rejects(lambda d: d["uart"]["tx"].__setitem__("bit", 8), r"tx: uo_out\[8\] is not a signal")


def test_a_microcontroller_gpio_given_twice_is_refused():
    rejects(lambda d: d["groups"]["uio"].__setitem__("mcu_first_gpio", 20), r"RP2350 GPIO20 is given to ui_in\[3\] and")
    rejects(lambda d: d["other"][1].pop("mcu_source"), "mcu_gpio needs mcu_source")


def test_a_wiring_without_sources_is_refused():
    rejects(lambda d: d["sources"].clear(), "sources. is empty")


def test_the_clock_must_have_its_frequency_and_a_pin_our_code_drives():
    rejects(lambda d: d["other"][0].pop("hz"), "needs one clock")
    rejects(lambda d: d["other"][0].__setitem__("mcu_source", "tt"), "needs one clock")
