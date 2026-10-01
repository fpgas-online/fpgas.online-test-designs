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


WORDS = fk.DRAM_BYTES // fk.DramModel.WORD
TOP = WORDS.bit_length() - 2  # the word-address bit that picks the half


@pytest.mark.parametrize("dead_bit", [0, 1, 3, TOP - 1, TOP], ids=["column 0", "column 1", "bank", "row", "top"])
def test_a_dead_address_bit_fails(dead_bit):
    """The top bit only shows because the halves are written before either is checked; a lower one (a column
    or bank bit) makes two words of one half share a cell, so the second write of a pass spoils the first."""
    soc = fk.FakeSoC()
    soc.dram = fk.DramModel(fk.DRAM_BYTES, dead_bit=dead_bit)
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
    assert bist.console(_regs(soc), clock=soc.clock, sleep=soc.sleep) == "BIOS built on ...\nMemtest OK\n"
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


@pytest.mark.parametrize(
    ("high", "low"),
    [(0xFF << 8, 0), (0, 0xFF << 8), (0, 0xFF), (1 << 20, 0)],
    ids=["byte lane 1 stuck high", "byte lane 1 stuck low", "byte lane 0 stuck low", "one DQ line stuck high"],
)
def test_a_stuck_byte_lane_or_data_line_fails(high, low):
    soc = fk.FakeSoC()
    soc.dram = fk.DramModel(fk.DRAM_BYTES, stuck_high=high, stuck_low=low)
    out = bist.dram(_regs(soc), sleep=soc.sleep)
    assert out["errors"] > 0 and out["faults"]


def test_the_switch_timeout_is_put_back_even_when_reading_fails():
    soc = fk.FakeSoC()
    real = soc.read

    def read(addr):
        if addr == fk.REGS["p2_serial_mode"] and soc.serial["timeout"] == bist.SELF_TIMEOUT_MS:
            raise OSError("bus error")
        return real(addr)

    soc.read = read
    with pytest.raises(OSError):
        bist.switch_times_out(_regs(soc), sleep=soc.sleep)
    assert soc.serial["timeout"] == 5000 and soc.serial["mode"] == 0


def test_a_slow_pinctrl_never_lets_j2_k2_go_back_to_serial_mid_test():
    """Each pinctrl call takes 3 s here: a whole ball test is far longer than the switch's 10 s timeout, but the
    switch is renewed before each pattern, so it never times out while the Pi drives J2/K2."""
    soc = fk.FakeSoC()
    pi = fk.FakePi(soc)
    returned = []

    def slow(argv, timeout):
        soc.sleep(3.0)
        if soc._serial_mode() == 0:
            returned.append(argv)
        return pi(argv, timeout)

    regs = _regs(soc)
    with bist.borrowed_serial(regs):
        faults, _ = bist.balls(regs, "p2_serial", {"J2": 14, "K2": 15}, slow)
    assert faults == [] and returned == []
