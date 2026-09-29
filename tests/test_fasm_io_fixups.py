"""The FASM rewrite giving openXC7 builds the VREF and SSTL drive Vivado gives (designs/_shared/fasm_io_fixups.py)."""

import pytest

from designs._shared.fasm_io_fixups import add_openxc7_fasm_io_fixups, fix_lines, main

# Trimmed from the openXC7 NeTV2 DDR build: a DQ pin (SSTL in and out), an address pin (SSTL out), and
# reset_n, an LVCMOS15 output driving 16 mA, which shares the SSTL15 drive feature but is no SSTL pin.
FASM = """\
HCLK_IOI3_X113Y78.STEPDOWN
HCLK_IOI3_X113Y78.VREF.V_675_MV
RIOB33_X43Y61.IOB_Y0.IN_TERM.UNTUNED_SPLIT_40
RIOB33_X43Y61.IOB_Y0.LVCMOS15_SSTL15.DRIVE.I16_I_FIXED
RIOB33_X43Y61.IOB_Y0.SSTL135_SSTL15.IN
RIOB33_X43Y61.IOB_Y0.SSTL135_SSTL15.SLEW.FAST
RIOB33_X43Y61.IOB_Y1.LVCMOS15_SSTL15.DRIVE.I16_I_FIXED
RIOB33_X43Y61.IOB_Y1.SSTL135_SSTL15.SLEW.FAST
RIOB33_X43Y65.IOB_Y1.LVCMOS15_SSTL15.DRIVE.I16_I_FIXED
RIOB33_X43Y65.IOB_Y1.LVCMOS12_LVCMOS15_LVCMOS18_LVCMOS25_LVCMOS33_LVTTL.SLEW.FAST
CLBLM_R_X3Y5.SLICEM_X0.ALUT.INIT[63:0] = 64'h0000000000000001
""".splitlines(keepends=True)


def test_nothing_asked_nothing_changed():
    assert fix_lines(FASM) == FASM


def test_the_bank_gets_the_vref_asked_for():
    out = fix_lines(FASM, vref_mv=750)
    assert "HCLK_IOI3_X113Y78.VREF.V_750_MV\n" in out
    assert not any("V_675_MV" in line for line in out)


def test_no_vref_is_added_to_a_bank_that_had_none():
    no_vref = [line for line in FASM if "VREF" not in line]
    assert fix_lines(no_vref, vref_mv=750) == no_vref


@pytest.mark.parametrize("mv", [0, 700, 1500])
def test_a_vref_prjxray_cannot_encode_is_refused(mv):
    with pytest.raises(ValueError):
        fix_lines(FASM, vref_mv=mv)


def test_sstl15_outputs_get_the_reduced_drive():
    out = fix_lines(FASM, sstl15_reduced_drive=True)
    assert "RIOB33_X43Y61.IOB_Y0.LVCMOS15.DRIVE.I8\n" in out
    assert "RIOB33_X43Y61.IOB_Y1.LVCMOS15.DRIVE.I8\n" in out


def test_an_lvcmos15_output_keeps_its_drive():
    out = fix_lines(FASM, sstl15_reduced_drive=True)
    assert "RIOB33_X43Y65.IOB_Y1.LVCMOS15_SSTL15.DRIVE.I16_I_FIXED\n" in out
    assert "RIOB33_X43Y65.IOB_Y1.LVCMOS15.DRIVE.I8\n" not in out


def test_every_other_line_is_kept_in_order():
    out = fix_lines(FASM, vref_mv=750, sstl15_reduced_drive=True)
    assert len(out) == len(FASM)
    unchanged = [a for a, b in zip(FASM, out) if a == b]
    assert len(unchanged) == len(FASM) - 3


class _Toolchain:
    is_openxc7 = True
    _build_name = "kosagi_netv2"

    def __init__(self):
        self._pre_packer_cmd = ["fasm2frames"]
        self._pre_packer_opts = {}

    def finalize(self):
        # As LiteX does: fasm2frames' options go to _pre_packer_cmd[0].
        self._pre_packer_opts[self._pre_packer_cmd[0]] = "--part x kosagi_netv2.fasm > kosagi_netv2.frames"


class _Platform:
    def __init__(self, toolchain):
        self.toolchain = toolchain


def test_the_rewrite_runs_before_fasm2frames():
    tc = _Toolchain()
    add_openxc7_fasm_io_fixups(_Platform(tc), vref_mv=750, sstl15_reduced_drive=True)
    tc.finalize()
    assert len(tc._pre_packer_cmd) == 2
    assert tc._pre_packer_cmd[1] == "fasm2frames"
    assert tc._pre_packer_opts["fasm2frames"].startswith("--part x")
    step = tc._pre_packer_cmd[0] + " " + tc._pre_packer_opts[tc._pre_packer_cmd[0]]
    assert "fasm_io_fixups.py" in step
    assert "kosagi_netv2.fasm" in step and "--vref-mv 750" in step and "--sstl15-reduced-drive" in step


def test_vivado_builds_are_untouched():
    tc = _Toolchain()
    tc.is_openxc7 = False
    add_openxc7_fasm_io_fixups(_Platform(tc), vref_mv=750)
    tc.finalize()
    assert tc._pre_packer_cmd == ["fasm2frames"]


def test_single_iob_tiles_are_rewritten_too():
    sing = [
        "RIOB33_SING_X43Y50.IOB_Y0.LVCMOS15_SSTL15.DRIVE.I16_I_FIXED\n",
        "RIOB33_SING_X43Y50.IOB_Y0.SSTL135_SSTL15.SLEW.FAST\n",
    ]
    assert fix_lines(sing, sstl15_reduced_drive=True)[0] == "RIOB33_SING_X43Y50.IOB_Y0.LVCMOS15.DRIVE.I8\n"


def test_the_command_line_rewrites_the_file_in_place(tmp_path):
    fasm = tmp_path / "top.fasm"
    fasm.write_text("".join(FASM))
    main([str(fasm), "--vref-mv", "750", "--sstl15-reduced-drive"])
    assert fasm.read_text() == "".join(fix_lines(FASM, vref_mv=750, sstl15_reduced_drive=True))
