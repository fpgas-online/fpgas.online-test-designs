"""The Acorn's self-test code (fpgas_online_verify.boards.acorn.bist), shared by the boot check and
designs/acorn-pcie/host/selftest.py.

The DRAM tests drive bist.dram() against tests/acorn_fakes.py's model of LiteDRAM's BIST cores. The model's
DRAM can ignore its top address bit, which is what an open or stuck top address line, or an image built for
twice the DRAM the board has, looks like from the controller.
"""

import pytest
from fpgas_online_verify.boards.acorn import bist, check, setup
from fpgas_online_verify.core import Problem

from tests import acorn_fakes as fk


def _regs(soc, golden=False):
    return bist.Regs(soc.read, soc.write, check.Csrs(fk.csr_json(golden)))


# -- the DRAM --------------------------------------------------------------------------------------------


def test_a_healthy_dram_passes_with_its_bandwidth():
    soc = fk.FakeSoC()
    out = bist.dram(_regs(soc), sleep=soc.sleep)
    assert out["faults"] == [] and out["errors"] == 0
    assert out["bytes"] == fk.DRAM_BYTES and out["passes"] == 2
    assert out["write_MBps"] == out["read_MBps"] == pytest.approx(fk.P48_MBPS, rel=0.02)  # ticks are whole cycles


def test_a_dead_top_address_bit_fails():
    soc = fk.FakeSoC()
    top = (fk.DRAM_BYTES // fk.DramModel.WORD).bit_length() - 2  # the word-address bit that picks the half
    soc.dram = fk.DramModel(fk.DRAM_BYTES, dead_bit=top)
    out = bist.dram(_regs(soc), sleep=soc.sleep)
    assert out["errors"] > 0
    assert any("words wrong" in f for f in out["faults"])


def test_both_halves_are_written_before_either_is_checked_and_each_gets_both_patterns():
    soc = fk.FakeSoC()
    bist.dram(_regs(soc), sleep=soc.sleep)
    half = fk.DRAM_BYTES // 2
    gen = [(base, prbs) for core, base, _, prbs in soc.dram.runs if core == "generator"]
    assert gen == [(0, 1), (half, 0), (0, 0), (half, 1)]
    order = [core for core, *_ in soc.dram.runs]
    assert order == ["generator", "generator", "checker", "checker"] * 2


def test_the_dram_size_comes_from_the_builds_csr_json():
    assert bist.dram(_regs(fk.FakeSoC()), sleep=lambda s: None)["bytes"] == fk.DRAM_BYTES


def test_the_bios_memtest_line_is_found():
    text = "\n--=============== SoC ==================--\nInitializing SDRAM @0x40000000...\nMemtest OK\n"
    assert bist.memtest_line(text) == "Memtest OK"
    assert bist.memtest_line("nothing here") is None


def test_the_console_is_read_until_it_is_quiet():
    soc = fk.FakeSoC()
    soc.console = bytearray(b"BIOS built on ...\nMemtest OK\n")
    assert bist.console(_regs(soc), quiet_s=0.05, sleep=soc.sleep) == "BIOS built on ...\nMemtest OK\n"
    assert soc.console == bytearray()


# -- the P2 pins -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("model", "serial", "spare"), [
    (fk.PI5, {"J2": 14, "K2": 15}, {"J5": 3, "H5": 4}),
    (fk.CM4, {"J2": 14, "K2": 15}, {}),
    (fk.CM5, {"J2": 14, "K2": 15}, {}),
])  # fmt: skip
def test_the_p2_balls_come_from_the_wiring(model, serial, spare):
    s = setup.detect(model)
    assert (s.p2_serial, s.p2_gpio) == (serial, spare)


@pytest.mark.parametrize("model", [fk.PI5, fk.CM4])
def test_no_ball_is_driven_on_tdi_tdo_or_tck(model):
    s = setup.detect(model)
    jtag = dict(zip(("TDI", "TDO", "TCK", "TMS"), s.jtag_gpios))
    ok, why = bist.testable({**s.p2_serial, **s.p2_gpio}, jtag)
    assert not set(ok.values()) & {jtag["TDI"], jtag["TDO"], jtag["TCK"]}
    assert why == {}  # both carriers keep the P2 balls off TDI/TDO/TCK; J2 meets TMS on the Blade, which is fine
    assert {"TMS"} == bist.SHARED_JTAG_OK


def test_a_ball_on_tck_is_not_driven():
    ok, why = bist.testable({"J5": 4}, {"TDI": 2, "TDO": 3, "TCK": 4, "TMS": 14})
    assert ok == {} and why == {"J5": "GPIO4 is JTAG TCK"}


def test_the_serial_switch_is_borrowed_with_a_finite_timeout_and_given_back():
    soc = fk.FakeSoC()
    regs = _regs(soc)
    with bist.borrowed_serial(regs):
        assert soc.serial["mode"] == 1 and 0 < soc.serial["timeout"] <= 30_000
    assert soc.serial["mode"] == 0 and soc.serial["timeout"] == 5000 and soc.serial["oe"] == 0


def test_the_switch_is_given_back_even_when_the_test_inside_fails():
    soc = fk.FakeSoC()
    with pytest.raises(Problem), bist.borrowed_serial(_regs(soc)):
        raise Problem("fail", "something")
    assert soc.serial["mode"] == 0


def test_the_switch_timing_out_by_itself_is_checked():
    soc = fk.FakeSoC()
    assert bist.switch_times_out(_regs(soc), sleep=soc.sleep)[0]
    soc.switch_stuck = True
    ok, detail = bist.switch_times_out(_regs(soc), sleep=soc.sleep)
    assert not ok and detail == "mode 1, 0.5 s later 1"


def test_balls_put_an_output_back_as_an_output_at_its_level():
    soc = fk.FakeSoC()
    pi = fk.FakePi(soc)
    pi.pins[3] = ["op", "pn", 1]
    faults, _ = bist.balls(_regs(soc), "p2_gpio", {"J5": 3}, pi)
    assert pi.pins[3] == ["op", "pn", 1]
    assert [f for f in faults if "drove" not in f] == []
