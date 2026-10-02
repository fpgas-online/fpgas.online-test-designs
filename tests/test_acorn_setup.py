"""Which Acorn setup a host is, from docs/wiring/acorn/wiring.toml (boards/acorn/setup.py)."""

import pytest
from fpgas_online_verify.boards.acorn import setup
from fpgas_online_verify.core import Problem

from tests import acorn_fakes as fk


def test_a_pi5_is_the_hat_setup_with_its_jtag_pins_and_spare_balls():
    s = setup.detect(fk.PI5)
    assert (s.key, s.jtag_pins, s.jtag_cable, s.gpiochip, s.uart) == (
        "pi5", "10:9:11:8", "libgpiod", "raspberrypi,rp1-gpio", "/dev/ttyAMA0")  # fmt: skip
    assert s.jtag_gpios == [10, 9, 11, 8]
    assert s.p2_gpio == {"J5": 3, "H5": 4}
    assert s.expected["pcie"] == {"speed_gt_s": 5.0, "width": 1}


@pytest.mark.parametrize(("model", "chip"), [(fk.CM4, "brcm,bcm2711-gpio"), (fk.CM5, "raspberrypi,rp1-gpio")])
def test_a_compute_module_is_the_blade_setup(model, chip):
    """A CM4 has no RP1: its header pins are on the BCM2711's own GPIO chip, driven with the libgpiod cable."""
    s = setup.detect(model)
    assert (s.key, s.jtag_pins, s.jtag_cable, s.gpiochip) == ("blade", "2:3:4:14", "libgpiod", chip)
    assert s.p2_gpio == {}  # J5 and H5 are cut on the blade cable


@pytest.mark.parametrize("model", ["Raspberry Pi 4 Model B Rev 1.4", "Raspberry Pi 500 Rev 1.0", ""])
def test_any_other_host_is_no_acorn_setup(model):
    with pytest.raises(Problem, match=r"is not an Acorn setup in wiring\.toml"):
        setup.detect(model)


def test_jtag_pins_that_disagree_with_the_wires_are_refused():
    wiring = setup.load(setup.WIRING)
    wiring["carriers"]["pi5"]["jtag_pins"] = "9:10:11:8"
    with pytest.raises(Problem, match="TDI:TDO:TCK:TMS land on 10:9:11:8"):
        setup.detect(fk.PI5, wiring)


def test_every_setup_has_its_pcie_figures():
    expected = setup.load(setup.EXPECTED)
    assert set(expected["setups"]) == set(setup.load(setup.WIRING)["carriers"])
    assert all(e["pcie"]["width"] == 1 for e in expected["setups"].values())


def test_the_data_is_found_from_a_checkout():
    assert setup.DATA_DIRS[1].joinpath("wiring.toml").is_file()


def test_missing_data_is_an_error(tmp_path):
    with pytest.raises(Problem, match=r"wiring\.toml is not installed"):
        setup.load(setup.WIRING, dirs=(tmp_path,))
