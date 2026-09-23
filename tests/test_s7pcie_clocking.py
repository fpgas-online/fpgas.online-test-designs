"""The PIPE clock mux must be fed straight from the PHY's MMCM, not through the 125/250 MHz BUFGs."""

import pytest

pytest.importorskip("litex")
pytest.importorskip("litepcie")

from litepcie.phy.s7pciephy import S7PCIEPHY
from litex_boards.platforms import kosagi_netv2
from migen import ClockSignal
from migen.fhdl.specials import Instance

import designs._shared.migen_compat  # noqa: F401  -- patches migen tracer
from designs._shared.s7pcie_clocking import feed_pclk_mux_from_mmcm


def _phy():
    platform = kosagi_netv2.Platform(variant="a7-35", toolchain="vivado")
    return S7PCIEPHY(platform, platform.request("pcie_x1"), data_width=64, bar0_size=0x20000)


def _mux_inputs(phy):
    (mux,) = [s for s in phy._fragment.specials if isinstance(s, Instance) and s.of == "BUFGCTRL"]
    return {item.name: item.expr for item in mux.items if item.name in ("I0", "I1")}


def test_litepcie_still_muxes_the_buffered_clocks():
    # What the helper corrects: if litepcie changes this, the helper's premise needs rechecking.
    inputs = _mux_inputs(_phy())
    assert isinstance(inputs["I0"], ClockSignal) and inputs["I0"].cd == "clk125"
    assert isinstance(inputs["I1"], ClockSignal) and inputs["I1"].cd == "clk250"


def test_mux_is_fed_from_the_mmcm_outputs():
    phy = _phy()
    feed_pclk_mux_from_mmcm(phy)
    inputs = _mux_inputs(phy)
    assert inputs["I0"] is phy.mmcm.clkouts[0][0]
    assert inputs["I1"] is phy.mmcm.clkouts[1][0]


def test_the_125mhz_bufg_still_clocks_its_domain():
    # clk125 also clocks the PIPE DRP port: its BUFG stays, alongside the mux.
    phy = _phy()
    feed_pclk_mux_from_mmcm(phy)
    bufg_inputs = [
        item.expr
        for s in phy.mmcm._fragment.specials
        if isinstance(s, Instance) and s.of == "BUFG"
        for item in s.items
        if item.name == "I"
    ]
    assert any(e is phy.mmcm.clkouts[0][0] for e in bufg_inputs)


def test_the_mux_clocks_are_physically_exclusive():
    # Only one of 125/250 MHz drives PIPECLK at a time: a path launched on one and captured on the other
    # does not exist, and without this Vivado times it (-0.645 ns on Acorn CLE-215+, yosys-vivado).
    phy = _phy()
    feed_pclk_mux_from_mmcm(phy)
    (mux,) = [s for s in phy._fragment.specials if isinstance(s, Instance) and s.of == "BUFGCTRL"]
    assert mux.name_override == "pcie_pclk_mux"
    commands = [c.format() for c in phy.platform.toolchain.pre_placement_commands]
    assert (
        "create_generated_clock -name pcie_pclk_125 -source [get_pins pcie_pclk_mux/I0] -divide_by 1"
        " [get_pins pcie_pclk_mux/O]"
    ) in commands
    assert (
        "create_generated_clock -name pcie_pclk_250 -source [get_pins pcie_pclk_mux/I1] -divide_by 1"
        " -add -master_clock [get_clocks -of_objects [get_pins pcie_pclk_mux/I1]] [get_pins pcie_pclk_mux/O]"
    ) in commands
    assert (
        "set_clock_groups -name pcie_pclk_mux -physically_exclusive -group pcie_pclk_125 -group pcie_pclk_250"
    ) in commands


def test_refuses_a_second_call():
    phy = _phy()
    feed_pclk_mux_from_mmcm(phy)
    with pytest.raises(AssertionError):
        feed_pclk_mux_from_mmcm(phy)
