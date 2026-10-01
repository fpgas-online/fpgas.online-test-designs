"""designs/acorn-pcie/host/selftest.py: a command-line front end to the same code the boot check runs
(fpgas_online_verify.boards.acorn.bist; tests/test_acorn_bist.py tests that), with the pins from wiring.toml."""

import importlib.util
import pathlib

import pytest
from fpgas_online_verify.boards.acorn import bist, check

from tests import acorn_fakes as fk

REPO = pathlib.Path(__file__).resolve().parents[1]
SELFTEST = REPO / "designs" / "acorn-pcie" / "host" / "selftest.py"
_spec = importlib.util.spec_from_file_location("acorn_selftest", SELFTEST)
selftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(selftest)


@pytest.fixture(autouse=True)
def _fresh_results():
    selftest.results.clear()


def test_it_uses_the_boot_checks_code():
    assert selftest.bist is bist


@pytest.mark.parametrize(("name", "serial", "spare"), [("pi5", {"J2": 14, "K2": 15}, {"J5": 3, "H5": 4}),
                                                        ("blade", {"J2": 14, "K2": 15}, {})])  # fmt: skip
def test_the_carrier_and_its_pins_come_from_the_wiring(name, serial, spare):
    host = selftest.carrier(name)
    assert (host.key, host.p2_serial, host.p2_gpio) == (name, serial, spare)


def test_a_healthy_dram_passes_and_says_so_per_step():
    soc = fk.FakeSoC()
    out = selftest.dram(bist.Regs(soc.read, soc.write, check.Csrs(fk.csr_json())))
    assert out["errors"] == 0 and all(selftest.results) and len(selftest.results) == 13  # 8 runs, 4 checks, the summary


def test_every_wired_pin_both_ways_on_the_pi5_and_the_switch_given_back(monkeypatch):
    soc = fk.FakeSoC()
    pi = fk.FakePi(soc)
    monkeypatch.setattr(selftest, "run", pi)
    monkeypatch.setattr(bist.time, "sleep", soc.sleep)
    selftest.p2(bist.Regs(soc.read, soc.write, check.Csrs(fk.csr_json())), selftest.carrier("pi5"))
    assert all(selftest.results)
    assert soc.serial["mode"] == 0 and pi.pins[14][:2] == ["a4", "pn"] and pi.pins[3][:2] == ["no", "pu"]


def test_a_killed_run_gives_the_link_back():
    assert 0 < bist.SWITCH_TIMEOUT_MS <= 30_000
