"""openXC7 fixups for litex-boards platforms (designs/_shared/platform_fixups.py)."""

from litex.build.generic_platform import IOStandard, Subsignal
from litex_boards.platforms import kosagi_netv2

from designs._shared.platform_fixups import fix_openxc7_reduced_drive_iostandards


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
