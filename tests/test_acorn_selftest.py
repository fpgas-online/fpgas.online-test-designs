"""designs/acorn-pcie/host/selftest.py: the DRAM passes must catch a dead top address bit, and the P2 map must
be the wiring's.

The DRAM tests drive selftest.dram() against a model of LiteDRAM's BIST cores (dram_generator/dram_checker):
`reset` restarts the data pattern, `random` bit 0 picks a PRBS or a counter, one 16-byte word per address.
The model's DRAM can ignore its top address bit, which is what an open or stuck top address line, or an image
built for twice the DRAM the board has, looks like from the controller.
"""

import importlib.util
import pathlib

import pytest
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[1]
SELFTEST = REPO / "designs" / "acorn-pcie" / "host" / "selftest.py"
_spec = importlib.util.spec_from_file_location("acorn_selftest", SELFTEST)
selftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(selftest)

WORD = 16  # bytes per native-port word (128 bits)
SIZE = 64 * WORD


def _pattern(prbs, i):
    # Stand-ins for the PRBS and the counter: what matters is that they differ, and restart at reset.
    return (i * 2654435761 + 0x5A5A) & 0x7FFFFFFF if prbs else i


class FakeBIST:
    """csr[...] for the two BIST cores over a DRAM of `size` bytes whose address bit `dead_bit` (a word-address
    bit) does nothing."""

    def __init__(self, size, dead_bit=None):
        self.constants = {"config_clock_frequency": 100_000_000}
        self.memories = {"main_ram": {"size": size}}
        self.mem = {}
        self.mask = ~(1 << dead_bit) if dead_bit is not None else -1
        self.regs = {}
        self.errors = 0

    def __setitem__(self, name, value):
        self.regs[name] = value
        if name.endswith("_start"):
            self._run(name.removesuffix("_start"))

    def __getitem__(self, name):
        if name.endswith("_done"):
            return 1
        if name.endswith("_ticks"):
            return self.regs[name.replace("_ticks", "_length")] // WORD + 10
        if name == "dram_checker_errors":
            return self.errors
        return self.regs.get(name, 0)

    def _run(self, core):
        base, length, prbs = (self.regs[f"{core}_{r}"] for r in ("base", "length", "random"))
        if core == "dram_checker":
            self.errors = 0
        for i in range(length // WORD):
            addr = (base // WORD + i) & self.mask
            want = _pattern(prbs & 1, i)
            if core == "dram_generator":
                self.mem[addr] = want
            elif self.mem.get(addr) != want:
                self.errors += 1


@pytest.fixture(autouse=True)
def _fresh_results():
    selftest.results.clear()


def test_a_healthy_dram_passes():
    out = selftest.dram(FakeBIST(SIZE))
    assert out["errors"] == 0
    assert all(selftest.results)


def test_a_dead_top_address_bit_fails():
    top = (SIZE // WORD).bit_length() - 2  # the word-address bit that picks the high half
    out = selftest.dram(FakeBIST(SIZE, dead_bit=top))
    assert out["errors"] > 0
    assert not all(selftest.results)


def test_every_half_gets_both_patterns():
    seen = []

    class Recording(FakeBIST):
        def _run(self, core):
            seen.append((core, self.regs[f"{core}_base"], self.regs[f"{core}_random"]))
            super()._run(core)

    selftest.dram(Recording(SIZE))
    gen = [(base, pattern) for core, base, pattern in seen if core == "dram_generator"]
    assert sorted(gen) == [(0, 0), (0, 1), (SIZE // 2, 0), (SIZE // 2, 1)]
    # Within a pass, both halves are written before either is checked.
    cores = [core for core, _, _ in seen]
    assert cores == ["dram_generator"] * 2 + ["dram_checker"] * 2 + ["dram_generator"] * 2 + ["dram_checker"] * 2


# -- P2 ----------------------------------------------------------------------------------------------------

WIRING = tomllib.loads((REPO / "docs" / "wiring" / "acorn" / "wiring.toml").read_text())
P2_BALLS = ("J2", "K2", "J5", "H5")
JTAG = ("TDI", "TDO", "TCK", "TMS")


def _gpio(carrier, signal):
    header, pin = WIRING["carriers"][carrier]["wires"][signal]
    return int(WIRING["carriers"][carrier]["headers"][header]["pins"][str(pin)]["gpio"].removeprefix("GPIO"))


@pytest.mark.parametrize("carrier", sorted(WIRING["carriers"]))
def test_the_p2_map_is_the_wiring(carrier):
    wires = WIRING["carriers"][carrier]["wires"]
    assert selftest.P2_GPIO[carrier] == {b: _gpio(carrier, b) for b in P2_BALLS if b in wires}
    assert selftest.JTAG_GPIO[carrier] == {s: _gpio(carrier, s) for s in JTAG}


def test_the_blade_tests_j2_and_k2_but_not_the_cut_pins():
    pins, skipped = selftest.pins_to_test("blade")
    assert pins == {"J2": 14, "K2": 15}  # J2 shares GPIO14 with TMS, which is allowed
    assert skipped == {b: "not wired on this carrier (wiring.toml)" for b in ("J5", "H5")}


@pytest.mark.parametrize("carrier", sorted(WIRING["carriers"]))
def test_no_ball_is_tested_on_tdi_tdo_or_tck(carrier):
    pins, _ = selftest.pins_to_test(carrier)
    jtag = selftest.JTAG_GPIO[carrier]
    assert not set(pins.values()) & {jtag[s] for s in ("TDI", "TDO", "TCK")}
    assert {"TMS"} == selftest.SHARED_JTAG_OK


def test_the_pi5_tests_every_p2_pin():
    pins, skipped = selftest.pins_to_test("pi5")
    assert pins == {"J2": 14, "K2": 15, "J5": 3, "H5": 4}
    assert skipped == {}


def test_a_killed_run_gives_the_link_back():
    assert 0 < selftest.SWITCH_TIMEOUT_MS <= 30_000
