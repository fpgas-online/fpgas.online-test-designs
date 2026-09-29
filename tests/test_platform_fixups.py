"""openXC7 fixups for litex-boards platforms (designs/_shared/platform_fixups.py)."""

import pytest
from litex.build.generic_platform import IOStandard, Subsignal
from litex_boards.platforms import digilent_arty, kosagi_netv2
from migen import ClockDomain

from designs._shared.platform_fixups import constrain_openxc7_clocks, fix_openxc7_reduced_drive_iostandards


def iostandards(resource):
    """Every IOStandard name in a resource tuple, including those inside its subsignals."""
    names = []
    for item in resource[2:]:
        if isinstance(item, IOStandard):
            names.append(item.name)
        elif isinstance(item, Subsignal):
            names += [c.name for c in item.constraints if isinstance(c, IOStandard)]
    return names


def ddram(platform):
    return next(r for r in platform.constraint_manager.available if r[0] == "ddram")


def test_netv2_ddram_is_reduced_drive_sstl15_to_begin_with():
    platform = kosagi_netv2.Platform(variant="a7-35", toolchain="openxc7")
    assert set(iostandards(ddram(platform))) == {"SSTL15_R", "DIFF_SSTL15_R", "LVCMOS15"}


def test_the_ddram_standards_become_ones_nextpnr_xilinx_knows():
    platform = kosagi_netv2.Platform(variant="a7-35", toolchain="openxc7")
    fix_openxc7_reduced_drive_iostandards(platform)
    assert set(iostandards(ddram(platform))) == {"SSTL15", "DIFF_SSTL15", "LVCMOS15"}


def test_the_other_constraints_are_kept():
    platform = kosagi_netv2.Platform(variant="a7-35", toolchain="openxc7")
    before = [repr(r) for r in platform.constraint_manager.available]
    fix_openxc7_reduced_drive_iostandards(platform)
    after = [repr(r).replace("SSTL15_R", "SSTL15") for r in platform.constraint_manager.available]
    assert after == [b.replace("SSTL15_R", "SSTL15") for b in before]


def test_the_board_definition_itself_is_not_changed():
    fix_openxc7_reduced_drive_iostandards(kosagi_netv2.Platform(variant="a7-35", toolchain="openxc7"))
    vivado = kosagi_netv2.Platform(variant="a7-35", toolchain="vivado")
    assert set(iostandards(ddram(vivado))) == {"SSTL15_R", "DIFF_SSTL15_R", "LVCMOS15"}


def test_each_pll_output_gets_its_own_period():
    platform = digilent_arty.Platform(variant="a7-35", toolchain="openxc7")
    sys, sys4x = ClockDomain("sys"), ClockDomain("sys4x")
    constrain_openxc7_clocks(platform, {sys: 80e6, sys4x: 320e6})
    assert platform.toolchain.clocks[sys.clk][0] == 12.5
    assert platform.toolchain.clocks[sys4x.clk][0] == 3.125


def test_vivado_builds_are_left_to_derive_their_own():
    platform = digilent_arty.Platform(variant="a7-35", toolchain="vivado")
    sys = ClockDomain("sys")
    constrain_openxc7_clocks(platform, {sys: 80e6})
    assert sys.clk not in platform.toolchain.clocks


def test_openxc7_builds_fail_when_timing_fails():
    platform = digilent_arty.Platform(variant="a7-35", toolchain="openxc7")
    seen = {}
    platform.toolchain.build = lambda *args, **kwargs: seen.update(kwargs)
    constrain_openxc7_clocks(platform, {ClockDomain("sys"): 80e6})
    platform.toolchain.build(platform, None, timingstrict=False)  # what LiteXArgumentParser passes by default
    assert seen["timingstrict"] is True


@pytest.mark.parametrize("freq", [0, -1])
def test_a_nonsense_frequency_is_refused(freq):
    platform = digilent_arty.Platform(variant="a7-35", toolchain="openxc7")
    with pytest.raises(ValueError):
        constrain_openxc7_clocks(platform, {ClockDomain("sys"): freq})
