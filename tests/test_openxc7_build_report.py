"""scripts/openxc7_build_report.py: what an openXC7 build's nextpnr log and FASM say, as a table."""

import importlib.util
import pathlib

import pytest

_MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "openxc7_build_report.py"
_spec = importlib.util.spec_from_file_location("openxc7_build_report", _MOD_PATH)
rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rep)

# Trimmed from the nextpnr-xilinx log of the pcie-enumeration Acorn CLE-215+ build (regymm/openxc7, 2026-10-02).
LOG = """\
Info: ignoring unsupported XDC command 'set_false_path' (on line 53)
Info:     Constraining 'pcie_x1_rx_p' to site 'IPAD_X1Y55'
Info:     Tile 'GTP_CHANNEL_2_MID_LEFT_X103Y243'
Info:     Constraining 'serial_rx' to site 'IOB_X1Y181'
Info:     Tile 'RIOB33_X105Y181'
Info:     Constraining 'IBUFDS_GTE2' to site 'IBUFDS_GTE2_X0Y2/IBUFDS_GTE2'
Info:     Constraining 'pcie_s7.pcie_7x_litepcie_inst.pipe_wrapper_i.gtpe2_channell_i' to site 'GTPE2_CHANNEL_X0Y6'
Info: Device utilisation:
Info: \t          SLICE_LUTX: 12492/269200     4%
Info: \t           SLICE_FFX:  3261/269200     1%
Info: \t            RAMB36E1:    19/  365     5%
Info: \t             DSP48E1:     0/  740     0%
Info: \t            PCIE_2_1:     1/    1   100%

Info: Placed 23 cells based on constraints.
Info: Max frequency for clock               'from1000_clk': 82.19 MHz (FAIL at 200.00 MHz)
Info: Max frequency for clock               'from1399_clk': 116.21 MHz (FAIL at 125.00 MHz)
Info: Max delay posedge from1000_clk               -> posedge from1399_clk              : 7.01 ns
Info: Routing complete.
Warning: Max frequency for clock               'from1000_clk': 73.13 MHz (FAIL at 200.00 MHz)
Info: Max frequency for clock               'from1399_clk': 132.75 MHz (PASS at 125.00 MHz)
Info: Max delay posedge from1000_clk               -> posedge from1399_clk              : 7.76 ns
"""

FASM = """\
RIOB33_X105Y181.IOB_Y0.LVCMOS12_LVCMOS15_LVCMOS18_LVCMOS25_LVCMOS33_LVDS_25_LVTTL_SSTL135_SSTL15_TMDS_33.IN_ONLY
RIOB33_X105Y181.IOB_Y0.PULLTYPE.PULLUP
RIOB33_X105Y181.IOB_Y1.PULLTYPE.NONE
RIOB33_X105Y185.IOB_Y0.PULLTYPE.PULLUP
"""


def test_clocks_are_the_routed_designs_not_the_placers_estimate():
    assert rep.clocks(LOG) == [("from1000_clk", 73.13, 200.0, False), ("from1399_clk", 132.75, 125.0, True)]


def test_a_strict_builds_missed_clock_is_an_error_line_and_still_read():
    log = "ERROR: Max frequency for clock 'pclk_clk': 197.16 MHz (FAIL at 250.00 MHz)\n"
    assert rep.clocks(log) == [("pclk_clk", 197.16, 250.0, False)]


def test_slack_is_the_period_asked_for_less_the_period_achieved():
    assert rep.slack_ns(132.75, 125.0) == pytest.approx(8.0 - 7.533, abs=1e-3)
    assert rep.slack_ns(73.13, 200.0) < 0


def test_utilisation_lists_what_is_used():
    assert rep.utilisation(LOG) == [
        ("SLICE_LUTX", 12492, 269200, 4),
        ("SLICE_FFX", 3261, 269200, 1),
        ("RAMB36E1", 19, 365, 5),
        ("PCIE_2_1", 1, 1, 100),
    ]


def test_sites_and_pullups():
    sites = rep.sites(LOG)
    assert sites["pcie_s7.pcie_7x_litepcie_inst.pipe_wrapper_i.gtpe2_channell_i"] == "GTPE2_CHANNEL_X0Y6"
    assert sites["serial_rx"] == "IOB_X1Y181"
    assert rep.pullups(FASM) == ["RIOB33_X105Y181.IOB_Y0", "RIOB33_X105Y185.IOB_Y0"]


def test_the_report_has_every_section(tmp_path, capsys):
    (tmp_path / "top_nextpnr.log").write_text(LOG)
    (tmp_path / "top.fasm").write_text(FASM)
    rep.main([str(tmp_path), "top"])
    out = capsys.readouterr().out
    assert "| `from1399_clk` | 132.75 | 125.00 | +0.467 | met |" in out
    assert "| `from1000_clk` | 73.13 | 200.00 | -8.674 | MISSED |" in out
    assert "| PCIE_2_1 | 1 | 1 | 100 |" in out
    assert "gtpe2_channell_i` on `GTPE2_CHANNEL_X0Y6`" in out
    assert "- `serial_rx` on `IOB_X1Y181`" in out
    assert "- `RIOB33_X105Y185.IOB_Y0`" in out
